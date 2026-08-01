"""FC-018: wheel-centric dashboard data endpoints.

These endpoints power the new dashboard pages (Overview, Symbol drilldown,
Bot Health). They live behind `/api/v2/` to keep them clearly separated
from the legacy `/api/...` routes during the strangler migration. PR G
will drop the `v2` prefix and retire any legacy endpoints that are no
longer consumed.
"""

import logging
import os

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional

from services.bigquery import get_bigquery_service
from services.pause_alert import (
    CHECK_FAILED_MARKER,
    DEFAULT_THRESHOLD_DAYS,
    format_uncovered_alert,
    select_alertable_uncovered,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Live-bot proxy helpers (soft-fail: FC-031 endpoints degrade with a
# labeled fallback instead of 5xx when the bot is unreachable). These wrap
# the canonical handlers in routers/live.py — one copy of the response
# normalization, plus the soft-fail behavior these endpoints need.
# ----------------------------------------------------------------------

async def _live_nlv() -> Optional[float]:
    try:
        from routers.live import get_account
        account = await get_account()
        v = account.get("portfolio_value")
        return float(v) if v is not None else None
    except Exception:
        return None


async def _live_positions() -> Optional[List[Dict[str, Any]]]:
    try:
        from routers.live import get_positions
        return await get_positions()
    except Exception:
        return None


async def _bot_config() -> Dict[str, Any]:
    try:
        from routers.live import get_config
        return await get_config()
    except Exception:
        return {}


# `_drawdown_pause_threshold` was removed by FC-065 Phase 4. It read the bot's
# `call_drawdown_pause_threshold` to describe a gate the bot no longer has
# (OQ-3), against a reference price Phase 1 replaced. The config key itself is
# left alone — decommissioning dead knobs is FC-069's sweep, not this phase's.


# ----------------------------------------------------------------------
# Page 1 — Overview
# ----------------------------------------------------------------------

@router.get("/scorecard")
async def scorecard(
    days: int = Query(default=365, ge=1, le=3650, description="Lookback window"),
) -> List[Dict[str, Any]]:
    """Per-symbol scorecard for the Overview matrix.

    One row per underlying that traded within the lookback window. Includes
    cycle count, premium breakdown, realized P&L, current position state,
    and vs-buy-and-hold delta.
    """
    bq = get_bigquery_service()
    return bq.get_per_symbol_scorecard(days=days)


# ----------------------------------------------------------------------
# Page 2 — Per-symbol drilldown
# ----------------------------------------------------------------------

@router.get("/symbol/{underlying}/acb-timeline")
async def acb_timeline(
    underlying: str,
    days: int = Query(default=730, ge=1, le=3650),
) -> List[Dict[str, Any]]:
    """Adjusted-cost-basis walk for one underlying.

    Returns one row per premium / assignment / called-away event with the
    running ACB. Used by the per-symbol drilldown page's ACB chart.
    """
    if not underlying or len(underlying) > 10:
        raise HTTPException(status_code=400, detail="Invalid underlying")
    bq = get_bigquery_service()
    return bq.get_acb_timeline(symbol=underlying.upper(), days=days)


@router.get("/symbol/{underlying}/decision-quality")
async def decision_quality(
    underlying: str,
    days: int = Query(default=365, ge=1, le=3650),
) -> List[Dict[str, Any]]:
    """% of max profit captured at close, per closed trade for one symbol."""
    if not underlying or len(underlying) > 10:
        raise HTTPException(status_code=400, detail="Invalid underlying")
    bq = get_bigquery_service()
    return bq.get_decision_quality(symbol=underlying.upper(), days=days)


@router.get("/symbol/{underlying}/vs-buy-and-hold")
async def vs_buy_and_hold(underlying: str) -> Dict[str, Any]:
    """Wheel vs synthetic buy-and-hold for one underlying."""
    if not underlying or len(underlying) > 10:
        raise HTTPException(status_code=400, detail="Invalid underlying")
    bq = get_bigquery_service()
    result = bq.get_vs_buy_and_hold(symbol=underlying.upper())
    if result is None:
        raise HTTPException(status_code=404,
                            detail=f"No data for {underlying.upper()}")
    return result


@router.get("/symbol/{underlying}/phase-timing")
async def phase_timing(
    underlying: str,
    days: int = Query(default=730, ge=1, le=3650),
) -> Dict[str, Any]:
    """Days spent in each phase (cash / short put / long stock / covered)."""
    if not underlying or len(underlying) > 10:
        raise HTTPException(status_code=400, detail="Invalid underlying")
    bq = get_bigquery_service()
    return bq.get_phase_timing(symbol=underlying.upper(), days=days)


@router.get("/symbol/{underlying}/cycles")
async def symbol_cycles(
    underlying: str,
    days: int = Query(default=730, ge=1, le=3650),
) -> List[Dict[str, Any]]:
    """Completed wheel cycles for one underlying. Reads the FC-018 view directly.

    Replaces the legacy /api/history/wheel-cycles call from the per-symbol
    drilldown — that endpoint capped at 90 days and read from a stale
    legacy table.
    """
    if not underlying or len(underlying) > 10:
        raise HTTPException(status_code=400, detail="Invalid underlying")
    bq = get_bigquery_service()
    return bq.get_wheel_cycles_for_symbol(symbol=underlying.upper(), days=days)


@router.get("/symbol/{underlying}/stock-history")
async def stock_history(
    underlying: str,
    days: int = Query(default=365, ge=1, le=3650),
) -> List[Dict[str, Any]]:
    """Daily OHLC bars for one underlying."""
    if not underlying or len(underlying) > 10:
        raise HTTPException(status_code=400, detail="Invalid underlying")
    bq = get_bigquery_service()
    return bq.get_stock_history(symbol=underlying.upper(), days=days)


# ----------------------------------------------------------------------
# Page 3 — Bot Health
# ----------------------------------------------------------------------

@router.get("/bot-health/ingest")
async def bot_health_ingest() -> Dict[str, Any]:
    """Last-successful-ingest timestamps for FC-012/FC-018 ingestors.

    Returns a dict keyed by table name with ISO timestamp values. Null means
    no rows yet (or the table doesn't exist).
    """
    bq = get_bigquery_service()
    return bq.get_ingest_health()


# ----------------------------------------------------------------------
# FC-031 — portfolio returns, reconciliation, cycle/put stats, bot health
# ----------------------------------------------------------------------

@router.get("/portfolio/returns")
async def portfolio_returns() -> Dict[str, Any]:
    """XIRR / TWR / max drawdown ($ and %) from JNLC flows + equity history.

    Live NLV replaces any same-date equity row; falls back to the last
    equity row (labeled in nlv_source) when the bot proxy is unreachable.
    """
    bq = get_bigquery_service()
    nlv = await _live_nlv()
    return bq.get_portfolio_returns(current_nlv=nlv)


@router.get("/portfolio/equity-curve")
async def portfolio_equity_curve(
    days: int = Query(default=3650, ge=7, le=3650),
) -> List[Dict[str, Any]]:
    """TWR-indexed account curve vs SPY price index (base 100)."""
    bq = get_bigquery_service()
    return bq.get_equity_curve_indexed(days=days)


@router.get("/cycle-stats")
async def cycle_stats(
    days: int = Query(default=3650, ge=1, le=3650),
) -> Dict[str, Any]:
    """Closed-wheel-cycle win rate / expectancy with FC-020 exclusions
    disclosed, open-cycle MTM shown, and an FC-029 regime split."""
    bq = get_bigquery_service()
    return bq.get_wheel_cycle_stats(days=days)


@router.get("/put-stats")
async def put_stats(
    days: int = Query(default=3650, ge=1, le=3650),
) -> Dict[str, Any]:
    """Unassigned-put stats (separate from cycle stats) + held-to-expiry
    assignment rate vs the put delta band."""
    bq = get_bigquery_service()
    cfg = await _bot_config()
    return bq.get_option_trade_stats("put", days=days,
                                     delta_band=cfg.get("put_delta_range"))


@router.get("/call-stats")
async def call_stats(
    days: int = Query(default=3650, ge=1, le=3650),
) -> Dict[str, Any]:
    """Call-trade stats — the symmetric twin of /put-stats (Wheel Strategy
    Symmetry Principle): held-to-expiry CALLED-AWAY rate vs the call delta
    band, the calibration that matters most post-FC-029."""
    bq = get_bigquery_service()
    cfg = await _bot_config()
    return bq.get_option_trade_stats("call", days=days,
                                     delta_band=cfg.get("call_delta_range"))


@router.get("/reconciliation")
async def reconciliation() -> Dict[str, Any]:
    """Broker-vs-ledger reconciliation identity with residual + known gaps."""
    import asyncio
    bq = get_bigquery_service()
    nlv, positions = await asyncio.gather(_live_nlv(), _live_positions())
    return bq.get_reconciliation(current_nlv=nlv, live_positions=positions)


@router.get("/monthly-cashflow")
async def monthly_cashflow(
    months: int = Query(default=24, ge=1, le=120),
) -> List[Dict[str, Any]]:
    """Net option cash flow by month (put/call split, gross in payload)."""
    bq = get_bigquery_service()
    return bq.get_monthly_cashflow(months=months)


@router.get("/bot-health/anomalies")
async def bot_health_anomalies() -> List[Dict[str, Any]]:
    """Anomaly flags on the SPY-bar trading calendar (independent of the
    scheduler, so a totally dead scheduler still lights up)."""
    bq = get_bigquery_service()
    return bq.get_bot_anomalies()


def _alert_threshold_days() -> int:
    """Trading-day threshold for the uncovered alert.

    Read from the same ``PAUSE_ALERT_THRESHOLD_DAYS`` env var FC-030 declared
    in ``cloudbuild.yaml`` — the repoint changes the alert's data source, not
    its deployment surface, so no env or scheduler edit is required.
    """
    try:
        return int(os.getenv("PAUSE_ALERT_THRESHOLD_DAYS",
                             str(DEFAULT_THRESHOLD_DAYS)))
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD_DAYS


async def _evaluate_uncovered_symbols() -> Dict[str, Any]:
    """Shared evaluation — one computation, two consumers (the Bot Health
    card and the daily alert check).

    FC-065 Phase 4: sourced from the bot's decision records rather than from
    an OPASN-strike price inference. The old ``call_drawdown_pause_threshold``
    percentage is no longer consulted here at all: there is no pause gate for
    it to describe, and after Phase 1 it would have been compared against the
    wrong floor anyway.
    """
    bq = get_bigquery_service()
    positions = await _live_positions()
    result = bq.get_uncovered_symbols(live_positions=positions,
                                      threshold_days=_alert_threshold_days())
    # Distinguish "no symbol is uncovered" from "we could not tell" — the
    # alert path must not read a proxy outage as all-clear.
    result["positions_available"] = positions is not None
    return result


@router.get("/bot-health/drawdown-pauses")
async def bot_health_uncovered_symbols() -> Dict[str, Any]:
    """Held symbols with no covered call written, from the bot's decision
    records (FC-065 Phase 4 — was pause inference off the OPASN strike).

    The route path is unchanged on purpose: it is the frontend's contract and
    a bookmarkable URL. The payload is the new uncovered shape, and
    ``types/v2.ts`` + ``DrawdownPauseCard.tsx`` move with it.
    """
    return await _evaluate_uncovered_symbols()


@router.post("/bot-health/pause-alert-check")
async def pause_alert_check() -> Dict[str, Any]:
    """Log an alert when a held symbol has been uncovered too long.

    Triggered daily post-close by Cloud Scheduler (route and schedule
    unchanged by FC-065 Phase 4 — only the data source moved). Emits ONE
    WARNING line carrying the marker `DRAWDOWN_PAUSE_ALERT` when any symbol
    has been uncovered >= PAUSE_ALERT_THRESHOLD_DAYS trading days; a Cloud
    Monitoring log-based policy turns that into an operator email.

    Returns the evaluation either way so the check is manually invokable.
    """
    threshold_days = _alert_threshold_days()

    try:
        result = await _evaluate_uncovered_symbols()
    except Exception as exc:  # noqa: BLE001 - must never raise past the scheduler
        # A silent evaluator is the FC-006 failure mode. Log loudly.
        logger.warning("%s evaluation raised: %s", CHECK_FAILED_MARKER, exc)
        return {"status": "degraded", "reason": str(exc),
                "threshold_days": threshold_days}

    if not result.get("positions_available"):
        logger.warning("%s live positions unavailable; uncovered state "
                       "could not be evaluated", CHECK_FAILED_MARKER)
        return {"status": "degraded", "reason": "live positions unavailable",
                "threshold_days": threshold_days}

    alertable = select_alertable_uncovered(result.get("uncovered", []),
                                           threshold_days)
    if alertable:
        logger.warning(format_uncovered_alert(alertable, threshold_days))

    # A symbol whose uncovered_days could not be derived is reported as
    # degraded, not as clear: the bot is holding shares and we cannot say
    # whether it has written a call against them, which is the state this
    # alert exists to make impossible to miss.
    unknown = result.get("unknown_uncovered_days", [])
    if unknown:
        logger.warning("%s uncovered_days underivable for %s",
                       CHECK_FAILED_MARKER,
                       ",".join(str(r.get("symbol")) for r in unknown))

    return {
        "status": "ok",
        "threshold_days": threshold_days,
        "alerted": bool(alertable),
        "alert_symbols": alertable,
        "uncovered_total": len(result.get("uncovered", [])),
        "unknown_total": len(unknown),
    }
