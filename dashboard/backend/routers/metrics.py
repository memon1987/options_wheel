"""
Metrics endpoints - aggregated analytics and performance data.

Combines real-time and historical data for dashboard metrics.
"""

from fastapi import APIRouter, Query
from typing import Dict, Any, List
import httpx
import os
import google.auth.transport.requests
import google.oauth2.id_token

from services.bigquery import get_bigquery_service

router = APIRouter()

TRADING_BOT_URL = os.getenv(
    "TRADING_BOT_URL",
    "https://options-wheel-strategy-799970961417.us-central1.run.app"
)


def get_identity_token(audience: str) -> str:
    """Get an identity token for service-to-service authentication."""
    auth_req = google.auth.transport.requests.Request()
    return google.oauth2.id_token.fetch_id_token(auth_req, audience)


@router.get("/summary")
async def get_metrics_summary(
    days: int = Query(default=30, ge=1, le=365, description="Days to analyze")
) -> Dict[str, Any]:
    """
    Get aggregated performance metrics.

    Args:
        days: Number of days to analyze (1-365)

    Returns:
        Dict with win rate, total premium, avg premium, trade count, etc.
    """
    bq = get_bigquery_service()
    metrics = bq.get_performance_metrics(days=days)

    # Try to get current account value
    try:
        token = get_identity_token(TRADING_BOT_URL)
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{TRADING_BOT_URL}/account", headers=headers)
            if response.status_code == 200:
                account = response.json()
                metrics['portfolio_value'] = account.get('portfolio_value', 0)
                metrics['cash'] = account.get('cash', 0)
                metrics['buying_power'] = account.get('buying_power', 0)
    except Exception:
        # Silently ignore - account data is optional
        pass

    return metrics


@router.get("/pnl-by-symbol")
async def get_pnl_by_symbol(
    days: int = Query(default=30, ge=1, le=365, description="Days to analyze")
) -> List[Dict[str, Any]]:
    """
    Get P&L breakdown by underlying symbol.

    Args:
        days: Number of days to analyze (1-365)

    Returns:
        List of per-symbol metrics: trade count, win rate, total premium.
    """
    bq = get_bigquery_service()
    return bq.get_pnl_by_symbol(days=days)


@router.get("/portfolio-chart")
async def get_portfolio_chart(
    days: int = Query(default=30, ge=1, le=365, description="Days of history")
) -> List[Dict[str, Any]]:
    """
    Get portfolio value history for charting.

    Args:
        days: Number of days of history (1-365)

    Returns:
        List of {date, portfolio_value} or {date, cumulative_premium}
    """
    bq = get_bigquery_service()
    return bq.get_portfolio_value_history(days=days)


@router.get("/expirations")
async def get_upcoming_expirations() -> List[Dict[str, Any]]:
    """
    Get upcoming option expirations from current positions.

    Returns:
        List of positions with expiration dates for calendar view.
    """
    try:
        token = get_identity_token(TRADING_BOT_URL)
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{TRADING_BOT_URL}/positions", headers=headers)
            if response.status_code == 200:
                positions = response.json()
                # Filter to options only and extract expiration info
                expirations = []
                for pos in positions:
                    if pos.get('asset_class') == 'us_option':
                        symbol = pos.get('symbol', '')
                        # Parse option symbol for expiration (e.g., AAPL250117P00170000)
                        if len(symbol) > 15:
                            try:
                                # Extract date part (YYMMDD after ticker)
                                date_part = symbol[-15:-9]
                                year = 2000 + int(date_part[:2])
                                month = int(date_part[2:4])
                                day = int(date_part[4:6])
                                exp_date = f"{year}-{month:02d}-{day:02d}"

                                expirations.append({
                                    'symbol': symbol,
                                    'expiration_date': exp_date,
                                    'qty': pos.get('qty'),
                                    'market_value': pos.get('market_value'),
                                    'unrealized_pl': pos.get('unrealized_pl')
                                })
                            except (ValueError, IndexError):
                                continue
                return sorted(expirations, key=lambda x: x['expiration_date'])
    except Exception:
        pass
    return []


@router.get("/premium-by-symbol")
async def get_premium_by_symbol(
    days: int = Query(default=30, ge=1, le=365, description="Days to analyze")
) -> List[Dict[str, Any]]:
    """
    Get premium collection breakdown by symbol.

    Args:
        days: Number of days to analyze (1-365)

    Returns:
        List of per-symbol premium data: put_premium, call_premium, total_premium, trade_count.
    """
    bq = get_bigquery_service()
    return bq.get_premium_by_symbol(days=days)


@router.get("/premium-by-day")
async def get_premium_by_day(
    days: int = Query(default=30, ge=1, le=365, description="Days of history")
) -> List[Dict[str, Any]]:
    """
    Get daily premium totals for charting.

    Args:
        days: Number of days of history (1-365)

    Returns:
        List of {date, put_premium, call_premium, total_premium, trade_count}.
    """
    bq = get_bigquery_service()
    return bq.get_premium_by_day(days=days)


@router.get("/stock-snapshots")
async def get_stock_snapshots(
    days: int = Query(default=30, ge=1, le=365, description="Days of history")
) -> List[Dict[str, Any]]:
    """
    Get daily unrealized P&L snapshots for stock holdings.

    Args:
        days: Number of days of history (1-365)

    Returns:
        List of daily stock snapshot data with unrealized P&L.
    """
    bq = get_bigquery_service()
    return bq.get_daily_stock_snapshots(days=days)
