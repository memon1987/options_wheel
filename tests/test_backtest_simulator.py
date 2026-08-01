"""Simulator day loop (FC-032 Phase 3).

The golden path: the simulator drives the *real* WheelEngine over canned data.
Nothing here stubs strategy logic — if a rule is wrong, it is wrong in
production too.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List

import pytest

from src.backtesting.data.chain_builder import STRIKE_WINDOW_PCT, ChainBuilder
from src.backtesting.data.dividends import Dividend, DividendSchedule
from src.backtesting.data.provider import OptionBar, OptionContract, StockBar
from src.backtesting.engine.no_op_analytics import NoOpAnalyticsWriter
from src.backtesting.engine.simulator import Simulator, restrict_symbols
from src.backtesting.metrics.cycles import build_cycles
from src.backtesting.metrics.fitness import compute_fitness
from src.data import analytics_writer as analytics_module
from src.utils import clock
from src.utils.config import Config


def _occ(underlying: str, exp: date, opt: str, strike: float) -> str:
    return f"{underlying}{exp:%y%m%d}{'P' if opt == 'put' else 'C'}{int(strike * 1000):08d}"


class ScriptedProvider:
    """Canned data: one underlying, a strike ladder, every contract trades daily."""

    def __init__(self, symbol: str, closes: Dict[date, float], expirations: List[date]):
        self.symbol = symbol
        self.closes = closes
        self.expirations = expirations

    def get_stock_bars(self, symbol, start, end):
        return [
            StockBar(symbol=symbol, bar_date=d, open=c, high=c, low=c, close=c, volume=5_000_000)
            for d, c in sorted(self.closes.items())
            if start <= d <= end
        ]

    def _ladder(self, spot: float) -> List[float]:
        base = round(spot)
        return [float(base + k) for k in range(-12, 13)]

    def get_contract_universe(
        self, underlying, as_of, max_dte, *, strike_gte=None, strike_lte=None
    ):
        # Deliberately IGNORES the strike bounds — the Protocol permits a
        # provider to return a superset, and the builder is responsible for
        # narrowing. Keeping one mock ignore them keeps that guarantee tested.
        spot = self.closes.get(as_of)
        if spot is None:
            return []
        out = []
        for exp in self.expirations:
            if not (as_of <= exp <= as_of + timedelta(days=max_dte)):
                continue
            for strike in self._ladder(spot):
                for opt in ("put", "call"):
                    out.append(
                        OptionContract(_occ(underlying, exp, opt, strike), underlying,
                                       exp, strike, opt)
                    )
        return out

    def get_option_bars(self, symbols, start, end):
        """Price every contract off the day's spot with a crude but monotone model."""
        out: Dict[str, List[OptionBar]] = {}
        for sym in symbols:
            for d in _daterange(start, end):
                spot = self.closes.get(d)
                if spot is None:
                    continue
                strike = int(sym[-8:]) / 1000.0
                is_put = sym[-9] == "P"
                exp = datetime.strptime(sym[len(self.symbol):len(self.symbol) + 6], "%y%m%d").date()
                dte = max((exp - d).days, 0)
                intrinsic = max(0.0, strike - spot) if is_put else max(0.0, spot - strike)
                # Enough time value that 0.10-0.20 delta strikes clear the $0.50 floor.
                time_value = 0.9 * (dte + 1) ** 0.5 * (spot / 100.0)
                moneyness = abs(spot - strike) / spot
                price = intrinsic + time_value * max(0.05, 1.0 - 6.0 * moneyness)
                out.setdefault(sym, []).append(
                    OptionBar(symbol=sym, bar_date=d, open=price, high=price, low=price,
                              close=round(price, 2), volume=500, trade_count=50, vwap=price)
                )
        return out


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _weekdays(start: date, n: int) -> List[date]:
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


