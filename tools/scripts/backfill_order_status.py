#!/usr/bin/env python3
"""
Backfill Order Status Script

This script queries BigQuery for historical orders that don't have status updates,
then checks Alpaca for their current status and logs the appropriate events.

This enables historical order tracking in the dashboard before the polling job
was implemented.

Usage:
    python tools/scripts/backfill_order_status.py --days 30 --dry-run
    python tools/scripts/backfill_order_status.py --days 30  # Live mode
"""

import os
import sys
import argparse
from datetime import datetime
from typing import Dict, List, Any

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import structlog
from google.cloud import bigquery

from src.utils.config import Config
from src.api.alpaca_client import AlpacaClient
from src.utils.logging_events import log_order_status_update

logger = structlog.get_logger(__name__)


def get_pending_orders_from_bigquery(days: int = 30) -> List[Dict[str, Any]]:
    """Query BigQuery for orders without status updates.

    Args:
        days: Number of days to look back

    Returns:
        List of orders with order_id that need status backfill
    """
    project_id = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT", "gen-lang-client-0607444019")
    dataset = f"{project_id}.options_wheel_logs"

    client = bigquery.Client(project=project_id)

    # Find orders that have *_executed events but no corresponding status update
    query = f"""
    WITH submitted_orders AS (
        SELECT DISTINCT
            order_id,
            symbol,
            underlying,
            strategy,
            event_type as original_event,
            timestamp_et
        FROM `{dataset}.trades_executed`
        WHERE date_et >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND event_type IN ('put_sale_executed', 'call_sale_executed', 'buy_to_close_executed')
            AND order_id IS NOT NULL
            AND order_id != ''
    ),
    status_updates AS (
        SELECT DISTINCT order_id
        FROM `{dataset}.trades_executed`
        WHERE date_et >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND event_type IN ('order_filled', 'order_expired', 'order_canceled')
            AND order_id IS NOT NULL
    )
    SELECT
        s.order_id,
        s.symbol,
        s.underlying,
        s.strategy,
        s.original_event,
        s.timestamp_et
    FROM submitted_orders s
    LEFT JOIN status_updates u ON s.order_id = u.order_id
    WHERE u.order_id IS NULL
    ORDER BY s.timestamp_et DESC
    """

    try:
        job = client.query(query)
        results = job.result(timeout=60)
        return [dict(row.items()) for row in results]
    except Exception as e:
        logger.error("Failed to query BigQuery for pending orders", error=str(e))
        return []


def extract_underlying(option_symbol: str) -> str:
    """Extract underlying symbol from option symbol."""
    if not option_symbol:
        return "Unknown"
    for i, char in enumerate(option_symbol):
        if char.isdigit():
            return option_symbol[:i]
    return option_symbol


def backfill_order_statuses(days: int = 30, dry_run: bool = True) -> Dict[str, int]:
    """Backfill order statuses from Alpaca.

    Args:
        days: Number of days to look back
        dry_run: If True, don't actually log events

    Returns:
        Summary statistics
    """
    stats = {
        'orders_found': 0,
        'filled': 0,
        'expired': 0,
        'canceled': 0,
        'pending': 0,
        'errors': 0,
        'not_found': 0
    }

    # Get pending orders from BigQuery
    pending_orders = get_pending_orders_from_bigquery(days)
    stats['orders_found'] = len(pending_orders)

    if not pending_orders:
        logger.info("No pending orders found that need backfill")
        return stats

    logger.info(f"Found {len(pending_orders)} orders to check", dry_run=dry_run)

    # Initialize Alpaca client
    config = Config()
    alpaca = AlpacaClient(config)

    for order in pending_orders:
        order_id = order.get('order_id')
        # Handle UUID object string format: UUID('xxx') -> xxx
        if order_id and isinstance(order_id, str) and order_id.startswith("UUID('"):
            order_id = order_id.replace("UUID('", "").replace("')", "")
        elif hasattr(order_id, 'hex'):  # It's a UUID object
            order_id = str(order_id)

        symbol = order.get('symbol', '')
        underlying = order.get('underlying') or extract_underlying(symbol)
        strategy = order.get('strategy', 'unknown')

        try:
            # Get order status from Alpaca
            order_details = alpaca.get_order_by_id(order_id)
            status = order_details.get('status', '').lower()

            logger.info(f"Order {order_id}: {status}",
                       symbol=symbol,
                       underlying=underlying,
                       strategy=strategy)

            if dry_run:
                # Just count, don't log
                if status == 'filled':
                    stats['filled'] += 1
                elif status == 'expired':
                    stats['expired'] += 1
                elif status in ('canceled', 'cancelled'):
                    stats['canceled'] += 1
                else:
                    stats['pending'] += 1
            else:
                # Log the status update event
                if status == 'filled':
                    log_order_status_update(
                        logger,
                        event_type="order_filled",
                        order_id=order_id,
                        symbol=symbol,
                        status=status,
                        underlying=underlying,
                        strategy=strategy,
                        filled_qty=order_details.get('filled_qty', 0),
                        filled_avg_price=order_details.get('filled_avg_price'),
                        filled_at=order_details.get('filled_at', ''),
                        backfill=True
                    )
                    stats['filled'] += 1

                elif status == 'expired':
                    log_order_status_update(
                        logger,
                        event_type="order_expired",
                        order_id=order_id,
                        symbol=symbol,
                        status=status,
                        underlying=underlying,
                        strategy=strategy,
                        backfill=True
                    )
                    stats['expired'] += 1

                elif status in ('canceled', 'cancelled'):
                    log_order_status_update(
                        logger,
                        event_type="order_canceled",
                        order_id=order_id,
                        symbol=symbol,
                        status=status,
                        underlying=underlying,
                        strategy=strategy,
                        backfill=True
                    )
                    stats['canceled'] += 1

                else:
                    # Still pending or in another non-final state
                    stats['pending'] += 1

        except Exception as e:
            error_msg = str(e)
            if 'order not found' in error_msg.lower() or '404' in error_msg:
                logger.warning(f"Order not found in Alpaca (may be too old)",
                             order_id=order_id)
                stats['not_found'] += 1
            else:
                logger.error(f"Failed to get order status",
                            order_id=order_id,
                            error=error_msg)
                stats['errors'] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description='Backfill order statuses from Alpaca')
    parser.add_argument('--days', type=int, default=30,
                       help='Number of days to look back (default: 30)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be done without logging events')

    args = parser.parse_args()

    logger.info("Starting order status backfill",
               days=args.days,
               dry_run=args.dry_run)

    stats = backfill_order_statuses(days=args.days, dry_run=args.dry_run)

    logger.info("Backfill completed", **stats)

    # Print summary
    print("\n" + "="*50)
    print("Order Status Backfill Summary")
    print("="*50)
    print(f"Orders Found:    {stats['orders_found']}")
    print(f"Filled:          {stats['filled']}")
    print(f"Expired:         {stats['expired']}")
    print(f"Canceled:        {stats['canceled']}")
    print(f"Still Pending:   {stats['pending']}")
    print(f"Not Found:       {stats['not_found']}")
    print(f"Errors:          {stats['errors']}")
    print("="*50)

    if args.dry_run:
        print("\nThis was a DRY RUN. No events were logged.")
        print("Run without --dry-run to actually log status updates.")


if __name__ == "__main__":
    main()
