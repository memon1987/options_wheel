#!/usr/bin/env python3
"""Scheduler for automated options wheel strategy execution."""

import os
import sys
import time
import schedule
import structlog
from datetime import datetime, timedelta
from typing import Dict, Any

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.utils.config import Config
from src.strategy.wheel_engine import WheelEngine

logger = structlog.get_logger(__name__)


class StrategyScheduler:
    """Automated scheduler for wheel strategy execution."""

    def __init__(self):
        """Initialize scheduler with configuration."""
        self.config = Config()
        self.wheel_engine = WheelEngine(self.config)
        self.running = False

    def is_market_open(self) -> bool:
        """Check if market is currently open."""
        now = datetime.now()

        # Basic market hours check (9:30 AM - 4:00 PM ET, Mon-Fri)
        # Note: This is simplified - production should use market calendar API
        if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False

        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)

        return market_open <= now <= market_close

    def is_trading_day(self) -> bool:
        """Check if today is a trading day."""
        # Simplified check - production should use market calendar
        return datetime.now().weekday() < 5

    def morning_scan_job(self):
        """Morning market scan for opportunities."""
        try:
            logger.info("Starting morning scan job")

            if not self.is_trading_day():
                logger.info("Not a trading day, skipping scan")
                return

            # Wait for market stabilization (15 minutes after open)
            if self.is_market_open():
                now = datetime.now()
                market_open = now.replace(hour=9, minute=30)
                if now < market_open + timedelta(minutes=15):
                    logger.info("Market just opened, waiting for stabilization")
                    return

            result = self.wheel_engine.run_strategy_cycle()
            logger.info("Morning scan completed",
                       actions=len(result.get('actions', [])),
                       opportunities=len(result.get('opportunities', [])))

        except Exception as e:
            logger.error("Morning scan job failed", error=str(e))

    def position_management_job(self):
        """Regular position management and monitoring."""
        try:
            logger.info("Starting position management job")

            if not self.is_trading_day():
                return

            # Check positions and execute management actions
            result = self.wheel_engine.manage_existing_positions()
            logger.info("Position management completed",
                       positions_checked=result.get('positions_checked', 0),
                       actions_taken=result.get('actions_taken', 0))

        except Exception as e:
            logger.error("Position management job failed", error=str(e))

    def order_status_poll_job(self):
        """Poll order statuses and log fills/expirations."""
        try:
            logger.info("Starting order status poll job")

            if not self.is_trading_day():
                return

            # Poll order statuses and log updates
            result = self.wheel_engine.poll_order_statuses()
            logger.info("Order status poll completed",
                       orders_checked=result.get('orders_checked', 0),
                       filled_logged=result.get('filled_logged', 0),
                       expired_logged=result.get('expired_logged', 0))

        except Exception as e:
            logger.error("Order status poll job failed", error=str(e))

    def end_of_day_report(self):
        """Generate end-of-day performance report."""
        try:
            logger.info("Generating end-of-day report")

            if not self.is_trading_day():
                return

            # Generate daily report
            status = self.wheel_engine.get_strategy_status()

            # Log key metrics
            logger.info("Daily performance summary",
                       total_positions=status.get('total_positions', 0),
                       cash_balance=status.get('cash_balance', 0),
                       unrealized_pnl=status.get('unrealized_pnl', 0))

            # Send notifications if configured
            self._send_daily_report(status)

        except Exception as e:
            logger.error("End-of-day report failed", error=str(e))

    def pre_market_preparation(self):
        """Pre-market preparation and gap analysis."""
        try:
            logger.info("Starting pre-market preparation")

            if not self.is_trading_day():
                return

            # Analyze overnight gaps and prepare for market open
            # This would include gap risk assessment and position adjustments
            logger.info("Pre-market analysis completed")

        except Exception as e:
            logger.error("Pre-market preparation failed", error=str(e))

    def _send_daily_report(self, status: Dict[str, Any]):
        """Send daily report via configured channels."""
        # Implement notification logic (Slack, email, etc.)
        pass

    def setup_schedule(self):
        """Set up the trading schedule."""
        logger.info("Setting up trading schedule")

        # Pre-market preparation (8:00 AM ET)
        schedule.every().day.at("08:00").do(self.pre_market_preparation)

        # Morning scan after market stabilization (9:45 AM ET)
        schedule.every().day.at("09:45").do(self.morning_scan_job)

        # Position management during market hours
        schedule.every().day.at("11:00").do(self.position_management_job)
        schedule.every().day.at("13:00").do(self.position_management_job)
        schedule.every().day.at("15:00").do(self.position_management_job)

        # Order status polling (10:00 AM, 12:00 PM, 14:00 PM, 16:00 PM ET)
        # Polls Alpaca for order fills/expirations and logs to BigQuery
        schedule.every().day.at("10:00").do(self.order_status_poll_job)
        schedule.every().day.at("12:00").do(self.order_status_poll_job)
        schedule.every().day.at("14:00").do(self.order_status_poll_job)
        schedule.every().day.at("16:00").do(self.order_status_poll_job)

        # End-of-day report (4:30 PM ET)
        schedule.every().day.at("16:30").do(self.end_of_day_report)

        logger.info("Schedule configured successfully")

    def run(self):
        """Start the scheduler."""
        logger.info("Starting options wheel scheduler")
        self.running = True
        self.setup_schedule()

        try:
            while self.running:
                schedule.run_pending()
                time.sleep(60)  # Check every minute

        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
        except Exception as e:
            logger.error("Scheduler error", error=str(e))
        finally:
            self.running = False
            logger.info("Scheduler shutdown complete")

    def stop(self):
        """Stop the scheduler."""
        self.running = False


def main():
    """Main entry point for scheduler."""
    scheduler = StrategyScheduler()

    # Handle command line arguments
    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "test":
            # Test mode - run one cycle
            scheduler.morning_scan_job()
        elif command == "report":
            # Generate report only
            scheduler.end_of_day_report()
        else:
            # Production mode - continuous scheduling
            scheduler.run()
    else:
        # Default - continuous scheduling
        scheduler.run()


if __name__ == "__main__":
    main()