@pytest.fixture
def falling_then_flat():
    """Price slides enough to put an assigned strike ITM, then stabilizes.

    Includes ~45 sessions of warm-up history before the first decision day:
    GapDetector indexes positionally into ~30 daily bars and blocks everything
    on a cold start, exactly as it would in production against a fresh account.
    """
    warmup = _weekdays(date(2024, 3, 25), 45)
    days = _weekdays(date(2024, 6, 3), 30)
    closes = {d: 100.0 for d in warmup}
    # -3/day for 10 sessions (100 -> 70), then flat. The strategy sells puts
    # ~8% OTM, so a gentler slide would never overtake the strike before expiry
    # and the assignment path would go untested. -3 stays under GapDetector's
    # 5% overnight-gap block, which would otherwise halt trading outright.
    for i, d in enumerate(days):
        closes[d] = 100.0 - min(i, 10) * 3.0
    expirations = [d for d in days if d.weekday() == 4]  # Fridays
    return days, closes, expirations


@pytest.fixture
def dip_then_recovering():
    """Assigns a put, then RECOVERS so the call leg can actually run.

    `falling_then_flat` cannot test the call side and never could: it assigns
    at ~92 and leaves spot at 70, so the 5% drawdown pause and the cost-basis
    floor block every covered call *even with correct routing*. That fixture
    documents the call-refusal path; this one exercises the call-sale path.

    Shape: warm-up flat at 100 -> slide to put the ~8%-OTM strike ITM ->
    recover to just above cost basis and drift up, so that
      * spot >= basis, so the drawdown pause does not fire, and
      * strikes just above basis sit inside call_delta_range [0.15, 0.25], and
      * a later expiry finishes above the sold strike, so the call assigns.
    """
    warmup = _weekdays(date(2024, 3, 25), 45)
    days = _weekdays(date(2024, 6, 3), 45)
    closes = {d: 100.0 for d in warmup}
    for i, d in enumerate(days):
        if i <= 8:
            closes[d] = 100.0 - i * 3.0          # 100 -> 76, assigns ~92
        elif i <= 20:
            closes[d] = 76.0 + (i - 8) * 1.6     # recover 76 -> ~95
        else:
            closes[d] = 95.0 + (i - 20) * 0.9    # drift up through the strike
    expirations = [d for d in days if d.weekday() == 4]
    return days, closes, expirations


def _simulator(symbol, closes, expirations, days, **kw):
    provider = ScriptedProvider(symbol, closes, expirations)
    builder = ChainBuilder(provider, risk_free_rate=0.04)
    config = Config()
    return Simulator(
        config, provider, builder, [symbol], days[0], days[-1],
        starting_cash=kw.pop("starting_cash", 50_000.0), max_dte=7, **kw
    )


