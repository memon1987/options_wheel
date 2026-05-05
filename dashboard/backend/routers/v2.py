"""FC-018: wheel-centric dashboard data endpoints.

These endpoints power the new dashboard pages (Overview, Symbol drilldown,
Bot Health). They live behind `/api/v2/` to keep them clearly separated
from the legacy `/api/...` routes during the strangler migration. PR G
will drop the `v2` prefix and retire any legacy endpoints that are no
longer consumed.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional

from services.bigquery import get_bigquery_service

router = APIRouter()


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
