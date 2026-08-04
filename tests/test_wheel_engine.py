"""Tests for wheel strategy engine.

FC-068 deleted the orchestration half of ``WheelEngine`` — ``run_strategy_cycle``
and everything beneath it. Production stopped calling it on 2025-10-03, three
days before the live account's first fill, and the backtest was its only
surviving caller. The 16 tests that pinned that path are gone with it; the
behaviours worth keeping migrated to the live path's own tests:

* stage-6's naked-call/oversell half → ``ExecutionEngine._available_shares``
  and ``strict_option_type`` tests in ``tests/test_execution_engine.py``.
  (Its *open-order duplicate window* half — an unfilled resting order that a
  positions-based check cannot see — is covered by nothing on the live path
  either, before or after. That is FC-009's standing territory; this deletion
  neither widens nor closes it.)
* the covered-call floor family → ``tests/test_options_scanner.py``
  (scan-time floor) and ``tests/test_call_seller.py`` (FC-050 execute-time
  floor).
* the drawdown pause → **deleted, not migrated** (FC-065 OQ-3: it is not
  ported to the live path).

What remains here is the slimmed constructor plus a pin on the deletion itself.
The two methods production actually calls are exercised elsewhere:
``reconcile_positions`` through the backtest day loop
(``tests/test_backtest_simulator.py``) and ``run_rolling_cycle`` through
``tests/test_backtest_earnings.py`` and the roller suites
(``tests/test_call_roller*.py``). Neither had dedicated coverage here before
this FC either — noted, not introduced by it.
"""

from unittest.mock import Mock, patch

from src.strategy.wheel_engine import WheelEngine
from src.utils.config import Config


class TestWheelEngineConstruction:
    """The slimmed constructor: what it still wires, and what it must not."""

    def _engine(self):
        self.mock_config = Mock(spec=Config)
        self.mock_config.stock_symbols = ['AAPL', 'MSFT', 'GOOGL']

        with patch('src.strategy.wheel_engine.AlpacaClient') as mock_alpaca_cls, \
             patch('src.strategy.wheel_engine.MarketDataManager') as mock_market_cls:
            self.mock_alpaca = Mock()
            self.mock_market_data = Mock()
            mock_alpaca_cls.return_value = self.mock_alpaca
            mock_market_cls.return_value = self.mock_market_data
            return WheelEngine(self.mock_config)

    def test_wheel_engine_initialization(self):
        engine = self._engine()
        assert engine.config is self.mock_config
        assert engine.alpaca is self.mock_alpaca
        # The roller still needs market data of its own.
        assert engine.market_data is self.mock_market_data
        assert engine.wheel_state is not None

    def test_the_deleted_path_is_really_gone(self):
        """A partial deletion — a method left behind with no caller — is the
        state this FC exists to end. Named explicitly so a revert or a merge
        that resurrects one of them fails loudly rather than quietly restoring
        a strategy nobody trades."""
        engine = self._engine()
        for gone in (
            'run_strategy_cycle',
            '_manage_existing_positions',
            '_evaluate_option_position',
            '_can_open_new_positions',
            '_find_new_opportunities',
            '_has_existing_position',
            '_has_existing_option_position',
            'get_strategy_status',
            '_get_stock_position_for_symbol',
            '_log_daily_stock_snapshots',
        ):
            assert not hasattr(engine, gone), f"{gone} is back on WheelEngine"

    def test_the_engine_no_longer_owns_sellers_or_a_gap_detector(self):
        """The engine constructed a PutSeller, a CallSeller (with its own
        CostBasisResolver) and a GapDetector purely to feed the dead path.
        ``/run`` builds its own sellers; the gap detector module itself was
        deleted by FC-069 item 5. Holding them here would keep a second,
        divergent wiring alive."""
        engine = self._engine()
        for gone in ('put_seller', 'call_seller', 'gap_detector',
                     '_pending_underlyings'):
            assert not hasattr(engine, gone), f"{gone} is back on WheelEngine"

    def test_what_production_calls_still_exists(self):
        engine = self._engine()
        assert callable(engine.reconcile_positions)      # /run pre-trade
        assert callable(engine.run_rolling_cycle)        # Friday /roll
        assert callable(engine._extract_underlying_from_option_symbol)

    def test_the_roller_replay_gate_is_still_carried(self):
        """FC-065 Phase 2's gate rides on the engine even though the seller it
        also fed is gone."""
        with patch('src.strategy.wheel_engine.MarketDataManager'):
            engine = WheelEngine(Mock(spec=Config), alpaca_client=Mock(),
                                 allow_bigquery_cost_basis=False)
        assert engine._allow_bigquery_cost_basis is False