class TestDayLoop:
    def test_run_produces_one_state_per_trading_day(self, falling_then_flat):
        days, closes, exps = falling_then_flat
        result = _simulator("XYZ", closes, exps, days).run()
        assert [s.day for s in result.daily] == days
        assert result.start == days[0] and result.end == days[-1]

    def test_clock_is_cleared_after_the_run(self, falling_then_flat):
        days, closes, exps = falling_then_flat
        _simulator("XYZ", closes, exps, days).run()
        assert not clock.is_frozen(), "a leaked freeze would corrupt later code"

    def test_empty_window_refuses_rather_than_reporting_zero_trades(self):
        """The old engine's cardinal sin: a 0-trade run that 'succeeded'."""
        provider = ScriptedProvider("XYZ", {}, [])
        builder = ChainBuilder(provider, risk_free_rate=0.04)
        sim = Simulator(Config(), provider, builder, ["XYZ"],
                        date(2024, 6, 3), date(2024, 6, 28))
        with pytest.raises(ValueError, match="refusing to report a zero-trade run"):
            sim.run()

    def test_the_wheel_actually_turns(self, falling_then_flat):
        """A put is sold; the slide assigns it; shares appear. The engine's own code did it."""
        days, closes, exps = falling_then_flat
        result = _simulator("XYZ", closes, exps, days).run()

        kinds = [e.kind for e in result.broker.ledger]
        assert "sell_put_open" in kinds, f"no put was ever sold; ledger={kinds}"
        # The underlying falls 12%, so at least one short put must finish ITM.
        assert "put_assignment" in kinds, f"no assignment despite a 12% slide; ledger={kinds}"
        assert result.broker.shares("XYZ") > 0

    def test_no_contract_is_left_expired_but_unsettled(self, falling_then_flat):
        """Regression: settling before the decision let the engine open a fresh

        put expiring the same day, after that day's settlement had already run.
        It then sat on the book forever, corrupting equity.
        """
        days, closes, exps = falling_then_flat
        result = _simulator("XYZ", closes, exps, days).run()
        for symbol, pos in result.broker.options.items():
            assert pos.expiration >= days[-1], (
                f"{symbol} expired {pos.expiration} but is still open at {days[-1]}"
            )

    def test_no_new_put_is_opened_on_the_day_a_put_is_assigned(self, falling_then_flat):
        """Stage 6 sees the expiring position because settlement runs after the scan."""
        days, closes, exps = falling_then_flat
        result = _simulator("XYZ", closes, exps, days).run()
        assigned_days = {e.event_date for e in result.broker.ledger if e.kind == "put_assignment"}
        opened_days = {e.event_date for e in result.broker.ledger if e.kind == "sell_put_open"}
        assert not (assigned_days & opened_days), (
            "a put was sold on the same day another was assigned — the expiring "
            "position was invisible to the duplicate guard"
        )

    def test_equity_equals_cash_plus_marked_positions(self, falling_then_flat):
        """The reported curve must be arithmetic on the ledger, not a second opinion."""
        days, closes, exps = falling_then_flat
        result = _simulator("XYZ", closes, exps, days).run()
        final = result.daily[-1]
        expected = final.cash + result.broker.shares("XYZ") * closes[days[-1]]
        assert final.equity == pytest.approx(expected)

    def test_wheel_loses_less_than_buy_and_hold_through_the_crash(self, falling_then_flat):
        """Sanity anchor, not a performance claim: collateral sat in cash for most

        of a -30% slide, so the wheel must be well ahead of the underlying.
        """
        days, closes, exps = falling_then_flat
        result = _simulator("XYZ", closes, exps, days).run()
        underlying_return = (closes[days[-1]] - closes[days[0]]) / closes[days[0]]
        assert underlying_return == pytest.approx(-0.30)
        assert result.total_return > underlying_return

    def test_cash_ledger_is_conserved_no_phantom_margin(self, falling_then_flat):
        days, closes, exps = falling_then_flat
        result = _simulator("XYZ", closes, exps, days).run()
        for state in result.daily:
            assert state.reserved_collateral >= 0.0
            # Cash-secured: collateral never exceeds cash on hand.
            assert state.reserved_collateral <= state.cash + 1e-6


