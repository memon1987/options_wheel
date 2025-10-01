#!/usr/bin/env python3
"""Examine the timing data returned by OptionBarsRequest."""

import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.utils.config import Config
from alpaca.data import OptionHistoricalDataClient
from alpaca.data.requests import OptionBarsRequest
from alpaca.data.timeframe import TimeFrame


def examine_options_timing():
    """Examine what timing information is returned in options data."""
    print("🔍 EXAMINING OPTIONS TIMING DATA")
    print("=" * 60)

    load_dotenv()
    config = Config("config/settings.yaml")

    option_client = OptionHistoricalDataClient(
        api_key=config.alpaca_api_key,
        secret_key=config.alpaca_secret_key
    )

    # Test with a known option from our previous analysis
    test_symbol = "UNH250926P00340000"  # 340 Put that had good volume
    test_date = datetime.strptime("2025-09-23", '%Y-%m-%d')

    print(f"Testing symbol: {test_symbol}")
    print(f"Date: {test_date}")

    try:
        # Test 1: Basic request (what we've been doing)
        print(f"\n📅 TEST 1: Basic OptionBarsRequest")
        print("-" * 40)

        bars_request = OptionBarsRequest(
            symbol_or_symbols=[test_symbol],
            timeframe=TimeFrame.Day,
            start=test_date,
            end=test_date + timedelta(days=1)
        )

        print(f"Request parameters:")
        print(f"  Start: {bars_request.start}")
        print(f"  End: {bars_request.end}")
        print(f"  Timeframe: {bars_request.timeframe}")

        bars_response = option_client.get_option_bars(bars_request)

        if hasattr(bars_response, 'df') and not bars_response.df.empty:
            df = bars_response.df
            print(f"\nResponse data:")
            print(f"  Records: {len(df)}")

            # Examine the index and timestamp information
            print(f"\nDataFrame structure:")
            print(f"  Index: {df.index}")
            print(f"  Columns: {list(df.columns)}")

            # Get the first row to examine timing details
            if hasattr(df.index, 'get_level_values'):
                timestamps = df.index.get_level_values('timestamp')
                print(f"\nTimestamp details:")
                for i, ts in enumerate(timestamps):
                    print(f"  Record {i+1}: {ts} (type: {type(ts)})")
                    if hasattr(ts, 'strftime'):
                        print(f"    Formatted: {ts.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                        print(f"    Hour: {ts.hour}")
                        print(f"    Timezone: {ts.tzinfo}")
            else:
                print(f"  Index type: {type(df.index)}")

            # Show the actual data
            print(f"\nSample data:")
            print(df.head())

            # Examine specific values
            if not df.empty:
                sample_row = df.iloc[0]
                print(f"\nDetailed sample row:")
                for col in df.columns:
                    value = sample_row[col]
                    print(f"  {col}: {value}")

        else:
            print("❌ No data returned")

        # Test 2: Check if we can specify different times within the day
        print(f"\n📅 TEST 2: Different time ranges within same day")
        print("-" * 50)

        # Try morning hours
        morning_start = test_date.replace(hour=9, minute=30)  # Market open
        morning_end = test_date.replace(hour=12, minute=0)   # Noon

        print(f"Morning request: {morning_start} to {morning_end}")

        try:
            morning_request = OptionBarsRequest(
                symbol_or_symbols=[test_symbol],
                timeframe=TimeFrame.Hour,  # Try hourly data
                start=morning_start,
                end=morning_end
            )

            morning_response = option_client.get_option_bars(morning_request)

            if hasattr(morning_response, 'df') and not morning_response.df.empty:
                print(f"✅ Morning data available: {len(morning_response.df)} records")

                if hasattr(morning_response.df.index, 'get_level_values'):
                    morning_timestamps = morning_response.df.index.get_level_values('timestamp')
                    print(f"Morning timestamps:")
                    for ts in morning_timestamps:
                        print(f"  {ts}")
            else:
                print("❌ No morning data")

        except Exception as e:
            print(f"❌ Morning request error: {e}")

        # Try afternoon hours
        afternoon_start = test_date.replace(hour=12, minute=0)  # Noon
        afternoon_end = test_date.replace(hour=16, minute=0)   # Market close

        print(f"\nAfternoon request: {afternoon_start} to {afternoon_end}")

        try:
            afternoon_request = OptionBarsRequest(
                symbol_or_symbols=[test_symbol],
                timeframe=TimeFrame.Hour,
                start=afternoon_start,
                end=afternoon_end
            )

            afternoon_response = option_client.get_option_bars(afternoon_request)

            if hasattr(afternoon_response, 'df') and not afternoon_response.df.empty:
                print(f"✅ Afternoon data available: {len(afternoon_response.df)} records")

                if hasattr(afternoon_response.df.index, 'get_level_values'):
                    afternoon_timestamps = afternoon_response.df.index.get_level_values('timestamp')
                    print(f"Afternoon timestamps:")
                    for ts in afternoon_timestamps:
                        print(f"  {ts}")
            else:
                print("❌ No afternoon data")

        except Exception as e:
            print(f"❌ Afternoon request error: {e}")

        # Test 3: Compare with market close data specifically
        print(f"\n📅 TEST 3: Market close timing")
        print("-" * 40)

        # Request just around market close
        close_start = test_date.replace(hour=15, minute=30)  # 30 min before close
        close_end = test_date.replace(hour=16, minute=30)   # 30 min after close

        print(f"Market close window: {close_start} to {close_end}")

        try:
            close_request = OptionBarsRequest(
                symbol_or_symbols=[test_symbol],
                timeframe=TimeFrame.Minute,  # Try minute data
                start=close_start,
                end=close_end
            )

            close_response = option_client.get_option_bars(close_request)

            if hasattr(close_response, 'df') and not close_response.df.empty:
                print(f"✅ Market close data available: {len(close_response.df)} records")

                close_df = close_response.df
                if hasattr(close_df.index, 'get_level_values'):
                    close_timestamps = close_df.index.get_level_values('timestamp')
                    print(f"Close period timestamps (first 5):")
                    for i, ts in enumerate(close_timestamps[:5]):
                        print(f"  {i+1}: {ts}")

                    print(f"Close period timestamps (last 5):")
                    for i, ts in enumerate(close_timestamps[-5:]):
                        print(f"  {i+1}: {ts}")

                    # Find the 4:00 PM close specifically
                    market_close_time = test_date.replace(hour=16, minute=0)
                    print(f"\nLooking for market close time: {market_close_time}")

                    close_matches = [ts for ts in close_timestamps if ts.hour == 16 and ts.minute == 0]
                    if close_matches:
                        print(f"✅ Found market close data: {close_matches}")

                        # Get the closing values
                        for close_ts in close_matches:
                            if hasattr(close_df.index, 'get_level_values'):
                                close_row = close_df.loc[(test_symbol, close_ts)]
                                print(f"Market close values:")
                                print(f"  Close: ${close_row['close']:.2f}")
                                print(f"  Volume: {close_row['volume']}")
                    else:
                        print("❌ No exact 4:00 PM data found")
            else:
                print("❌ No market close data")

        except Exception as e:
            print(f"❌ Market close request error: {e}")

    except Exception as e:
        print(f"❌ Main request error: {e}")
        import traceback
        traceback.print_exc()

    # Summary
    print(f"\n📋 SUMMARY: Options Timing Behavior")
    print("=" * 50)
    print("Based on the tests above:")
    print("1. Daily bars (TimeFrame.Day) - What 'as of' time?")
    print("2. Hourly/Minute bars - Available for intraday analysis?")
    print("3. Default behavior - Market close assumption?")
    print("4. Timezone handling - How are times interpreted?")


if __name__ == '__main__':
    examine_options_timing()