# =========================================================================== #
# FC-078 — the roll cycle: terminal-event contract, budget guard, open-order
# fetch (T-11, T-20)
#
# Plan: docs/plans/fc-078.md DD-5 / §4.
# =========================================================================== #

from datetime import date, timedelta  # noqa: E402

from src.strategy import wheel_engine as wheel_engine_module  # noqa: E402


TERMINAL_EVENTS = {
    'call_roll_skipped',
    'call_roll_skipped_cost_basis_unresolved',
    'call_roll_skipped_cost_basis_divergent',
    'call_roll_btc_rejected',
    'call_roll_btc_timeout_canceled',
    'call_roll_naked_exposure',
    'call_roll_completed',
    'call_roll_dry_run',
    'call_roll_execution_error',
}


def _occ(underlying, expiry, strike):
    return (f"{underlying}{expiry.strftime('%y%m%d')}C"
            f"{int(round(strike * 1000)):08d}")


class _CycleFixture:
    """A book of N short calls, each with covering shares."""

    EXPIRY = date(2026, 8, 7)

    def _book(self, symbols):
        positions = []
        for sym in symbols:
            positions.append({'symbol': _occ(sym, self.EXPIRY, 100.0),
                              'qty': '-1', 'asset_class': 'us_option'})
            positions.append({'symbol': sym, 'qty': '100',
                              'asset_class': 'us_equity',
                              'avg_entry_price': '90.00', 'side': 'long'})
        return positions

    def _engine(self, symbols, *, open_orders=None, roller_factory=None):
        config = Mock(spec=Config)
        config.rolling_enabled = True
        config.earnings_enabled = False
        config.state_storage_bucket = None

        alpaca = Mock()
        alpaca.get_positions.return_value = self._book(symbols)
        alpaca.get_orders.return_value = open_orders if open_orders is not None else []

        with patch('src.strategy.wheel_engine.MarketDataManager'):
            engine = WheelEngine(config, alpaca_client=alpaca,
                                 wheel_state=Mock())
        return engine, alpaca


