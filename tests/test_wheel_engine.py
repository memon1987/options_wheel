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
        self.mock_config.max_total_positions = 10
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
        ``/run`` builds its own sellers; the gap detector is consumed by
        nothing (FC-069 item 5). Holding them here would keep a second,
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
