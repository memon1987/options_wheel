#!/usr/bin/env python3
"""Test if OptionBarsRequest can retrieve data for expired options (9/26 expiration)."""

import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any
from dotenv import load_dotenv

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.utils.config import Config
from alpaca.data import OptionHistoricalDataClient
from alpaca.data.requests import OptionBarsRequest
from alpaca.data.timeframe import TimeFrame


class ExpiredOptionsBarsTester:
    """Test OptionBarsRequest endpoint for expired options data."""

    def __init__(self, config_path: str = "config/settings.yaml"):
        """Initialize tester.

        Args:
            config_path: Path to configuration file
        """
        load_dotenv()
        self.config = Config(config_path)
        self.option_client = OptionHistoricalDataClient(
            api_key=self.config.alpaca_api_key,
            secret_key=self.config.alpaca_secret_key
        )

    def generate_expired_option_symbols(self, underlying: str, expiration: str, strikes: List[float]) -> List[str]:
        """Generate option symbols for expired contracts.

        Args:
            underlying: Underlying stock symbol (e.g., "UNH")
            expiration: Expiration date in YYYY-MM-DD format (e.g., "2025-09-26")
            strikes: List of strike prices to test

        Returns:
            List of option symbols
        """
        # Parse expiration date
        exp_date = datetime.strptime(expiration, '%Y-%m-%d')

        # Format: YYMMDD
        exp_str = exp_date.strftime('%y%m%d')

        symbols = []
        for strike in strikes:
            # Format strike as 8 digits (multiply by 1000)
            strike_str = f"{int(strike * 1000):08d}"

            # Generate put and call symbols
            put_symbol = f"{underlying}{exp_str}P{strike_str}"
            call_symbol = f"{underlying}{exp_str}C{strike_str}"

            symbols.extend([put_symbol, call_symbol])

        return symbols

    def test_expired_options_bars(self, underlying: str, expiration: str, test_dates: List[str]) -> Dict[str, Any]:
        """Test OptionBarsRequest for expired options on various dates.

        Args:
            underlying: Stock symbol
            expiration: Expired expiration date (YYYY-MM-DD)
            test_dates: List of historical dates to test (YYYY-MM-DD)

        Returns:
            Test results
        """
        print(f"🔍 TESTING EXPIRED OPTIONS BARS")
        print("=" * 60)
        print(f"Underlying: {underlying}")
        print(f"Expired Expiration: {expiration}")
        print(f"Test Dates: {test_dates}")

        # Generate realistic strike prices around UNH's typical range
        strikes = [320, 325, 330, 335, 340, 345, 350, 355, 360]
        option_symbols = self.generate_expired_option_symbols(underlying, expiration, strikes)

        print(f"Generated {len(option_symbols)} option symbols to test")
        print("Sample symbols:")
        for symbol in option_symbols[:5]:
            print(f"  - {symbol}")

        results = {}

        for date_str in test_dates:
            print(f"\n📅 Testing date: {date_str}")

            try:
                test_date = datetime.strptime(date_str, '%Y-%m-%d')

                # Test with a small batch first
                test_symbols = option_symbols[:10]  # Test first 10 symbols

                print(f"   Testing {len(test_symbols)} symbols...")

                # Create OptionBarsRequest
                bars_request = OptionBarsRequest(
                    symbol_or_symbols=test_symbols,
                    timeframe=TimeFrame.Day,
                    start=test_date,
                    end=test_date + timedelta(days=1)
                )

                # Execute the request
                bars_response = self.option_client.get_option_bars(bars_request)

                # Analyze results
                if hasattr(bars_response, 'df'):
                    df = bars_response.df
                    if not df.empty:
                        unique_symbols = df.index.get_level_values('symbol').unique()
                        print(f"   ✅ SUCCESS: Found data for {len(unique_symbols)} symbols")

                        # Show sample data
                        print("   Sample data:")
                        for symbol in unique_symbols[:3]:
                            symbol_data = df.loc[symbol]
                            if not symbol_data.empty:
                                close_price = symbol_data['close'].iloc[0] if 'close' in symbol_data else 'N/A'
                                volume = symbol_data['volume'].iloc[0] if 'volume' in symbol_data else 'N/A'
                                print(f"     {symbol}: close={close_price}, volume={volume}")

                        results[date_str] = {
                            'success': True,
                            'symbols_found': len(unique_symbols),
                            'total_bars': len(df),
                            'sample_data': df.head().to_dict() if len(df) < 100 else 'Large dataset'
                        }
                    else:
                        print(f"   ❌ No data: DataFrame is empty")
                        results[date_str] = {'success': False, 'reason': 'Empty DataFrame'}
                else:
                    print(f"   ❌ No data: No DataFrame in response")
                    results[date_str] = {'success': False, 'reason': 'No DataFrame in response'}

            except Exception as e:
                print(f"   ❌ ERROR: {e}")
                results[date_str] = {'success': False, 'reason': str(e)}

        return results

    def test_different_symbol_formats(self, underlying: str, expiration: str, test_date: str):
        """Test different option symbol formats to see which work.

        Args:
            underlying: Stock symbol
            expiration: Expiration date
            test_date: Date to test
        """
        print(f"\n🔧 TESTING DIFFERENT SYMBOL FORMATS")
        print("=" * 50)

        exp_date = datetime.strptime(expiration, '%Y-%m-%d')
        date_obj = datetime.strptime(test_date, '%Y-%m-%d')

        # Try different symbol formats
        formats_to_test = [
            # Standard format: UNH250926P00340000
            f"{underlying}{exp_date.strftime('%y%m%d')}P00340000",

            # Alternative format: UNH250926P340000
            f"{underlying}{exp_date.strftime('%y%m%d')}P340000",

            # With year: UNH20250926P00340000
            f"{underlying}{exp_date.strftime('%Y%m%d')}P00340000",

            # Different strike format: UNH250926P003400
            f"{underlying}{exp_date.strftime('%y%m%d')}P003400",
        ]

        for i, symbol in enumerate(formats_to_test, 1):
            print(f"\n   Format {i}: {symbol}")

            try:
                bars_request = OptionBarsRequest(
                    symbol_or_symbols=[symbol],
                    timeframe=TimeFrame.Day,
                    start=date_obj,
                    end=date_obj + timedelta(days=1)
                )

                bars_response = self.option_client.get_option_bars(bars_request)

                if hasattr(bars_response, 'df') and not bars_response.df.empty:
                    print(f"      ✅ SUCCESS: Found data")
                    print(f"      Bars: {len(bars_response.df)}")
                else:
                    print(f"      ❌ No data found")

            except Exception as e:
                print(f"      ❌ ERROR: {e}")