class TestDividendsThroughTheDayLoop:
    """FC-042 Track C, end to end.

    The fixture's put is assigned 2024-06-07 at 92.00 and the run finishes still
    holding those 100 shares, which makes it a clean bed for ex-date behavior.
    """

    ASSIGNED = date(2024, 6, 7)

    def _run(self, fixture, ex_dates, amount=0.50):
        days, closes, exps = fixture
        schedule = DividendSchedule(
            {"XYZ": [Dividend(ex_date=d, amount=amount) for d in ex_dates]}
        )
        sim = _simulator("XYZ", closes, exps, days, dividend_schedule=schedule)
        return sim.run()

    def test_dividend_is_credited_while_shares_are_held(self, falling_then_flat):
        result = self._run(falling_then_flat, [date(2024, 6, 20)])
        events = [e for e in result.broker.ledger if e.kind == "dividend"]
        assert len(events) == 1
        assert events[0].shares == 100
        assert events[0].cash_delta == pytest.approx(50.0)
        assert result.dividends_credited == pytest.approx(50.0)

    def test_nothing_is_credited_before_assignment(self, falling_then_flat):
        """No shares yet, so no dividend — the pre-assignment days are flat."""
        result = self._run(falling_then_flat, [date(2024, 6, 5)])
        assert not [e for e in result.broker.ledger if e.kind == "dividend"]
        assert result.dividends_credited == 0.0

    def test_an_ex_date_on_the_assignment_day_pays_nothing(self, falling_then_flat):
        """The ownership test is the PREVIOUS close, and this is the crux of it.

        Shares arrive at that day's expiration settlement, i.e. after the stock
        already went ex. A holder who acquires on the ex-date does not collect;
        crediting here would be free money, and it would appear on every cycle
        whose assignment happened to land on an ex-date.
        """
        result = self._run(falling_then_flat, [self.ASSIGNED])
        assert not [e for e in result.broker.ledger if e.kind == "dividend"]

    def test_the_day_after_assignment_does_pay(self, falling_then_flat):
        """Bracketing the case above: one session later, the shares are on the record."""
        result = self._run(falling_then_flat, [date(2024, 6, 10)])
        events = [e for e in result.broker.ledger if e.kind == "dividend"]
        assert len(events) == 1
        assert events[0].cash_delta == pytest.approx(50.0)

    def test_dividends_land_in_equity_and_attribution_still_reconciles(
        self, falling_then_flat
    ):
        """The acceptance criterion: attribution must still sum to the equity change.

        A dividend that reaches cash but not the attribution table would make
        every percentage in the report wrong by exactly that amount.
        """
        days, closes, exps = falling_then_flat
        base = self._run(falling_then_flat, [])
        with_div = self._run(falling_then_flat, [date(2024, 6, 20)])

        # It is real money: equity is higher by exactly the dividend.
        assert with_div.final_equity - base.final_equity == pytest.approx(50.0)

        cycles = build_cycles(with_div.broker.ledger)
        prices = {d: closes[d] for d in days}
        report = compute_fitness(
            "XYZ", with_div.daily, cycles, with_div.starting_cash,
            benchmark_prices=prices,
            benchmark_dividends_per_share=0.50,
            data_quality={"decision_days": len(with_div.daily)},
        )
        assert report.dividends == pytest.approx(50.0)
        assert report.reconciliation_gap == pytest.approx(0.0, abs=0.01)

    def test_benchmark_collects_the_dividend_too(self, falling_then_flat):
        """Crediting only the wheel would invert the bias, not remove it."""
        days, closes, exps = falling_then_flat
        result = self._run(falling_then_flat, [date(2024, 6, 20)])
        cycles = build_cycles(result.broker.ledger)
        prices = {d: closes[d] for d in days}

        without = compute_fitness(
            "XYZ", result.daily, cycles, result.starting_cash,
            benchmark_prices=prices, data_quality={"decision_days": len(result.daily)},
        )
        with_ = compute_fitness(
            "XYZ", result.daily, cycles, result.starting_cash,
            benchmark_prices=prices, benchmark_dividends_per_share=0.50,
            data_quality={"decision_days": len(result.daily)},
        )
        assert with_.benchmark.dividends > 0
        assert with_.benchmark.total_return > without.benchmark.total_return
        # And the wheel's edge shrinks accordingly — that is the bias correction.
        assert with_.excess_return < without.excess_return

    def test_no_schedule_means_no_dividends_anywhere(self, falling_then_flat):
        """The pre-FC-042 model stays reachable and stays silent."""
        days, closes, exps = falling_then_flat
        sim = _simulator(
            "XYZ", closes, exps, days, dividend_schedule=DividendSchedule.empty()
        )
        result = sim.run()
        assert result.dividends_credited == 0.0
        assert result.early_assignments == 0


