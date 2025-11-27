"""
Historical data endpoints - queries BigQuery for past data.

These endpoints provide historical trading data from the BigQuery log sink.
"""

from fastapi import APIRouter, Query
from typing import Dict, Any, List

from services.bigquery import get_bigquery_service

router = APIRouter()


@router.get("/trades")
async def get_trades(
    days: int = Query(default=7, ge=1, le=365, description="Days to look back")
) -> List[Dict[str, Any]]:
    """
    Get recent trades history.

    Args:
        days: Number of days to look back (1-365)

    Returns:
        List of trade records with symbol, strategy, premium, etc.
    """
    bq = get_bigquery_service()
    return bq.get_recent_trades(days=days)


@router.get("/daily-summary")
async def get_daily_summary(
    days: int = Query(default=30, ge=1, le=365, description="Days to look back")
) -> List[Dict[str, Any]]:
    """
    Get daily operations summary.

    Args:
        days: Number of days to look back (1-365)

    Returns:
        List of daily summaries with scan counts, trades, errors.
    """
    bq = get_bigquery_service()
    return bq.get_daily_summary(days=days)


@router.get("/filtering")
async def get_filtering_stats(
    days: int = Query(default=7, ge=1, le=30, description="Days to look back")
) -> List[Dict[str, Any]]:
    """
    Get filtering pipeline statistics.

    Shows how symbols progress through the 9-stage filtering pipeline.

    Args:
        days: Number of days to look back (1-30)

    Returns:
        List of filtering stage stats per day.
    """
    bq = get_bigquery_service()
    return bq.get_filtering_stats(days=days)


@router.get("/errors")
async def get_errors(
    days: int = Query(default=7, ge=1, le=30, description="Days to look back")
) -> List[Dict[str, Any]]:
    """
    Get recent errors.

    Args:
        days: Number of days to look back (1-30)

    Returns:
        List of error records with type, message, and context.
    """
    bq = get_bigquery_service()
    return bq.get_recent_errors(days=days)


@router.get("/wheel-cycles")
async def get_wheel_cycles(
    days: int = Query(default=30, ge=1, le=90, description="Days to look back")
) -> List[Dict[str, Any]]:
    """
    Get wheel cycle (position state) history.

    Shows the progression: sell put -> assigned -> sell call -> called away

    Args:
        days: Number of days to look back (1-90)

    Returns:
        List of position update records showing wheel transitions.
    """
    bq = get_bigquery_service()
    return bq.get_position_updates(days=days)


@router.get("/portfolio-history")
async def get_portfolio_history(
    days: int = Query(default=30, ge=1, le=365, description="Days to look back")
) -> List[Dict[str, Any]]:
    """
    Get portfolio value history for charting.

    Args:
        days: Number of days of history (1-365)

    Returns:
        List of daily portfolio values.
    """
    bq = get_bigquery_service()
    return bq.get_portfolio_value_history(days=days)
