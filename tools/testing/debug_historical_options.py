#!/usr/bin/env python3
"""Debug historical options data availability."""

import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.backtesting.historical_data import HistoricalDataManager
from src.utils.config import Config


def debug_historical_options():
    """Debug what historical options data is available."""
    print("🔍 DEBUGGING HISTORICAL OPTIONS DATA")
    print("=" * 50)

    load_dotenv()
    config = Config("config/settings.yaml")
    data_manager = HistoricalDataManager(config)

    symbol = "UNH"

    # Test different dates
    test_dates = [
        "2025-09-27",  # More recent
        "2025-09-26",  # The expiration date itself
        "2025-09-25",  # Day before expiration
        "2025-09-24",  # Two days before
        "2025-09-23",  # Three days before
        "2025-09-22"   # Original target date
    ]

    for date_str in test_dates:
        print(f"\n📅 Testing date: {date_str}")

        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d')

            # Try to get available expirations first
            try:
                expirations = data_manager.get_available_expirations(symbol, target_date)
                print(f"   Available expirations: {len(expirations) if expirations else 0}")
                if expirations:
                    for exp in expirations[:5]:  # Show first 5
                        print(f"     - {exp}")
                else:
                    print("     - No expirations found")
            except Exception as e:
                print(f"   ❌ Error getting expirations: {e}")

            # Try to get full option chain (no specific expiration)
            try:
                options_data = data_manager.get_option_chain_historical(symbol, target_date)
                if options_data:
                    puts = options_data.get('puts', [])
                    calls = options_data.get('calls', [])
                    print(f"   Total options: {len(puts)} puts, {len(calls)} calls")

                    if puts or calls:
                        # Show some examples
                        all_options = puts + calls
                        print("   Sample options:")
                        for opt in all_options[:3]:
                            exp = opt.get('expiration', 'N/A')
                            strike = opt.get('strike', 'N/A')
                            opt_type = opt.get('type', 'N/A')
                            print(f"     - {strike} {opt_type} exp:{exp}")
                else:
                    print("   No options data returned")
            except Exception as e:
                print(f"   ❌ Error getting option chain: {e}")

        except Exception as e:
            print(f"   ❌ Error processing date {date_str}: {e}")

    # Also try getting just recent data for context
    print(f"\n🔄 Testing current/recent options data...")
    try:
        current_date = datetime.now()
        options_data = data_manager.get_option_chain_historical(symbol, current_date)
        if options_data:
            puts = options_data.get('puts', [])
            calls = options_data.get('calls', [])
            print(f"Current options available: {len(puts)} puts, {len(calls)} calls")
        else:
            print("No current options data available")
    except Exception as e:
        print(f"❌ Error getting current options: {e}")


if __name__ == '__main__':
    debug_historical_options()