class TestNoProductionSideEffects:
    def test_analytics_singleton_is_restored_after_the_run(self, falling_then_flat):
        days, closes, exps = falling_then_flat
        before = analytics_module._instance
        _simulator("XYZ", closes, exps, days).run()
        assert analytics_module._instance is before

    def test_analytics_singleton_is_restored_even_when_the_run_raises(self):
        provider = ScriptedProvider("XYZ", {}, [])
        builder = ChainBuilder(provider, risk_free_rate=0.04)
        before = analytics_module._instance
        sim = Simulator(Config(), provider, builder, ["XYZ"],
                        date(2024, 6, 3), date(2024, 6, 28))
        with pytest.raises(ValueError):
            sim.run()
        assert analytics_module._instance is before

    def test_call_seller_cannot_query_bigquery_during_a_replay(self, falling_then_flat):
        """A replay must never mix production trade history into its cost-basis floor."""
        days, closes, exps = falling_then_flat
        sim = _simulator("XYZ", closes, exps, days)
        # Reach into the engine the simulator builds by running a 1-day window.
        result = sim.run()
        assert result is not None
        # Rebuild the same engine wiring the simulator uses and assert the guard.
        from src.strategy.wheel_engine import WheelEngine
        from src.strategy.wheel_state_manager import WheelStateManager
        from unittest.mock import Mock

        engine = WheelEngine(Mock(), alpaca_client=Mock(),
                             wheel_state=WheelStateManager(),
                             allow_bigquery_cost_basis=False)
        assert engine.call_seller.allow_bigquery_cost_basis is False
        # FC-065: the gate now stops the divergence cross-check, which is the
        # only BigQuery reader left on this path. "None" is "no comparison
        # available" — it leaves the simulated broker's floor untouched.
        assert engine.call_seller._cost_basis_resolver.allow_bigquery is False
        assert engine.call_seller._cost_basis_resolver._lookup_assignment_basis(
            "XYZ", 100) is None

    def test_call_roller_cannot_query_bigquery_during_a_replay(self):
        """FC-065 Phase 2: the roller resolves its floor through the same shared
        resolver now, and ``run_rolling_cycle()`` runs *inside* the replay
        (Fridays). Without the gate forwarded, a replay's roller would query
        production trade history against CURRENT_TIMESTAMP() — the identical
        hazard the seller's gate exists for."""
        from unittest.mock import Mock, patch

        from src.strategy.wheel_engine import WheelEngine
        from src.strategy.wheel_state_manager import WheelStateManager

        config = Mock()
        config.rolling_enabled = True
        config.earnings_enabled = False
        alpaca = Mock()
        alpaca.get_positions.return_value = []

        engine = WheelEngine(config, alpaca_client=alpaca,
                             wheel_state=WheelStateManager(),
                             allow_bigquery_cost_basis=False)

        with patch('src.strategy.wheel_engine.CallRoller') as mock_roller:
            engine.run_rolling_cycle()

        assert mock_roller.call_args.kwargs['allow_bigquery_cost_basis'] is False

    def test_bigquery_fallback_stays_enabled_by_default(self):
        from unittest.mock import Mock

        from src.strategy.call_roller import CallRoller
        from src.strategy.call_seller import CallSeller

        cs = CallSeller(Mock(), Mock(), Mock())
        assert cs.allow_bigquery_cost_basis is True

        roller = CallRoller(Mock(), Mock(), Mock(), Mock(), Mock())
        assert roller.cost_basis_resolver.allow_bigquery is True


class TestNoOpAnalytics:
    def test_records_calls_and_returns_none(self):
        w = NoOpAnalyticsWriter()
        assert w.write_trade_event(symbol="XYZ", qty=1) is None
        assert w.anything_at_all("a") is None
        assert len(w.calls) == 2
        assert w.calls_named("write_trade_event")[0][2] == {"symbol": "XYZ", "qty": 1}


class TestRestrictSymbols:
    def test_narrows_universe_without_mutating_the_original(self):
        config = Config()
        original = list(config.stock_symbols)
        narrowed = restrict_symbols(config, ["NVDA"])
        assert narrowed.stock_symbols == ["NVDA"]
        assert config.stock_symbols == original


class TestAnalyticsIsolationIsReal:
    """Reviewers proved these paths were untested: mutating the analytics swap
    to a no-op left every simulator test green, meaning a replay writing
    simulated fills into the PRODUCTION analytics singleton would not be caught.
    """

    def test_noop_writer_is_installed_for_the_whole_run(self, falling_then_flat):
        """Assert the singleton is swapped *while the day loop runs*.

        Checked from inside the loop rather than by spying on
        get_analytics_writer: the strategy only reaches that call on certain
        branches, so a spy can pass vacuously by never firing. What matters is
        that any call made at any point during the run would land on the no-op.
        """
        days, closes, exps = falling_then_flat
        seen = []

        sim = _simulator("XYZ", closes, exps, days)
        original = sim._execute_opportunities

        def observing(engine, exec_engine, cycle, client):
            seen.append(type(analytics_module.get_analytics_writer()).__name__)
            return original(engine, exec_engine, cycle, client)

        sim._execute_opportunities = observing
        sim.run()

        assert seen, "day loop never ran"
        assert set(seen) == {"NoOpAnalyticsWriter"}, (
            f"strategy code would have reached {set(seen)} — a real writer sends "
            "simulated trades to production analytics"
        )

    def test_singleton_restored_when_the_run_raises_AFTER_the_swap(self):
        """The old test raised ~40 lines BEFORE the swap, so the finally never ran."""
        days = _weekdays(date(2024, 6, 3), 10)
        closes = {d: 100.0 for d in days}
        exps = [d for d in days if d.weekday() == 4]
        before = analytics_module._instance

        sim = _simulator("XYZ", closes, exps, days)
        original = sim._execute_opportunities

        def boom(*a, **kw):
            raise RuntimeError("blew up inside the day loop")

        sim._execute_opportunities = boom
        with pytest.raises(RuntimeError, match="blew up inside the day loop"):
            sim.run()

        assert analytics_module._instance is before
        assert not clock.is_frozen()