class TestTheTerminalEventContract(_CycleFixture):
    """T-11. Every short call evaluated in a cycle emits EXACTLY ONE terminal
    event.

    *Catches:* any reintroduced silent path. FC-066's whole diagnosis was that
    five Fridays of production reported ``rolls_evaluated > 0,
    rolls_executed = 0`` and nothing else — three ``return None`` branches with
    no event between them.
    """

    def _run_and_collect(self, engine, side_effects):
        """Drive the cycle with a stub roller whose evaluations are scripted."""
        emitted = []

        class _StubRoller:
            def __init__(self, *a, **kw):
                pass

            def log_terminal_skip(self, option_symbol, underlying, reason, **kw):
                emitted.append(('call_roll_skipped', option_symbol, reason))

            def evaluate_roll_opportunity(self, call_pos, stock_pos, open_syms=None):
                behaviour = side_effects.pop(0)
                if behaviour == 'skip':
                    emitted.append(('call_roll_skipped',
                                    call_pos['symbol'], 'not_itm_enough'))
                    return None
                if behaviour == 'raise':
                    raise RuntimeError("boom")
                return {'symbol': call_pos['symbol'], 'behaviour': behaviour}

            def execute_roll(self, opportunity):
                if opportunity['behaviour'] == 'complete':
                    emitted.append(('call_roll_completed',
                                    opportunity['symbol'], None))
                    return {'success': True}
                emitted.append(('call_roll_naked_exposure',
                                opportunity['symbol'], None))
                return {'success': False, 'reason': 'stc_failed_naked_exposure'}

        with patch('src.strategy.wheel_engine.CallRoller', _StubRoller):
            with patch('src.strategy.wheel_engine.log_error_event') as err:
                results = engine.run_rolling_cycle()
        for c in err.call_args_list:
            emitted.append((c.kwargs['error_type'], c.kwargs.get('symbol'), None))
        return results, emitted

    def test_every_evaluated_position_emits_exactly_one_terminal(self):
        symbols = ['AAA', 'BBB', 'CCC', 'DDD']
        engine, _ = self._engine(symbols)

        results, emitted = self._run_and_collect(
            engine, ['skip', 'complete', 'naked', 'raise'])

        assert results['rolls_evaluated'] == 4
        terminals = [e for e in emitted if e[0] in TERMINAL_EVENTS]
        assert len(terminals) == 4, terminals
        # One per position, no position counted twice.
        assert len({t[1] for t in terminals}) == 4

    def test_an_exception_still_produces_a_terminal(self):
        """Per-position try/except keeps one bad symbol from killing the cycle
        — but "exactly one terminal per position" has to hold on the paths
        nobody planned for too."""
        engine, _ = self._engine(['AAA'])

        results, emitted = self._run_and_collect(engine, ['raise'])

        assert results['rolls_evaluated'] == 1
        assert [e[0] for e in emitted if e[0] in TERMINAL_EVENTS] == \
            ['call_roll_skipped']

    def test_one_bad_symbol_does_not_kill_the_cycle(self):
        engine, _ = self._engine(['AAA', 'BBB'])

        results, _ = self._run_and_collect(engine, ['raise', 'complete'])

        assert results['rolls_evaluated'] == 2
        assert results['rolls_executed'] == 1


class TestTheOpenOrderFetch(_CycleFixture):
    """DD-4 / FC-043. ``status`` is not a value filter over Alpaca's default
    page: ``'open'`` is a QUERY TOKEN, and ``AlpacaClient.get_orders`` routes it
    to ``QueryOrderStatus.OPEN``. Filtering ``status.value == 'open'`` — what
    FC-043 found in production — matched nothing at all.
    """

    def test_the_cycle_asks_for_the_open_bucket_once(self):
        engine, alpaca = self._engine(['AAA', 'BBB'])

        with patch('src.strategy.wheel_engine.CallRoller'):
            engine.run_rolling_cycle()

        alpaca.get_orders.assert_called_once_with(status='open')

    def test_open_symbols_are_forwarded_to_the_roller(self):
        conflicting = _occ('AAA', self.EXPIRY, 100.0)
        engine, _ = self._engine(
            ['AAA'], open_orders=[{'symbol': conflicting, 'status': 'new'}])

        with patch('src.strategy.wheel_engine.CallRoller') as roller_cls:
            roller = roller_cls.return_value
            roller.evaluate_roll_opportunity.return_value = None
            engine.run_rolling_cycle()

        _, kwargs = roller.evaluate_roll_opportunity.call_args
        args, _ = roller.evaluate_roll_opportunity.call_args
        assert conflicting in args[2]

    def test_an_unreadable_open_order_book_fails_closed(self):
        """Without the open-order picture the guard cannot protect against the
        double buy-to-close it exists for, so nothing is rolled."""
        engine, alpaca = self._engine(['AAA', 'BBB'])
        alpaca.get_orders.side_effect = RuntimeError("alpaca down")

        with patch('src.strategy.wheel_engine.CallRoller') as roller_cls:
            roller = roller_cls.return_value
            results = engine.run_rolling_cycle()

        assert results['rolls_skipped'] == 2
        roller.evaluate_roll_opportunity.assert_not_called()
        assert roller.log_terminal_skip.call_count == 2
        reasons = {c.args[2] for c in roller.log_terminal_skip.call_args_list}
        assert reasons == {'open_orders_unavailable'}


