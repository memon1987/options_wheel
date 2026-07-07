"""FC-018: wheel-centric dashboard data endpoints.

These endpoints power the new dashboard pages (Overview, Symbol drilldown,
Bot Health). They live behind `/api/v2/` to keep them clearly separated
from the legacy `/api/...` routes during the strangler migration. PR G
will drop the `v2` prefix and retire any legacy endpoints that are no
longer consumed.
"""

import os

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional

from services.bigquery import get_bigquery_service

router = APIRouter()


# ----------------------------------------------------------------------
# Live-bot proxy helpers (soft-fail: FC-031 endpoints degrade with a
# labeled fallback instead of 5xx when the bot is unreachable)
# ----------------------------------------------------------------------

async def _live_nlv() -> Optional[float]:
    try:
        from routers.live import proxy_request
        account = await proxy_request("/account")
        v = account.get("portfolio_value")
        return float(v) if v is not None else None
    except Exception:
        return None


async def _live_positions() -> Optional[List[Dict[str, Any]]]:
    try:
        from routers.live import proxy_request
        response = await proxy_request("/positions")
        if isinstance(response, dict) and "positions" in response:
            return response["positions"]
        return response if isinstance(response, list) else None
    except Exception:
        return None


async def _drawdown_pause_threshold() -> tuple:
    """Single source of truth: the bot's own /config (review F8)."""
    try:
        from routers.live import proxy_request
        cfg = await proxy_request("/config")
        v = cfg.get("call_drawdown_pause_threshold")
        if v is not None:
            return float(v), "bot /config"
    except Exception:
        pass
    return float(os.getenv("DRAWDOWN_PAUSE_THRESHOLD", "0.05")), "env fallback"


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
    assignment rate."""
    bq = get_bigquery_service()
    return bq.get_put_trade_stats(days=days)


@router.get("/reconciliation")
async def reconciliation() -> Dict[str, Any]:
    """Broker-vs-ledger reconciliation identity with residual + known gaps."""
    bq = get_bigquery_service()
    nlv = await _live_nlv()
    positions = await _live_positions()
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


@router.get("/bot-health/drawdown-pauses")
async def bot_health_drawdown_pauses() -> Dict[str, Any]:
    """Symbols the R3 drawdown pause is inferred to be blocking (assignment-
    strike referenced, live share counts; labeled inferred-not-telemetry)."""
    bq = get_bigquery_service()
    positions = await _live_positions()
    threshold, source = await _drawdown_pause_threshold()
    return bq.get_drawdown_pauses(live_positions=positions,
                                  threshold=threshold,
                                  threshold_source=source)
