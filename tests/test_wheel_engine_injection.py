"""WheelEngine dependency-injection seam (FC-032 Phase 3).

The backtest replays the *actual* live code rather than a reimplementation of
it. That only works if injecting one client redirects every component the
engine builds. If any of them quietly keeps a real AlpacaClient, a replay would
fire live API calls mid-simulation.

FC-068 shrank what the engine builds: the put seller, call seller and gap
detector existed only to feed the deleted orchestration path, and the simulator
now constructs its own scanner and sellers on the same injected client (see
``tests/test_backtest_simulator.py``). What the engine still hangs off the
client is its market-data manager and, per roll cycle, the CallRoller.

Production behavior is unchanged: omit the argument and the real client is built.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

from src.strategy.wheel_engine import WheelEngine
from src.strategy.wheel_state_manager import WheelStateManager


class TestAlpacaClientInjection:
    def test_injected_client_reaches_every_component(self):
        sentinel = Mock(name="BacktestAlpacaClient")
        engine = WheelEngine(Mock(), alpaca_client=sentinel, wheel_state=WheelStateManager())

        assert engine.alpaca is sentinel
        # The whole surviving graph must hang off the injected client.
        assert engine.market_data.alpaca is sentinel

    def test_the_injected_client_reaches_the_roller_too(self):
        """The roll cycle builds its CallRoller per invocation, so the seam has
        to hold at call time rather than construction time — and it runs inside
        the replay (Fridays)."""
        sentinel = Mock(name="BacktestAlpacaClient")
        sentinel.get_positions.return_value = []
        config = Mock()
        config.rolling_enabled = True
        config.earnings_enabled = False
        engine = WheelEngine(config, alpaca_client=sentinel,
                             wheel_state=WheelStateManager())

        with patch("src.strategy.wheel_engine.CallRoller") as roller:
            engine.run_rolling_cycle()

        assert roller.call_args.args[0] is sentinel
        assert roller.call_args.args[1] is engine.market_data

    def test_injection_constructs_no_real_client(self):
        """A replay must not build an AlpacaClient at all — it would read creds."""
        with patch("src.strategy.wheel_engine.AlpacaClient") as real_client:
            WheelEngine(Mock(), alpaca_client=Mock(), wheel_state=WheelStateManager())
        real_client.assert_not_called()

    def test_default_still_builds_the_real_client(self):
        """Production path is untouched."""
        with patch("src.strategy.wheel_engine.AlpacaClient") as real_client:
            config = Mock()
            config.state_storage_bucket = None
            engine = WheelEngine(config)
        real_client.assert_called_once_with(config)
        assert engine.alpaca is real_client.return_value


class TestWheelStateInjection:
    def test_the_state_is_deliberately_NOT_handed_to_the_roller(self):
        """FC-078 DD-6 — T-12's engine half.

        This assertion is inverted from what it was. Pre-FC-068 the shared
        consumer was the engine's CallSeller; FC-068 deleted that seller and
        left the roller as the component the state reached. FC-078 deleted the
        roller's dependency outright: the only consumer was the debit
        tolerance's ``original_premium``, credit-only has no debit to tolerate,
        and ``STATE_STORAGE_BUCKET`` has been unset since project start so the
        state was never persisted to read back in the first place.

        Half-maintaining the fiction is worse than none, so the engine must not
        pass it — and this test fails if anyone re-wires it.
        """
        state = WheelStateManager()
        alpaca = Mock()
        alpaca.get_positions.return_value = []
        alpaca.get_orders.return_value = []
        config = Mock()
        config.rolling_enabled = True
        config.earnings_enabled = False
        engine = WheelEngine(config, alpaca_client=alpaca, wheel_state=state)
        # The engine still keeps it — reconcile_positions is a real consumer.
        assert engine.wheel_state is state

        with patch("src.strategy.wheel_engine.CallRoller") as roller:
            engine.run_rolling_cycle()

        assert state not in roller.call_args.args
        assert state not in roller.call_args.kwargs.values()
        # Positional contract: (alpaca, market_data, config, risk_manager,
        # earnings_calendar). The state used to sit at index 3.
        assert roller.call_args.args[3].__class__.__name__ == 'RiskManager'

    def test_injected_state_never_touches_cloud_storage(self):
        """A bucket-less manager must not construct a GCS client."""
        state = WheelStateManager()
        assert getattr(state, "_storage_client", None) is None

    def test_default_state_still_reads_the_configured_bucket(self):
        with patch("src.strategy.wheel_engine.AlpacaClient"), patch(
            "src.strategy.wheel_engine.WheelStateManager"
        ) as wsm:
            config = Mock()
            config.state_storage_bucket = "prod-bucket"
            WheelEngine(config)
        wsm.assert_called_once_with(storage_bucket="prod-bucket")
