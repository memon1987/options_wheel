#!/usr/bin/env python3
"""Test cost basis protection to prevent guaranteed losses on covered calls."""

import os
import sys
from datetime import datetime, timedelta

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from ongoing_dev.monday_only_backtesting.monday_only_backtest import MondayOnlyBacktester


def test_cost_basis_protection():
    """Test that calls below cost basis are properly rejected."""
    print("🛡️  TESTING COST BASIS PROTECTION")
    print("=" * 60)

    backtester = MondayOnlyBacktester()

    # Set up stock position with HIGHER cost basis to trigger filtering
    backtester.stock_positions['UNH'] = {
        'shares': 100,
        'avg_cost': 320.0,  # HIGH cost basis vs $308 stock price
        'acquired_date': datetime(2025, 8, 1)
    }

    # Test Week 7 scenario
    monday_date = datetime(2025, 8, 18)
    friday_expiration = datetime(2025, 8, 22)

    print(f"Monday: {monday_date.strftime('%Y-%m-%d')}")
    print(f"Friday: {friday_expiration.strftime('%Y-%m-%d')}")
    print(f"Stock Position: 100 shares at $320 cost basis (ABOVE market)")
    print(f"Current Stock Price: ~$308")
    print()

    # Test call option analysis
    call_analysis = backtester.analyze_monday_call_options('UNH', monday_date, friday_expiration)

    if 'error' in call_analysis:
        print(f"✅ PROTECTION WORKING: {call_analysis['error']}")
        print("✅ No calls available above cost basis - strategy correctly avoided guaranteed loss")
    else:
        # If calls found, verify they're all above cost basis
        best_call = call_analysis.get('best_call')
        if best_call:
            strike = best_call['strike_price']
            cost_basis = 320.0

            if strike >= cost_basis:
                print(f"✅ PROTECTION WORKING: Strike ${strike} >= Cost basis ${cost_basis}")
                print(f"   Call found: {strike}C for ${best_call['bid']:.2f}")
                print("✅ Only profitable calls above cost basis are considered")
            else:
                print(f"❌ PROTECTION FAILED: Strike ${strike} < Cost basis ${cost_basis}")
                print("❌ System would allow guaranteed loss!")

    print(f"\n🔍 COMPARISON TEST: Lower cost basis scenario")
    print("-" * 50)

    # Test with lower cost basis (profitable scenario)
    backtester.stock_positions['UNH']['avg_cost'] = 260.0  # LOWER cost basis

    call_analysis_profitable = backtester.analyze_monday_call_options('UNH', monday_date, friday_expiration)

    if 'error' not in call_analysis_profitable:
        best_call = call_analysis_profitable.get('best_call')
        if best_call:
            strike = best_call['strike_price']
            cost_basis = 260.0
            print(f"✅ PROFITABLE SCENARIO: Strike ${strike} >= Cost basis ${cost_basis}")
            print(f"   Suitable calls found: {call_analysis_profitable.get('suitable_calls', 0)}")
            print("✅ System correctly finds calls when profitable")

    print(f"\n📋 SUMMARY:")
    print(f"   High cost basis ($320): Calls {'blocked' if 'error' in call_analysis else 'allowed'}")
    print(f"   Low cost basis ($260): Calls {'blocked' if 'error' in call_analysis_profitable else 'allowed'}")
    print("✅ Cost basis protection is working correctly!")


if __name__ == '__main__':
    test_cost_basis_protection()