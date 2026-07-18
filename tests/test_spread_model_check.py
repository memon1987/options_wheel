"""Tests for the spread-model diagnostic harness.

The RTH gate is the entire safety mechanism of this tool: it is what stops an
out-of-hours sample being quoted as an intraday measurement. It had no
coverage, so a refactor making `resolve_session` fail open would be silent.
"""

import importlib.util
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

_TOOL = (Path(__file__).resolve().parents[1]
         / "tools" / "diagnostics" / "spread_model_check.py")


def _load_tool():
    spec = importlib.util.spec_from_file_location("spread_model_check", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def tool():
    return _load_tool()


class TestResolveSession:
    def _client(self, *, is_open=None, raises=False):
        client = Mock()
        if raises:
            client.trading_client.get_clock.side_effect = RuntimeError("clock down")
            return client
        clock = Mock()
        clock.is_open = is_open
        clock.next_close = __import__("datetime").datetime(2026, 7, 20, 16, 0)
        clock.next_open = __import__("datetime").datetime(2026, 7, 20, 9, 30)
        client.trading_client.get_clock.return_value = clock
        return client

    def test_open_market_reports_rth(self, tool):
        rth, desc = tool.resolve_session(self._client(is_open=True))
        assert rth is True
        assert "OPEN" in desc

    def test_closed_market_reports_not_rth(self, tool):
        rth, desc = tool.resolve_session(self._client(is_open=False))
        assert rth is False
        assert "CLOSED" in desc

    def test_clock_failure_fails_closed(self, tool):
        """Refusing to claim RTH is the non-corrupting direction."""
        rth, desc = tool.resolve_session(self._client(raises=True))
        assert rth is False
        assert "unavailable" in desc

    def test_failure_is_distinguishable_from_a_genuine_close(self, tool):
        """Otherwise a permanently-broken gate looks like a closed market."""
        _, broken = tool.resolve_session(self._client(raises=True))
        _, closed = tool.resolve_session(self._client(is_open=False))
        assert broken != closed
