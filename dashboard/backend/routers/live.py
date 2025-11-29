"""
Live data endpoints - proxies to the trading bot Cloud Run service.

These endpoints provide real-time data from Alpaca via the trading bot.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
import httpx
import os
import google.auth.transport.requests
import google.oauth2.id_token

router = APIRouter()

# Trading bot Cloud Run URL
TRADING_BOT_URL = os.getenv(
    "TRADING_BOT_URL",
    "https://options-wheel-strategy-799970961417.us-central1.run.app"
)

# HTTP client with timeout
client = httpx.AsyncClient(timeout=30.0)


def get_identity_token(audience: str) -> str:
    """Get an identity token for service-to-service authentication."""
    auth_req = google.auth.transport.requests.Request()
    return google.oauth2.id_token.fetch_id_token(auth_req, audience)


async def proxy_request(endpoint: str) -> Dict[str, Any]:
    """Proxy a request to the trading bot with authentication."""
    try:
        # Get identity token for Cloud Run service-to-service auth
        token = get_identity_token(TRADING_BOT_URL)
        headers = {"Authorization": f"Bearer {token}"}
        response = await client.get(f"{TRADING_BOT_URL}{endpoint}", headers=headers)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Trading bot error: {e.response.text}"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach trading bot: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Authentication error: {str(e)}"
        )


@router.get("/status")
async def get_status() -> Dict[str, Any]:
    """
    Get current algorithm status.

    Returns:
        - running: Whether the bot is active
        - paper_trading: Paper or live mode
        - last_scan: Timestamp of last opportunity scan
        - last_trade: Timestamp of last executed trade
        - next_scan: Expected time of next scan
    """
    return await proxy_request("/status")


@router.get("/account")
async def get_account() -> Dict[str, Any]:
    """
    Get current account information.

    Returns:
        - portfolio_value: Total portfolio value
        - cash: Available cash
        - buying_power: Available buying power
        - equity: Account equity
        - options_buying_power: Options-specific buying power
    """
    return await proxy_request("/account")


@router.get("/positions")
async def get_positions() -> List[Dict[str, Any]]:
    """
    Get all current positions.

    Returns list of positions with:
        - symbol: Ticker or option symbol
        - qty: Position quantity
        - side: long/short
        - market_value: Current market value
        - cost_basis: Entry cost
        - unrealized_pl: Unrealized P&L
        - asset_class: us_equity or us_option
    """
    response = await proxy_request("/positions")
    # Trading bot returns {count, positions, timestamp} wrapper
    if isinstance(response, dict) and "positions" in response:
        return response["positions"]
    # Fallback: if response is already a list, return as-is
    return response if isinstance(response, list) else []


@router.get("/config")
async def get_config() -> Dict[str, Any]:
    """
    Get current strategy configuration.

    Returns:
        - put_target_dte: Target DTE for puts
        - call_target_dte: Target DTE for calls
        - delta_ranges: Target delta ranges
        - position_limits: Max positions per ticker
        - risk_settings: Stop loss and profit target settings
    """
    return await proxy_request("/config")
