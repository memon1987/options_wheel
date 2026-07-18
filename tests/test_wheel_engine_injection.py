"""WheelEngine dependency-injection seam (FC-032 Phase 3).

The backtest replays the *actual* staged pipeline in WheelEngine rather than a
reimplementation of it. That only works if injecting one client redirects every
component the engine builds — market data, gap detector, put seller, call seller.
If any of them quietly keeps a real AlpacaClient, a replay would fire live API
calls mid-simulation.

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
        # The whole graph must hang off the injected client.
        assert engine.market_data.alpaca is sentinel
        assert engine.put_seller.alpaca is sentinel
        assert engine.call_seller.alpaca is sentinel
        assert engine.gap_detector.alpaca is sentinel

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
    def test_injected_state_is_used_and_shared_with_call_seller(self):
        state = WheelStateManager()
        engine = WheelEngine(Mock(), alpaca_client=Mock(), wheel_state=state)
        assert engine.wheel_state is state
        assert engine.call_seller.wheel_state is state

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