class TestStrikeWindowCoversAssignedPositions:
    """FC-042 A2 at simulator scale.

    Chains are built for the whole window before the day loop starts, so there
    is no live position to read a cost basis from. The simulator bounds it
    instead — see ``Simulator._strike_anchors``.
    """

    def test_anchors_bracket_every_price_a_position_can_be_struck_against(
        self, falling_then_flat
    ):
        """The property, not the implementation: no strike can escape the window.

        Puts are sold at or below spot and assigned lots cost at most that
        strike, so every price any position is struck against on any decision
        day must lie between the two anchors.
        """
        days, closes, expirations = falling_then_flat
        sim = _simulator("XYZ", closes, expirations, days)
        bars = sim._load_stock_bars()["XYZ"]
        ceiling, floor = sim._strike_anchors(bars)

        decision_closes = [closes[d] for d in days]
        assert ceiling >= max(decision_closes)
        assert floor <= min(decision_closes)

    def test_no_bars_yields_no_anchors(self, falling_then_flat):
        days, closes, expirations = falling_then_flat
        sim = _simulator("XYZ", closes, expirations, days)
        assert sim._strike_anchors([]) == (None, None)

    def test_warmup_bars_cannot_inflate_the_ceiling(self, falling_then_flat):
        """A split inside the warm-up buffer must not neuter the strike filter.

        Warm-up bars are tolerated across a split (the simulator only warns),
        so NVDA's pre-split 1224.40 can sit in the same series as a ~180 spot.
        Reading it as a cost basis would push the window's upper bound ~7x too
        high and turn the filter into a no-op for the whole run.
        """
        days, closes, expirations = falling_then_flat
        sim = _simulator("XYZ", closes, expirations, days)
        bars = sim._load_stock_bars()["XYZ"]
        pre_split = StockBar("XYZ", days[0] - timedelta(days=40),
                             1224.40, 1224.40, 1224.40, 1224.40, 1_000_000)
        ceiling, _ = sim._strike_anchors([pre_split, *bars])
        assert ceiling < 200.0, "warm-up close leaked into the cost-basis ceiling"

    def test_an_open_short_put_survives_a_rally_out_of_the_window(
        self, falling_then_flat
    ):
        """The lower-bound mirror of the covered-call case.

        A put sold near 0.93x spot leaves a spot-centred window once the
        underlying rallies ~24%. The contract is then missing from the chain of
        a position that is still open, which marks it at 0.00 and makes it
        impossible to close — a winning early close silently becomes a
        hold-to-expiry.
        """
        days = _weekdays(date(2024, 6, 3), 30)
        warmup = _weekdays(date(2024, 3, 25), 45)
        closes = {d: 100.0 for d in warmup}
        for i, d in enumerate(days):  # 100 -> 160, a 60% rally
            closes[d] = 100.0 + min(i, 20) * 3.0
        expirations = [d for d in days if d.weekday() == 4]

        class WideLadderProvider(ScriptedProvider):
            def _ladder(self, spot):
                return [float(k) for k in range(50, 251)]

        provider = WideLadderProvider("XYZ", closes, expirations)
        sim = Simulator(
            Config(), provider, ChainBuilder(provider, risk_free_rate=0.04),
            ["XYZ"], days[0], days[-1], starting_cash=50_000.0, max_dte=7,
        )
        stock_bars = sim._load_stock_bars()
        chains = sim._build_chains(stock_bars, sim._trading_days(stock_bars))["XYZ"]

        early_strike = 93.0  # a put sold near the start, ~0.93x spot of 100
        peak_days = [d for d in chains if closes[d] == max(closes[x] for x in days)]
        assert peak_days
        assert max(closes[d] for d in days) * (1 - STRIKE_WINDOW_PCT) > early_strike, (
            "precondition: a spot-centred window would drop the open put"
        )
        for day in peak_days:
            assert [q for q in chains[day].puts if q.strike == early_strike], (
                f"{day}: the still-open short put fell out of the chain"
            )

    def test_calls_above_cost_basis_survive_a_60_percent_drawdown(
        self, falling_then_flat
    ):
        """The failure this exists to prevent, end to end.

        Price slides 100 -> 70 and a put assigned near 92 leaves the position
        well underwater. Every covered call the strategy may write is struck at
        or above ~92, but a spot-centred window on a 70 handle stops at 87.50 —
        so the eligible call ladder would come back empty and the replay would
        report a position that simply never rolled.
        """
        days, closes, expirations = falling_then_flat

        class WideLadderProvider(ScriptedProvider):
            """A full ladder, not one pinned to +/-12 around spot.

            ScriptedProvider's default ladder is itself narrower than the
            window under test, so with it this assertion would pass or fail on
            the mock's shape rather than on the filter's.
            """

            def _ladder(self, spot):
                return [float(k) for k in range(50, 151)]

        provider = WideLadderProvider("XYZ", closes, expirations)
        builder = ChainBuilder(provider, risk_free_rate=0.04)
        sim = Simulator(
            Config(), provider, builder, ["XYZ"], days[0], days[-1],
            starting_cash=50_000.0, max_dte=7,
        )
        stock_bars = sim._load_stock_bars()
        chains = sim._build_chains(stock_bars, sim._trading_days(stock_bars))["XYZ"]

        trough = min(closes[d] for d in days)
        trough_days = [d for d in chains if closes.get(d) == trough]
        assert trough_days, "fixture must reach a trough inside the decision window"
        assert trough * (1 + STRIKE_WINDOW_PCT) < 92.0, (
            "precondition: a spot-centred window would clip the eligible calls"
        )

        for day in trough_days:
            above_basis = [q for q in chains[day].calls if q.strike >= 92.0]
            assert above_basis, (
                f"{day}: no covered call at or above cost basis in the chain"
            )


