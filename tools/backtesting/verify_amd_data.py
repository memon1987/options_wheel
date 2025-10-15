#!/usr/bin/env python3
"""Verify AMD options data API by fetching ATM puts at each backtest interval."""

import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config import Config
from src.api.alpaca_client import AlpacaClient
from src.backtesting.cloud_storage import EnhancedHistoricalDataManager
import structlog

logger = structlog.get_logger(__name__)


def get_atm_strike(stock_price: float, strike_increment: float = 5.0) -> float:
    """Round stock price to nearest strike price."""
    return round(stock_price / strike_increment) * strike_increment


def main():
    """Fetch ATM put for each weekly interval in 2025 YTD."""
    print("="*80)
    print("AMD OPTIONS DATA API VERIFICATION")
    print("Testing ATM Put Fetching at Weekly Intervals")
    print("="*80)
    print()

    try:
        # Initialize
        config = Config()
        alpaca_client = AlpacaClient(config)
        data_manager = EnhancedHistoricalDataManager(config)

        # Define intervals (weekly from Jan 1 to Oct 6, 2025)
        start_date = datetime(2025, 1, 1)
        end_date = datetime(2025, 10, 6)

        # Generate weekly dates (every Wednesday during trading hours)
        intervals = []
        current_date = start_date
        while current_date <= end_date:
            # Skip weekends
            if current_date.weekday() < 5:  # Monday=0, Friday=4
                intervals.append(current_date.date())
            current_date += timedelta(days=7)

        print(f"Testing {len(intervals)} weekly intervals from {start_date.date()} to {end_date.date()}")
        print()

        # Get stock data first
        print("Fetching AMD stock price history...")
        # Calculate days from start_date to now
        days_needed = (datetime.now() - start_date).days + 100
        stock_data = alpaca_client.get_stock_bars('AMD', days=days_needed)
        print(f"✓ Fetched {len(stock_data)} days of stock data")
        print()

        # Create price lookup - index is the date
        stock_prices = {idx.date(): row['close'] for idx, row in stock_data.iterrows()}

        # Fetch ATM put for each interval
        print("="*80)
        print("ATM PUT OPTIONS AT EACH INTERVAL")
        print("="*80)
        print()
        print(f"{'Date':<12} {'Stock Price':>12} {'ATM Strike':>12} {'Put Available':>15} {'Premium':>10} {'Delta':>8}")
        print("-"*80)

        successful = 0
        failed = 0

        for test_date in intervals:
            try:
                # Get stock price for this date
                if test_date not in stock_prices:
                    print(f"{test_date!s:<12} {'N/A':>12} {'N/A':>12} {'No stock data':>15}")
                    failed += 1
                    continue

                stock_price = stock_prices[test_date]
                atm_strike = get_atm_strike(stock_price)

                # Fetch option chain for this date - convert to datetime
                test_datetime = datetime.combine(test_date, datetime.min.time())
                option_chain = data_manager.get_option_chain_historical_bars(
                    underlying='AMD',
                    date=test_datetime,
                    underlying_price=stock_price
                )

                # Find ATM put
                puts = option_chain.get('puts', [])

                if not puts:
                    print(f"{test_date!s:<12} ${stock_price:>11.2f} ${atm_strike:>11.2f} {'No puts found':>15}")
                    failed += 1
                    continue

                # Find put closest to ATM strike with 7 DTE
                atm_put = None
                min_strike_diff = float('inf')

                for put in puts:
                    if put['dte'] <= 7:  # Within 7 days
                        strike_diff = abs(put['strike_price'] - atm_strike)
                        if strike_diff < min_strike_diff:
                            min_strike_diff = strike_diff
                            atm_put = put

                if atm_put:
                    premium = atm_put.get('mid_price', atm_put.get('close', 0))
                    delta = atm_put.get('delta', 0)
                    print(f"{test_date!s:<12} ${stock_price:>11.2f} ${atm_put['strike_price']:>11.2f} "
                          f"{'✓ YES':>15} ${premium:>9.2f} {abs(delta):>7.3f}")
                    successful += 1
                else:
                    print(f"{test_date!s:<12} ${stock_price:>11.2f} ${atm_strike:>11.2f} {'No ATM match':>15}")
                    failed += 1

            except Exception as e:
                error_msg = str(e)
                if len(error_msg) > 50:
                    logger.error(f"Failed to fetch data for {test_date}", error=error_msg)
                print(f"{test_date!s:<12} {'ERROR':>12} {'ERROR':>12} {error_msg[:30]:>15}")
                failed += 1

        print("-"*80)
        print(f"Total: {len(intervals)} intervals | Successful: {successful} | Failed: {failed}")
        print()

        # Summary
        print("="*80)
        print("DATA API VERIFICATION SUMMARY")
        print("="*80)
        print()

        success_rate = (successful / len(intervals)) * 100 if intervals else 0

        print(f"Success Rate: {success_rate:.1f}%")
        print(f"Intervals Tested: {len(intervals)}")
        print(f"Successful Fetches: {successful}")
        print(f"Failed Fetches: {failed}")
        print()

        if success_rate >= 80:
            print("✅ DATA API IS WORKING CORRECTLY")
            print("   Options data is available for most intervals")
        elif success_rate >= 50:
            print("⚠️  DATA API IS PARTIALLY WORKING")
            print("   Some intervals have missing data")
        else:
            print("❌ DATA API HAS ISSUES")
            print("   Most intervals are failing")

        print()
        print("="*80)

        return 0 if success_rate >= 80 else 1

    except Exception as e:
        import traceback
        logger.error("Data verification failed", error=str(e))
        print(f"\n❌ ERROR: {str(e)}")
        print("\nFull traceback:")
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