class TestUncoveredShortCalls(_CycleFixture):
    """Trader L-1. A short call with no matching stock position was dropped
    before the loop, silently — so the one position shape nobody wants, a
    genuinely naked short call, was the one the roll cycle never mentioned."""

    def _naked_book(self):
        return [
            {'symbol': _occ('AAA', self.EXPIRY, 100.0), 'qty': '-1',
             'asset_class': 'us_option'},
            # no AAA shares
        ]

    def test_a_short_call_with_no_covering_shares_emits_a_terminal(self):
        engine, alpaca = self._engine([])
        alpaca.get_positions.return_value = self._naked_book()

        with patch('src.strategy.wheel_engine.CallRoller') as roller_cls:
            roller = roller_cls.return_value
            results = engine.run_rolling_cycle()

        assert results['rolls_evaluated'] == 1
        assert results['rolls_skipped'] == 1
        roller.evaluate_roll_opportunity.assert_not_called()
        assert roller.log_terminal_skip.call_count == 1
        assert roller.log_terminal_skip.call_args.args[2] == 'no_covering_shares'

    def test_covered_calls_are_unaffected(self):
        engine, _ = self._engine(['AAA'])

        with patch('src.strategy.wheel_engine.CallRoller') as roller_cls:
            roller = roller_cls.return_value
            roller.evaluate_roll_opportunity.return_value = None
            results = engine.run_rolling_cycle()

        assert results['rolls_evaluated'] == 1
        roller.evaluate_roll_opportunity.assert_called_once()
        roller.log_terminal_skip.assert_not_called()


class TestTheCycleBudgetGuard(_CycleFixture):
    """T-20. A position is never STARTED without the full per-position worst
    case remaining, because a kill between a filled BTC and an unplaced STO is
    the worst seam there is — shares uncovered, no event, no alert.

    *Mutation:* drop the pre-position budget check → these fail.
    """

    def test_a_fresh_budget_proceeds(self):
        engine, _ = self._engine(['AAA'])

        with patch('src.strategy.wheel_engine.CallRoller') as roller_cls:
            roller = roller_cls.return_value
            roller.evaluate_roll_opportunity.return_value = None
            engine.run_rolling_cycle()

        roller.evaluate_roll_opportunity.assert_called_once()

    def test_an_exhausted_budget_defers_the_position(self, monkeypatch):
        engine, _ = self._engine(['AAA', 'BBB'])

        # Clock: start, then far enough past that only the worst case of one
        # position fits, then past the budget entirely.
        start = date(2026, 8, 4)
        times = iter([
            _dt(start, 0),       # cycle start
            _dt(start, 10),      # position 1 budget check — fine
            _dt(start, 1200),    # position 2 budget check — 300s left < 600s
            _dt(start, 1201),    # cycle duration
        ])
        monkeypatch.setattr(wheel_engine_module.clock, 'now', lambda: next(times))

        with patch('src.strategy.wheel_engine.CallRoller') as roller_cls:
            roller = roller_cls.return_value
            roller.evaluate_roll_opportunity.return_value = None
            results = engine.run_rolling_cycle()

        assert results['rolls_evaluated'] == 2
        assert roller.evaluate_roll_opportunity.call_count == 1
        skips = [c.args[2] for c in roller.log_terminal_skip.call_args_list]
        assert skips == ['cycle_budget_exhausted']

    def test_the_guard_reserves_the_full_per_position_worst_case(self):
        """1500 s budget, 600 s per position — the constants are the contract,
        so they are asserted rather than left to drift."""
        assert wheel_engine_module._CYCLE_BUDGET_SECONDS == 1500
        assert wheel_engine_module._PER_POSITION_BUDGET_SECONDS == 600
        # The scheduler attempt-deadline is 1800s; the budget must leave room.
        assert wheel_engine_module._CYCLE_BUDGET_SECONDS < 1800


def _dt(day, seconds):
    from datetime import datetime, time
    return datetime.combine(day, time(15, 30)) + timedelta(seconds=seconds)