# RejectionTally.summary() keys by description (src/backtesting/engine/rejections.py),
# not by the raw stage_4_blocked event name.
STAGE_4_LABEL = "execution gap check (stage 4)"


class TestStage4ExecutionGapGate:
    """FC-036 plan tests 9 & 10 — the fixed gate, through the full engine loop.

    Test 9 pins that an ARMED threshold actually blocks inside the day loop
    (the RejectionTally wiring for stage_4_blocked was never exercised
    end-to-end). Test 10 pins Phase A's safety property: at the shipped
    shadow threshold the gate never fires, so behavior is unchanged.

    Thresholds are injected explicitly rather than read from settings.yaml, so
    these tests keep their meaning when Phase B arms the production default.
    """

    def _run(self, fixture, threshold):
        days, closes, exps = fixture
        provider = ScriptedProvider("XYZ", closes, exps)
        builder = ChainBuilder(provider, risk_free_rate=0.04)
        config = Config()
        # execution_gap_threshold is a read-only property over _config; inject
        # through the underlying dict so the arm is explicit and independent of
        # settings.yaml (which is at Phase A's shadow value).
        config._config["risk"]["gap_risk_controls"]["execution_gap_threshold"] = threshold
        sim = Simulator(
            config, provider, builder, ["XYZ"], days[0], days[-1],
            starting_cash=50_000.0, max_dte=7,
        )
        return sim.run()

    def test_armed_threshold_blocks_on_gap_days(self, falling_then_flat):
        """The slide is -3%/day; a 1.0% gate must reject those decision days."""
        result = self._run(falling_then_flat, 1.0)

        assert result.rejections.get(STAGE_4_LABEL, 0) > 0, (
            f"an armed gate must record stage-4 rejections on the slide; "
            f"got rejections={result.rejections!r}"
        )

    def test_shadow_blocks_only_on_fail_closed_not_on_gap_size(self, falling_then_flat):
        """Phase A property, stated precisely.

        The shadow threshold suppresses every *gap-magnitude* block, but stage 4
        still blocks on missing data / degenerate quotes — that path is
        fail-closed by design and fires at ANY threshold. So "999 blocks
        nothing" is false; the true property is that shadow blocks equal the
        arming-independent floor and are strictly fewer than an armed gate's.
        """
        shadow = self._run(falling_then_flat, 999)
        armed = self._run(falling_then_flat, 1.0)
        floor = self._run(falling_then_flat, 10_000)

        shadow_blocks = shadow.rejections.get(STAGE_4_LABEL, 0)
        assert shadow_blocks == floor.rejections.get(STAGE_4_LABEL, 0), (
            "shadow must add no gap-magnitude blocks over an effectively "
            f"disabled gate; got {shadow.rejections!r}"
        )
        assert shadow_blocks < armed.rejections.get(STAGE_4_LABEL, 0), (
            "an armed gate must block strictly more than shadow"
        )

    def test_shadow_matches_the_unarmed_baseline_ledger(self, falling_then_flat):
        """At 999 the ledger is identical to an effectively-disabled gate.

        This is the property that makes Phase A safe to ship ahead of the
        study: correcting the math changes nothing until it is armed.
        """
        shadow = self._run(falling_then_flat, 999)
        disabled = self._run(falling_then_flat, 10_000)

        assert [(d.day, d.equity) for d in shadow.daily] == \
               [(d.day, d.equity) for d in disabled.daily]
        assert shadow.rejections == disabled.rejections
        assert shadow.final_equity == disabled.final_equity


