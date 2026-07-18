"""FC-030: drawdown-pause alerting tests.

Covers the threshold boundary, the single-line digest format (the marker a
Cloud Monitoring log-based policy matches on), and the degraded path — a
live-proxy outage must NOT read as "nothing is paused".
"""

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard" / "backend"))

from services.pause_alert import (  # noqa: E402
    ALERT_MARKER,
    format_pause_alert,
    select_alertable_pauses,
)


def pause(symbol, days, pct_below=0.06, strike=250.0):
    return {
        "symbol": symbol,
        "shares": 100.0,
        "assignment_strike": strike,
        "pause_floor": strike * 0.95,
        "last_close": strike * (1 - pct_below),
        "last_close_date": "2026-07-17",
        "trading_days_paused": days,
        "pct_below_strike": pct_below,
    }


class TestSelectAlertablePauses:
    def test_below_threshold_is_silent(self):
        # The whole point: a 1-day pause is normal operation, not an alert.
        assert select_alertable_pauses([pause("AMZN", 1), pause("GOOGL", 6)], 7) == []

    def test_at_threshold_alerts(self):
        # Boundary is inclusive — 7 days means 7 days, not 8.
        out = select_alertable_pauses([pause("AMZN", 7)], 7)
        assert [p["symbol"] for p in out] == ["AMZN"]

    def test_filters_mixed_set_and_sorts_longest_first(self):
        out = select_alertable_pauses(
            [pause("AMZN", 9), pause("GOOGL", 3), pause("UNH", 21)], 7)
        assert [p["symbol"] for p in out] == ["UNH", "AMZN"]

    def test_empty_pause_list(self):
        assert select_alertable_pauses([], 7) == []

    def test_missing_day_count_does_not_crash(self):
        # Defensive: a malformed row must not take down the scheduled check.
        assert select_alertable_pauses([{"symbol": "AMD"}], 7) == []

    def test_threshold_is_configurable(self):
        rows = [pause("AMZN", 10)]
        assert select_alertable_pauses(rows, 14) == []
        assert len(select_alertable_pauses(rows, 10)) == 1


class TestFormatPauseAlert:
    def test_carries_marker_and_is_single_line(self):
        msg = format_pause_alert([pause("AMZN", 9, 0.0585, 262.5)], 7)
        # Marker is the policy's match string — renaming it breaks the alert.
        assert msg.startswith(ALERT_MARKER)
        assert ALERT_MARKER == "DRAWDOWN_PAUSE_ALERT", "policy filter depends on this literal"
        assert "\n" not in msg, "must be one line so it yields one email"

    def test_includes_symbol_days_and_depth(self):
        msg = format_pause_alert([pause("AMZN", 9, 0.0585, 262.5)], 7)
        assert "AMZN" in msg
        assert "9d" in msg
        assert "5.9%" in msg
        assert "262.5" in msg

    def test_multiple_symbols_in_one_digest(self):
        msg = format_pause_alert(
            [pause("UNH", 21, 0.08, 300.0), pause("AMZN", 9, 0.06, 262.5)], 7)
        assert "2 symbol(s)" in msg
        assert "UNH" in msg and "AMZN" in msg
        assert "\n" not in msg

    def test_threshold_stated_in_message(self):
        assert ">=7 trading days" in format_pause_alert([pause("AMZN", 9)], 7)
        assert ">=14 trading days" in format_pause_alert([pause("AMZN", 20)], 14)


# The endpoint tests import routers.v2, which needs FastAPI — present in
# the dashboard image but NOT in the bot CI image where this suite runs.
# Skip is deliberately CLASS-scoped: a module-level pytest.importorskip
# would abort collection of the whole file and silently skip the pure
# tests above too (verified — it skipped all 14), turning CI green while
# testing nothing.
_HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None


@pytest.mark.skipif(not _HAS_FASTAPI,
                    reason="FastAPI only present in the dashboard image")
class TestPauseAlertCheckEndpoint:
    """Endpoint behavior — especially that a degraded evaluation is never
    silently reported as 'nothing is paused'."""

    @staticmethod
    def _run(coro):
        import asyncio
        return asyncio.new_event_loop().run_until_complete(coro)

    def test_proxy_outage_reports_degraded_not_ok(self, monkeypatch):
        import routers.v2 as v2

        async def fake_eval():
            # get_drawdown_pauses returns an empty paused list when live
            # positions are unavailable — indistinguishable from "all clear"
            # unless positions_available is honored.
            return {"paused": [], "positions_available": False}

        monkeypatch.setattr(v2, "_evaluate_drawdown_pauses", fake_eval)
        out = self._run(v2.pause_alert_check())
        assert out["status"] == "degraded"
        assert "unavailable" in out["reason"]

    def test_evaluation_exception_is_contained(self, monkeypatch):
        import routers.v2 as v2

        async def boom():
            raise RuntimeError("BigQuery exploded")

        monkeypatch.setattr(v2, "_evaluate_drawdown_pauses", boom)
        # Must not raise — the scheduler would otherwise just log a 500 and
        # the failure would be as silent as the thing we are alerting on.
        out = self._run(v2.pause_alert_check())
        assert out["status"] == "degraded"
        assert "BigQuery exploded" in out["reason"]

    def test_healthy_sub_threshold_run_is_quiet(self, monkeypatch):
        import routers.v2 as v2

        async def fake_eval():
            return {"paused": [pause("AMZN", 1)], "positions_available": True}

        monkeypatch.setattr(v2, "_evaluate_drawdown_pauses", fake_eval)
        out = self._run(v2.pause_alert_check())
        assert out["status"] == "ok"
        assert out["alerted"] is False
        assert out["paused_total"] == 1

    def test_extended_pause_alerts(self, monkeypatch):
        import routers.v2 as v2

        async def fake_eval():
            return {"paused": [pause("AMZN", 9)], "positions_available": True}

        monkeypatch.setattr(v2, "_evaluate_drawdown_pauses", fake_eval)
        out = self._run(v2.pause_alert_check())
        assert out["status"] == "ok"
        assert out["alerted"] is True
        assert [s["symbol"] for s in out["alert_symbols"]] == ["AMZN"]
