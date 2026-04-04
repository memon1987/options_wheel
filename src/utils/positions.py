"""Position filtering utilities shared across strategy modules."""

from typing import Dict, List, Any


def get_stock_positions(positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter positions to only include long US equity (stock) positions.

    This consolidates the duplicated position filtering pattern used
    across options_scanner, portfolio_tracker, and wheel_engine.

    Args:
        positions: List of position dicts from Alpaca API

    Returns:
        List of positions where asset_class is 'us_equity' and qty > 0
    """
    return [
        p for p in positions
        if p.get('asset_class') == 'us_equity' and float(p.get('qty', 0)) > 0
    ]
