#!/usr/bin/env python3
"""One-time backfill of historical wheel cycle completion events.

Reads assignment history from Alpaca Activities API, identifies completed
wheel cycles (put assigned → call assigned on same underlying), and logs
wheel_cycle_complete events via structlog so they flow to BigQuery.

Run once: python scripts/backfill_wheel_cycles.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import structlog
from datetime import datetime

from src.utils.logger import setup_logging
from src.utils.logging_events import log_position_update

setup_logging("INFO")
logger = structlog.get_logger(__name__)

# Completed wheel cycles identified from Alpaca Activities API (OPASN events).
# A cycle = put assigned (got stock) → call assigned (stock called away).
COMPLETED_CYCLES = [
    {
        "symbol": "AMD",
        "put_assignment_date": "2025-11-21",
        "put_strike": 230.0,
        "call_assignment_date": "2025-11-28",
        "call_strike": 192.50,
        "shares": 100,
    },
    {
        "symbol": "AMZN",
        "put_assignment_date": "2025-11-07",
        "put_strike": 247.50,
        "call_assignment_date": "2025-11-28",
        "call_strike": 212.50,
        "shares": 100,
    },
    {
        "symbol": "NVDA",
        "put_assignment_date": "2025-11-28",
        "put_strike": 182.50,
        "call_assignment_date": "2026-01-02",
        "call_strike": 185.0,
        "shares": 100,
    },
    {
        "symbol": "UNH",
        "put_assignment_date": "2025-11-07",
        "put_strike": 332.50,
        "call_assignment_date": "2025-11-14",
        "call_strike": 315.0,
        "shares": 100,
    },
    {
        "symbol": "UNH",
        "put_assignment_date": "2026-02-06",
        "put_strike": 282.50,
        "call_assignment_date": "2026-02-20",
        "call_strike": 282.50,
        "shares": 100,
    },
    {
        "symbol": "UNH",
        "put_assignment_date": "2026-03-27",
        "put_strike": 267.50,
        "call_assignment_date": "2026-04-02",
        "call_strike": 267.50,
        "shares": 100,
    },
]


def main():
    logger.info("Starting wheel cycle backfill",
               event_category="system",
               event_type="backfill_started",
               total_cycles=len(COMPLETED_CYCLES))

    for cycle in COMPLETED_CYCLES:
        put_date = datetime.fromisoformat(cycle["put_assignment_date"])
        call_date = datetime.fromisoformat(cycle["call_assignment_date"])
        duration_days = (call_date - put_date).days

        # Capital gain/loss from stock price movement
        capital_gain = (cycle["call_strike"] - cycle["put_strike"]) * cycle["shares"]

        log_position_update(
            logger,
            event_type="wheel_cycle_complete",
            symbol=cycle["symbol"],
            position_status="cycle_complete",
            put_strike=cycle["put_strike"],
            call_strike=cycle["call_strike"],
            capital_gain=capital_gain,
            cycle_duration_days=duration_days,
            put_assignment_date=cycle["put_assignment_date"],
            call_assignment_date=cycle["call_assignment_date"],
            shares=cycle["shares"],
            backfill=True,
        )

        print(f"  {cycle['symbol']}: {cycle['put_assignment_date']} → {cycle['call_assignment_date']} "
              f"({duration_days}d) capital_gain=${capital_gain:+,.0f}")

    logger.info("Wheel cycle backfill complete",
               event_category="system",
               event_type="backfill_completed",
               cycles_logged=len(COMPLETED_CYCLES))

    print(f"\nBackfilled {len(COMPLETED_CYCLES)} wheel cycles.")
    print("These will appear in BigQuery after the log sink processes them (~1-2 minutes).")


if __name__ == "__main__":
    main()