def main():
    """Main test function."""
    print("🔍 EXPIRED OPTIONS BARS ENDPOINT TEST")
    print("=" * 60)
    print("Testing if OptionBarsRequest can retrieve expired options data")

    # Initialize tester
    try:
        tester = ExpiredOptionsBarsTester()
    except Exception as e:
        print(f"❌ Failed to initialize tester: {e}")
        return

    # Test parameters
    underlying = "UNH"
    expired_expiration = "2025-09-26"  # This has already expired

    # Test multiple dates around the expiration
    test_dates = [
        "2025-09-26",  # Expiration day
        "2025-09-25",  # Day before expiration
        "2025-09-24",  # Two days before
        "2025-09-23",  # Three days before
        "2025-09-20",  # Week before (Friday)
    ]

    print(f"\n🎯 PRIMARY TEST: OptionBarsRequest for Expired Contracts")
    results = tester.test_expired_options_bars(underlying, expired_expiration, test_dates)

    # Test different symbol formats
    tester.test_different_symbol_formats(underlying, expired_expiration, "2025-09-25")

    # Summary
    print(f"\n📊 SUMMARY OF RESULTS")
    print("=" * 40)

    successful_dates = [date for date, result in results.items() if result.get('success', False)]

    if successful_dates:
        print(f"✅ SUCCESS: Found expired options data for {len(successful_dates)} dates:")
        for date in successful_dates:
            result = results[date]
            print(f"   {date}: {result['symbols_found']} symbols, {result['total_bars']} bars")

        print(f"\n🎉 CONCLUSION: OptionBarsRequest CAN retrieve expired options data!")
        print(f"   This means we can access historical premiums for past expirations")
        print(f"   Unlike OptionChainRequest, OptionBarsRequest maintains expired data")

    else:
        print(f"❌ FAILED: No expired options data found for any test date")
        print(f"   OptionBarsRequest has same limitations as OptionChainRequest")
        print(f"   Expired options data is not available through Alpaca API")

    print(f"\n✅ Test complete!")


if __name__ == '__main__':
    main()