class TestTheCallLegActuallyRuns:
    """FC-048: every backtest before this modelled a put-only wheel.

    Covered-call opportunities carried 'strategy': 'sell_call' but no 'type',
    and ExecutionEngine routed on `opp.get('type', 'put')` — so every call was
    handed to put_seller and rejected. No test caught it because the golden
    fixture could not reach the call path at all.
    """

    def test_a_covered_call_is_sold_after_assignment(self, dip_then_recovering):
        days, closes, exps = dip_then_recovering
        result = _simulator("XYZ", closes, exps, days).run()

        kinds = [e.kind for e in result.broker.ledger]
        assert "put_assignment" in kinds, f"fixture never assigned; ledger={kinds}"
        assert "sell_call_open" in kinds, (
            f"assigned shares but NO covered call was sold — the FC-048 "
            f"misroute, or a gate blocking the call leg. ledger={kinds}"
        )
        # The call must come after the assignment that created the shares.
        assert kinds.index("sell_call_open") > kinds.index("put_assignment")

    def test_no_call_is_sold_below_cost_basis(self, dip_then_recovering):
        """Enabling the call leg must not enable selling below basis."""
        days, closes, exps = dip_then_recovering
        result = _simulator("XYZ", closes, exps, days).run()

        assigns = [e for e in result.broker.ledger if e.kind == "put_assignment"]
        calls = [e for e in result.broker.ledger if e.kind == "sell_call_open"]
        if not (assigns and calls):
            pytest.skip("covered by test_a_covered_call_is_sold_after_assignment")
        basis = assigns[0].price
        for c in calls:
            strike = float(c.symbol[-8:]) / 1000.0
            assert strike >= basis, (
                f"covered call struck at {strike} below cost basis {basis}"
            )

    def test_no_opportunity_dies_at_the_router(self, dip_then_recovering):
        """Guards a half-fix: calls found but still rejected at execution."""
        days, closes, exps = dip_then_recovering
        result = _simulator("XYZ", closes, exps, days).run()

        bad = {k: v for k, v in result.rejections.items()
               if "wrong_seller" in k or "unroutable" in k}
        assert not bad, f"opportunities died at the router: {bad}"

    def test_the_wheel_completes_a_full_cycle(self, dip_then_recovering):
        """The FC-032-planned golden path, finally real.

        put sold -> assigned -> covered call written -> called away. Before
        FC-048 the ledger stopped at the assignment on every symbol, in every
        window, in every backtest this project has ever run.
        """
        days, closes, exps = dip_then_recovering
        result = _simulator("XYZ", closes, exps, days).run()

        kinds = [e.kind for e in result.broker.ledger]
        for expected in ("sell_put_open", "put_assignment",
                         "sell_call_open", "call_assignment"):
            assert expected in kinds, (
                f"incomplete wheel: {expected!r} missing from ledger={kinds}"
            )
        # And in that order.
        assert (kinds.index("sell_put_open") < kinds.index("put_assignment")
                < kinds.index("sell_call_open") < kinds.index("call_assignment"))
