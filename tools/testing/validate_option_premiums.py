#!/usr/bin/env python3
"""Validate option premium assumptions by comparing current market data with backtesting logic."""

import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import pandas as pd
from dotenv import load_dotenv

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.api.alpaca_client import AlpacaClient
from src.utils.config import Config


class OptionPremiumValidator:
    """Validates option premium assumptions against current market data."""

    def __init__(self, config_path: str = "config/settings.yaml"):
        """Initialize validator.

        Args:
            config_path: Path to configuration file
        """
        load_dotenv()
        self.config = Config(config_path)
        self.client = AlpacaClient(self.config)

    def get_current_stock_price(self, symbol: str) -> float:
        """Get current stock price.

        Args:
            symbol: Stock symbol

        Returns:
            Current stock price
        """
        try:
            quote = self.client.get_stock_quote(symbol)
            # Use midpoint of bid/ask for current price
            return (quote['bid'] + quote['ask']) / 2
        except Exception as e:
            print(f"❌ Failed to get stock price for {symbol}: {e}")
            return 0.0

    def filter_options_by_expiration(self, options: List[Dict], target_date: str) -> List[Dict]:
        """Filter options by expiration date.

        Args:
            options: List of option contracts
            target_date: Target expiration date (YYYY-MM-DD)

        Returns:
            Filtered options list
        """
        filtered = []
        for option in options:
            exp_date = option.get('expiration_date')
            if exp_date:
                # Handle different date formats
                if isinstance(exp_date, str):
                    exp_str = exp_date.split('T')[0]  # Remove time component
                else:
                    exp_str = exp_date.strftime('%Y-%m-%d')

                if exp_str == target_date:
                    filtered.append(option)

        return filtered

    def apply_backtesting_quality_scoring(self, option: Dict) -> Dict:
        """Apply the same quality scoring logic used in backtesting.

        Args:
            option: Option contract data

        Returns:
            Option with quality score added
        """
        # Extract key metrics
        volume = option.get('volume', 0)
        bid = option.get('bid', 0.0)
        ask = option.get('ask', 0.0)
        delta = abs(option.get('delta', 0.0))

        # Calculate spread
        if bid > 0 and ask > 0:
            spread = ask - bid
            spread_pct = spread / bid * 100 if bid > 0 else 100
        else:
            spread = 0
            spread_pct = 100

        # Quality scoring (same as backtesting logic)
        volume_score = min(1.0, volume / 100)  # Normalize to 100 contracts

        max_bid_ask_spread = 15.0  # 15% max spread
        spread_score = max(0, 1 - (spread_pct / max_bid_ask_spread))

        premium_score = min(1.0, bid / 5.0)  # Normalize to $5 premium

        # Delta score - prefer deltas in our target range (0.10-0.20)
        delta_min, delta_max = 0.10, 0.20
        if delta_min <= delta <= delta_max:
            delta_score = 1.0
        elif delta < delta_min:
            delta_score = delta / delta_min
        else:
            delta_score = max(0, 1 - (delta - delta_max) / 0.1)

        # Combined quality score
        quality_score = (
            volume_score * 0.2 +
            spread_score * 0.3 +
            premium_score * 0.3 +
            delta_score * 0.2
        )

        # Add calculated metrics to option
        option_with_score = option.copy()
        option_with_score.update({
            'spread': spread,
            'spread_pct': spread_pct,
            'volume_score': volume_score,
            'spread_score': spread_score,
            'premium_score': premium_score,
            'delta_score': delta_score,
            'quality_score': quality_score
        })

        return option_with_score

    def validate_symbol(self, symbol: str, target_expiration: str) -> Dict[str, Any]:
        """Validate option premiums for a specific symbol and expiration.

        Args:
            symbol: Stock symbol
            target_expiration: Target expiration date (YYYY-MM-DD)

        Returns:
            Validation results
        """
        print(f"\n🔍 Validating {symbol} options for {target_expiration}")
        print("=" * 60)

        # Get current stock price
        current_price = self.get_current_stock_price(symbol)
        if current_price <= 0:
            return {'error': f'Failed to get current price for {symbol}'}

        print(f"Current {symbol} price: ${current_price:.2f}")

        # Get options chain
        try:
            all_options = self.client.get_options_chain(symbol)
            print(f"Total options in chain: {len(all_options)}")
        except Exception as e:
            return {'error': f'Failed to get options chain: {e}'}

        # Filter for target expiration and puts only
        target_options = self.filter_options_by_expiration(all_options, target_expiration)
        put_options = [opt for opt in target_options if opt.get('option_type') == 'put']

        print(f"Put options for {target_expiration}: {len(put_options)}")

        if not put_options:
            return {'error': f'No put options found for {target_expiration}'}

        # Apply backtesting quality scoring
        scored_options = [self.apply_backtesting_quality_scoring(opt) for opt in put_options]

        # Filter by our strategy criteria
        strategy_min_delta = self.config.put_delta_range[0]
        strategy_max_delta = self.config.put_delta_range[1]
        min_premium = self.config.min_put_premium

        suitable_options = []
        for option in scored_options:
            delta = abs(option.get('delta', 0.0))
            bid = option.get('bid', 0.0)

            if (strategy_min_delta <= delta <= strategy_max_delta and
                bid >= min_premium and
                option.get('bid', 0) > 0 and option.get('ask', 0) > 0):
                suitable_options.append(option)

        print(f"Options meeting strategy criteria: {len(suitable_options)}")

        # Sort by quality score (best first)
        suitable_options.sort(key=lambda x: x.get('quality_score', 0), reverse=True)

        # Analysis
        analysis = {
            'symbol': symbol,
            'current_price': current_price,
            'target_expiration': target_expiration,
            'total_puts': len(put_options),
            'suitable_options': len(suitable_options),
            'top_options': suitable_options[:5],  # Top 5 options
            'premium_range': {
                'min': min([opt.get('bid', 0) for opt in suitable_options]) if suitable_options else 0,
                'max': max([opt.get('bid', 0) for opt in suitable_options]) if suitable_options else 0,
                'avg': sum([opt.get('bid', 0) for opt in suitable_options]) / len(suitable_options) if suitable_options else 0
            },
            'delta_range': {
                'min': min([abs(opt.get('delta', 0)) for opt in suitable_options]) if suitable_options else 0,
                'max': max([abs(opt.get('delta', 0)) for opt in suitable_options]) if suitable_options else 0
            }
        }

        return analysis

    def print_detailed_analysis(self, analysis: Dict[str, Any]):
        """Print detailed analysis of option validation.

        Args:
            analysis: Analysis results from validate_symbol
        """
        if 'error' in analysis:
            print(f"❌ {analysis['error']}")
            return

        print(f"\n📊 DETAILED ANALYSIS FOR {analysis['symbol']}")
        print("=" * 60)

        print(f"Current Stock Price: ${analysis['current_price']:.2f}")
        print(f"Target Expiration: {analysis['target_expiration']}")
        print(f"Total Put Options: {analysis['total_puts']}")
        print(f"Strategy-Suitable Options: {analysis['suitable_options']}")

        if analysis['suitable_options'] > 0:
            premium_range = analysis['premium_range']
            delta_range = analysis['delta_range']

            print(f"\n💰 PREMIUM ANALYSIS:")
            print(f"  Range: ${premium_range['min']:.2f} - ${premium_range['max']:.2f}")
            print(f"  Average: ${premium_range['avg']:.2f}")

            print(f"\n📈 DELTA ANALYSIS:")
            print(f"  Range: {delta_range['min']:.3f} - {delta_range['max']:.3f}")

            print(f"\n🏆 TOP 5 OPTIONS BY QUALITY SCORE:")
            print("-" * 100)
            print(f"{'Strike':<8} {'Delta':<8} {'Bid':<8} {'Ask':<8} {'Spread%':<8} {'Volume':<8} {'Score':<8} {'Symbol'}")
            print("-" * 100)

            for i, option in enumerate(analysis['top_options'][:5], 1):
                strike = option.get('strike_price', 0)
                delta = abs(option.get('delta', 0))
                bid = option.get('bid', 0)
                ask = option.get('ask', 0)
                spread_pct = option.get('spread_pct', 0)
                volume = option.get('volume', 0)
                score = option.get('quality_score', 0)
                symbol = option.get('symbol', 'N/A')

                print(f"{strike:<8.0f} {delta:<8.3f} {bid:<8.2f} {ask:<8.2f} {spread_pct:<8.1f} {volume:<8} {score:<8.3f} {symbol}")
        else:
            print("\n❌ No options found meeting strategy criteria")
            print("\nPossible reasons:")
            print("- No options in target delta range (0.10-0.20)")
            print("- Premiums below minimum threshold")
            print("- No bid/ask data available")


