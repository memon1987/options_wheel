"""Uncovered-position alert selection and formatting (FC-030, repointed by FC-065 Phase 4).

Pure functions, no FastAPI or cloud imports — same pattern as
``services/returns.py`` and ``services/lots.py``, so the logic is testable
in the bot's CI image (which does not install FastAPI; only the dashboard
image does).

The router (``routers/v2.py``) is a thin caller: it fetches the decision
records and hands them here.

**What changed and what deliberately did not (FC-065 Phase 4).**

*Changed — the data source and the question.* FC-030 alerted on "symbol
paused >= 7 trading days", inferred from price versus the latest OPASN put
strike. There is no pause gate any more (OQ-3 removed it) and the bot's floor
moved to Alpaca's ``avg_entry_price`` in Phase 1, so that inference described
neither a real state nor the right number. The alert now fires on **"symbol
uncovered >= 7 trading days"**, read from the bot's own decision records —
the outcome that actually costs money (idle capital), rather than a proxy for
a gate that no longer exists.

*Not changed — the marker strings.* ``DRAWDOWN_PAUSE_ALERT`` and
``DRAWDOWN_PAUSE_ALERT_CHECK_FAILED`` are the literals the deployed Cloud
Monitoring log-based policy matches on, on the operator's one verified email
channel. Renaming them would silently disarm the alert — the exact failure
the FC-030 fire drill caught, in a different costume. They stay, and the
policy needs no edit for this repoint.
"""

from __future__ import annotations

from typing import Any, Dict, List

# The marker string a Cloud Monitoring log-based policy matches on.
# Renaming it silently breaks operator alerting — see
# deploy/monitoring/drawdown_pause_alert.md and the unit test asserting it.
ALERT_MARKER = "DRAWDOWN_PAUSE_ALERT"
CHECK_FAILED_MARKER = "DRAWDOWN_PAUSE_ALERT_CHECK_FAILED"

DEFAULT_THRESHOLD_DAYS = 7


def select_alertable_uncovered(rows: List[Dict[str, Any]],
                               threshold_days: int) -> List[Dict[str, Any]]:
    """Rows at or beyond the alert threshold, longest-uncovered first.

    A row whose ``uncovered_days`` is missing or ``None`` never qualifies —
    "we could not tell" must not manufacture an alert. It is surfaced through
    the separate ``unknown_uncovered_days`` list instead, which is what keeps
    it from reading as "all clear" either.
    """
    qualifying = [r for r in rows
                  if (r.get("uncovered_days") or 0) >= threshold_days]
    return sorted(qualifying,
                  key=lambda r: r.get("uncovered_days") or 0,
                  reverse=True)


def format_uncovered_alert(symbols: List[Dict[str, Any]],
                           threshold_days: int) -> str:
    """One-line digest for the alert log. Single line => single email.

    ``underwater_pct`` is signed with negative meaning below the floor (the
    plan's own convention), so it is rendered with its sign rather than as a
    "below" magnitude — an operator reading ``+2.1%`` learns something a
    "2.1% below" label would have inverted.
    """
    parts = []
    for r in symbols:
        underwater = r.get("underwater_pct")
        floor = r.get("cost_basis_per_share")
        depth = (f"{underwater * 100:+.1f}% vs floor"
                 if isinstance(underwater, (int, float)) else "depth unknown")
        floor_txt = (f" ${float(floor):.2f}"
                     if isinstance(floor, (int, float)) else "")
        parts.append(f"{r.get('symbol')} {r.get('uncovered_days')}d "
                     f"({depth}{floor_txt})")
    return (f"{ALERT_MARKER} {len(symbols)} symbol(s) uncovered "
            f">={threshold_days} trading days: " + "; ".join(parts))
