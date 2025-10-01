#!/usr/bin/env python3
"""Debug call option filtering to see why calls are being rejected."""

import os
import sys
from datetime import datetime, timedelta

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from ongoing_dev.monday_only_backtesting.monday_only_backtest import MondayOnlyBacktester


def debug_call_filtering():
    """Debug call option filtering logic."""
    print("🔍 DEBUGGING CALL OPTION FILTERING")
    print("=" * 60)

    backtester = MondayOnlyBacktester()

    # Set up stock position
    backtester.stock_positions['UNH'] = {
        'shares': 100,
        'avg_cost': 260.0,
        'acquired_date': datetime(2025, 8, 1)
    }

    # Test Week 7
    monday_date = datetime(2025, 8, 18)
    friday_expiration = datetime(2025, 8, 22)

    # Get stock price
    stock_data = backtester.data_manager.get_stock_data('UNH', monday_date, monday_date + timedelta(days=1))
    stock_price = stock_data['close'].iloc[0]
    print(f"Stock Price: ${stock_price:.2f}")

    # Get options chain
    options_chain = backtester.data_manager.get_option_chain_historical_bars('UNH', monday_date, stock_price)
    all_calls = options_chain.get('calls', [])
    print(f"Total Calls: {len(all_calls)}")

    # Filter for Friday expiration
    friday_calls = []
    target_exp_str = friday_expiration.strftime('%Y-%m-%d')

    for option in all_calls:
        exp_date = option.get('expiration_date')
        if exp_date:
            if isinstance(exp_date, str):
                exp_str = exp_date.split('T')[0]
            else:
                exp_str = exp_date.strftime('%Y-%m-%d')

            if (exp_str == target_exp_str and
                option.get('bid', 0) > 0 and
                option.get('volume', 0) > 0):
                friday_calls.append(option)

    print(f"Friday Calls: {len(friday_calls)}")

    # Apply filtering criteria
    min_premium = 0.30
    delta_min, delta_max = 0.15, 0.70

    print(f"\nFiltering Criteria:")
    print(f"  Min Premium: ${min_premium:.2f}")
    print(f"  Delta Range: {delta_min:.2f} - {delta_max:.2f}")
    print(f"  Min Strike: ${stock_price * 0.98:.2f} (98% of stock price)")

    print(f"\n{'Strike':<8} {'Premium':<8} {'Volume':<8} {'Delta':<8} {'Result'}")
    print("-" * 50)

    suitable_calls = []
    for call in friday_calls:
        premium = call.get('bid', 0)
        volume = call.get('volume', 0)
        strike = call.get('strike_price', 0)

        # Calculate delta
        moneyness = stock_price / strike if strike > 0 else 0
        if moneyness > 1.0:  # ITM calls
            itm_amount = moneyness - 1.0
            approx_delta = 0.5 + (itm_amount * 2.0)
        else:  # OTM calls
            approx_delta = 0.5 * moneyness
        approx_delta = min(0.95, max(0.05, approx_delta))

        # Check criteria
        reasons = []
        if premium < min_premium:
            reasons.append(f"Low prem (${premium:.2f})")
        if volume <= 0:
            reasons.append(f"No vol ({volume})")
        if not (delta_min <= approx_delta <= delta_max):
            reasons.append(f"Delta ({approx_delta:.3f})")
        if strike <= stock_price * 0.98:
            reasons.append(f"Too ITM (${strike:.0f})")

        if not reasons:
            suitable_calls.append(call)
            result = "✅ PASS"
        else:
            result = "❌ " + ", ".join(reasons)

        print(f"{strike:<8.0f} ${premium:<7.2f} {volume:<8.0f} {approx_delta:<8.3f} {result}")

    print(f"\nSuitable Calls: {len(suitable_calls)}")


if __name__ == '__main__':
    debug_call_filtering()