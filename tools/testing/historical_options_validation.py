#!/usr/bin/env python3
"""Pull historical options data to validate premium assumptions."""

import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import pandas as pd
from dotenv import load_dotenv

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.backtesting.historical_data import HistoricalDataManager
from src.utils.config import Config


class HistoricalOptionsValidator:
    """Validates historical options data."""

    def __init__(self, config_path: str = "config/settings.yaml"):
        """Initialize validator.

        Args:
            config_path: Path to configuration file
        """
        load_dotenv()
        self.config = Config(config_path)
        self.data_manager = HistoricalDataManager(self.config)

    def get_historical_options_data(self, symbol: str, date: str, expiration: str) -> List[Dict[str, Any]]:
        """Get historical options chain data for a specific date and expiration.

        Args:
            symbol: Stock symbol
            date: Historical date (YYYY-MM-DD)
            expiration: Expiration date (YYYY-MM-DD)

        Returns:
            List of option contracts
        """
        try:
            target_date = datetime.strptime(date, '%Y-%m-%d')
            exp_date = datetime.strptime(expiration, '%Y-%m-%d')

            print(f"🔍 Fetching historical options data for {symbol}")
            print(f"   Date: {date}")
            print(f"   Expiration: {expiration}")
            print(f"   Days to expiration: {(exp_date - target_date).days}")

            # Use our historical data manager to get options chain
            options_data = self.data_manager.get_option_chain_historical(symbol, target_date, exp_date)

            if not options_data:
                print("❌ No options data found")
                return []

            # Extract puts and calls
            puts = options_data.get('puts', [])
            calls = options_data.get('calls', [])
            all_options = puts + calls

            print(f"✅ Found {len(puts)} puts and {len(calls)} calls")
            print(f"📅 Total options for {expiration} expiration: {len(all_options)}")

            return all_options

        except Exception as e:
            print(f"❌ Error fetching historical options data: {e}")
            import traceback
            traceback.print_exc()
            return []

    def analyze_historical_puts(self, options: List[Dict[str, Any]], current_price: float) -> Dict[str, Any]:
        """Analyze historical put options data.

        Args:
            options: List of option contracts
            current_price: Stock price on the historical date

        Returns:
            Analysis results
        """
        # Filter for puts only
        put_options = [opt for opt in options if opt.get('option_type', '').lower() == 'put']

        if not put_options:
            print("❌ No put options found")
            return {'error': 'No put options found'}

        # Apply strategy criteria
        strategy_min_delta = self.config.put_delta_range[0]
        strategy_max_delta = self.config.put_delta_range[1]
        min_premium = self.config.min_put_premium

        suitable_options = []
        for option in put_options:
            delta = abs(option.get('delta', 0.0))
            bid = option.get('bid', 0.0)
            ask = option.get('ask', 0.0)

            if (strategy_min_delta <= delta <= strategy_max_delta and
                bid >= min_premium and bid > 0 and ask > 0):

                # Calculate quality metrics
                spread = ask - bid
                spread_pct = (spread / bid * 100) if bid > 0 else 100
                volume = option.get('volume', 0)

                # Add calculated fields
                option_with_metrics = option.copy()
                option_with_metrics.update({
                    'spread': spread,
                    'spread_pct': spread_pct,
                    'mid_price': (bid + ask) / 2
                })

                suitable_options.append(option_with_metrics)

        if not suitable_options:
            return {'error': 'No suitable options found'}

        # Sort by delta for consistent comparison
        suitable_options.sort(key=lambda x: abs(x.get('delta', 0)))

        # Calculate statistics
        bids = [opt.get('bid', 0) for opt in suitable_options]
        deltas = [abs(opt.get('delta', 0)) for opt in suitable_options]

        analysis = {
            'total_puts': len(put_options),
            'suitable_options': len(suitable_options),
            'current_price': current_price,
            'premium_stats': {
                'min': min(bids),
                'max': max(bids),
                'avg': sum(bids) / len(bids),
                'median': sorted(bids)[len(bids)//2]
            },
            'delta_stats': {
                'min': min(deltas),
                'max': max(deltas),
                'avg': sum(deltas) / len(deltas)
            },
            'top_options': suitable_options[:5]
        }

        return analysis

    def print_analysis(self, analysis: Dict[str, Any], date: str, expiration: str):
        """Print detailed analysis of historical options.

        Args:
            analysis: Analysis results
            date: Historical date
            expiration: Expiration date
        """
        if 'error' in analysis:
            print(f"❌ {analysis['error']}")
            return

        print(f"\n📊 HISTORICAL OPTIONS ANALYSIS")
        print("=" * 60)
        print(f"Date: {date}")
        print(f"Expiration: {expiration}")
        print(f"Stock Price: ${analysis['current_price']:.2f}")
        print(f"Total Put Options: {analysis['total_puts']}")
        print(f"Strategy-Suitable Options: {analysis['suitable_options']}")

        if analysis['suitable_options'] > 0:
            premium_stats = analysis['premium_stats']
            delta_stats = analysis['delta_stats']

            print(f"\n💰 PREMIUM ANALYSIS:")
            print(f"  Range: ${premium_stats['min']:.2f} - ${premium_stats['max']:.2f}")
            print(f"  Average: ${premium_stats['avg']:.2f}")
            print(f"  Median: ${premium_stats['median']:.2f}")

            print(f"\n📈 DELTA ANALYSIS:")
            print(f"  Range: {delta_stats['min']:.3f} - {delta_stats['max']:.3f}")
            print(f"  Average: {delta_stats['avg']:.3f}")

            print(f"\n🏆 TOP 5 OPTIONS:")
            print("-" * 100)
            print(f"{'Strike':<8} {'Delta':<8} {'Bid':<8} {'Ask':<8} {'Mid':<8} {'Spread%':<8} {'Volume':<8} {'Symbol'}")
            print("-" * 100)

            for option in analysis['top_options'][:5]:
                strike = option.get('strike_price', 0)
                delta = abs(option.get('delta', 0))
                bid = option.get('bid', 0)
                ask = option.get('ask', 0)
                mid = option.get('mid_price', 0)
                spread_pct = option.get('spread_pct', 0)
                volume = option.get('volume', 0)
                symbol = option.get('symbol', 'N/A')

                print(f"{strike:<8.0f} {delta:<8.3f} {bid:<8.2f} {ask:<8.2f} {mid:<8.2f} {spread_pct:<8.1f} {volume:<8} {symbol}")


def main():
    """Main function to validate historical options data."""
    print("🔍 HISTORICAL OPTIONS VALIDATION")
    print("=" * 50)

    # Initialize validator
    try:
        validator = HistoricalOptionsValidator()
    except Exception as e:
        print(f"❌ Failed to initialize validator: {e}")
        return

    # Target parameters - using 10/3 expiration since 9/26 has expired
    symbol = "UNH"
    historical_date = "2025-09-25"  # September 25th (4 days before 9/29)
    expiration_date = "2025-10-03"  # October 3rd (same expiration as current data)

    print(f"Symbol: {symbol}")
    print(f"Historical Date: {historical_date}")
    print(f"Expiration Date: {expiration_date}")

    # Get historical stock price first
    try:
        target_datetime = datetime.strptime(historical_date, '%Y-%m-%d')
        stock_data = validator.data_manager.get_stock_data(symbol, target_datetime, target_datetime + timedelta(days=1))

        if not stock_data.empty:
            historical_price = stock_data['close'].iloc[0]
            print(f"Historical Stock Price: ${historical_price:.2f}")
        else:
            print("❌ Could not get historical stock price")
            historical_price = 0.0
    except Exception as e:
        print(f"❌ Error getting historical stock price: {e}")
        historical_price = 0.0

    # Get historical options data
    options_data = validator.get_historical_options_data(symbol, historical_date, expiration_date)

    if options_data:
        # Analyze the data
        analysis = validator.analyze_historical_puts(options_data, historical_price)

        # Print results
        validator.print_analysis(analysis, historical_date, expiration_date)

        # Compare with current validation if we have it
        print(f"\n🔄 COMPARISON WITH CURRENT DATA:")
        print("-" * 40)
        print("Historical (9/25 → 10/3): 8-day options")
        if 'premium_stats' in analysis:
            print(f"  Average Premium: ${analysis['premium_stats']['avg']:.2f}")
        print("Current (9/29 → 10/3): 4-day options")
        print("  Average Premium: $0.93 (from earlier validation)")

        if 'premium_stats' in analysis:
            hist_avg = analysis['premium_stats']['avg']
            current_avg = 0.93
            diff_pct = ((current_avg - hist_avg) / hist_avg * 100) if hist_avg > 0 else 0
            print(f"  Raw Difference: {diff_pct:+.1f}%")

            # Adjust for time decay (8-day vs 4-day options)
            # Expect ~30-50% premium decay over 4 days for short-term options
            expected_decay = 0.40  # 40% expected decay
            adjusted_hist = hist_avg * (1 - expected_decay)
            adjusted_diff_pct = ((current_avg - adjusted_hist) / adjusted_hist * 100) if adjusted_hist > 0 else 0

            print(f"  Time-Adjusted Difference: {adjusted_diff_pct:+.1f}% (accounting for 4-day time decay)")

            if abs(adjusted_diff_pct) < 25:
                print("✅ Premiums are consistent after accounting for time decay")
            else:
                print("⚠️  Significant difference detected even after time decay adjustment")
    else:
        print("❌ No historical options data available")

    print(f"\n✅ Historical validation complete!")


if __name__ == '__main__':
    main()