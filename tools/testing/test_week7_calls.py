#!/usr/bin/env python3
"""Test Week 7 call option detection after fixing the expiration date bug."""

import os
import sys
from datetime import datetime, timedelta

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from ongoing_dev.monday_only_backtesting.monday_only_backtest import MondayOnlyBacktester


def test_week7_calls():
    """Test call option detection for Week 7 specifically."""
    print("🔍 TESTING WEEK 7 CALL OPTION DETECTION")
    print("=" * 60)

    backtester = MondayOnlyBacktester()

    # Set up stock position (from Week 4 assignment)
    backtester.stock_positions['UNH'] = {
        'shares': 100,
        'avg_cost': 260.0,
        'acquired_date': datetime(2025, 8, 1)
    }

    # Test Week 7 specifically
    monday_date = datetime(2025, 8, 18)
    friday_expiration = datetime(2025, 8, 22)

    print(f"Monday: {monday_date.strftime('%Y-%m-%d')}")
    print(f"Friday: {friday_expiration.strftime('%Y-%m-%d')}")
    print(f"Stock Position: 100 shares at $260 cost basis")
    print()

    # Test call option analysis
    call_analysis = backtester.analyze_monday_call_options('UNH', monday_date, friday_expiration)

    if 'error' in call_analysis:
        print(f"❌ Error: {call_analysis['error']}")
    else:
        print("✅ Call analysis completed successfully!")
        print(f"Best call found: {call_analysis.get('best_call', 'None')}")


if __name__ == '__main__':
    test_week7_calls()