def main():
    """Main validation function."""
    print("🔍 OPTION PREMIUM VALIDATION TOOL")
    print("=" * 50)
    print("Comparing current market data with backtesting assumptions\n")

    # Initialize validator
    try:
        validator = OptionPremiumValidator()
    except Exception as e:
        print(f"❌ Failed to initialize validator: {e}")
        return

    # Target parameters
    symbol = "UNH"
    target_date = "2025-10-03"  # October 3rd, 2025

    print(f"Target Symbol: {symbol}")
    print(f"Target Expiration: {target_date}")
    print(f"Current Date: {datetime.now().strftime('%Y-%m-%d')}")

    # Calculate days to expiration
    current_date = datetime.now().date()
    exp_date = datetime.strptime(target_date, '%Y-%m-%d').date()
    days_to_exp = (exp_date - current_date).days
    print(f"Days to Expiration: {days_to_exp}")

    # Validate options
    analysis = validator.validate_symbol(symbol, target_date)

    # Print results
    validator.print_detailed_analysis(analysis)

    # Interpretation and recommendations
    if 'error' not in analysis and analysis['suitable_options'] > 0:
        avg_premium = analysis['premium_range']['avg']
        print(f"\n🎯 BACKTESTING VALIDATION:")
        print("-" * 40)

        if avg_premium > 3.0:
            print(f"⚠️  Average premium ${avg_premium:.2f} seems HIGH for {days_to_exp}-day options")
            print("   This might explain the backtesting concern about high premiums")
        elif avg_premium < 0.5:
            print(f"⚠️  Average premium ${avg_premium:.2f} seems LOW for wheel strategy")
            print("   May not meet minimum premium requirements")
        else:
            print(f"✅ Average premium ${avg_premium:.2f} appears reasonable for {days_to_exp}-day options")

        print(f"\n📋 RECOMMENDATIONS:")
        print("- Compare these current premiums with recent backtesting results")
        print("- Check if backtesting IV assumptions match current market IV")
        print("- Verify backtesting option pricing model accuracy")
        print("- Consider adjusting backtesting parameters if significant discrepancies exist")

    print(f"\n✅ Validation complete!")


if __name__ == '__main__':
    main()