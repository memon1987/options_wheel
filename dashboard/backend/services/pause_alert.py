"""Drawdown-pause alert selection and formatting (FC-030).

Pure functions, no FastAPI or cloud imports — same pattern as
``services/returns.py`` and ``services/lots.py``, so the logic is testable
in the bot's CI image (which does not install FastAPI; only the dashboard
image does).

The router (``routers/v2.py``) is a thin caller: it fetches pause state and
hands it here.
"""

from __future__ import annotations

from typing import Any, Dict, List

# The marker string a Cloud Monitoring log-based policy matches on.
# Renaming it silently breaks operator alerting — see
# deploy/monitoring/drawdown_pause_alert.md and the unit test asserting it.
ALERT_MARKER = "DRAWDOWN_PAUSE_ALERT"
CHECK_FAILED_MARKER = "DRAWDOWN_PAUSE_ALERT_CHECK_FAILED"

DEFAULT_THRESHOLD_DAYS = 7


def select_alertable_pauses(pauses: List[Dict[str, Any]],
                            threshold_days: int) -> List[Dict[str, Any]]:
    """Pauses at or beyond the alert threshold, longest-paused first."""
    qualifying = [p for p in pauses
                  if (p.get("trading_days_paused") or 0) >= threshold_days]
    return sorted(qualifying,
                  key=lambda p: p.get("trading_days_paused") or 0,
                  reverse=True)


def format_pause_alert(symbols: List[Dict[str, Any]], threshold_days: int) -> str:
    """One-line digest for the alert log. Single line => single email."""
    parts = [
        f"{p['symbol']} {p.get('trading_days_paused')}d "
        f"({(p.get('pct_below_strike') or 0) * 100:.1f}% below "
        f"${p.get('assignment_strike')})"
        for p in symbols
    ]
    return (f"{ALERT_MARKER} {len(symbols)} symbol(s) paused "
            f">={threshold_days} trading days: " + "; ".join(parts))
