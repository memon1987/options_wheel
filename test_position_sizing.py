#!/usr/bin/env python3
"""Test position sizing calculation locally."""

import json
from src.utils.config import Config
from src.api.alpaca_client import AlpacaClient
from src.api.market_data import MarketDataManager
from src.strategy.put_seller import PutSeller

def main():
    print("=== Local Position Sizing Test ===\n")

    # Initialize
    config = Config()
    alpaca_client = AlpacaClient(config)
    market_data = MarketDataManager(alpaca_client, config)
    put_seller = PutSeller(alpaca_client, market_data, config)

    # Sample opportunity from the scan (without contracts field)
    opportunity = {
        "type": "put",
        "symbol": "AMD",
        "option_symbol": "AMD251010P00155000",
        "current_stock_price": 164.36,
        "strike_price": 155.0,
        "premium": 1.17,
        "dte": 6,
        "delta": 0.1841,
        "annual_return_percent": 46.11,
        "otm_percentage": 5.69,
        "expiration_date": "2025-10-10",
        "bid": 1.14,
        "ask": 1.21
    }

    print("Original opportunity (from scan):")
    print(json.dumps(opportunity, indent=2))
    print("\n" + "="*60 + "\n")

    # Check if contracts field exists
    print(f"Has 'contracts' field: {'contracts' in opportunity}")
    print(f"Has 'premium' field: {'premium' in opportunity}")
    print(f"Has 'strike_price' field: {'strike_price' in opportunity}")
    print(f"Has 'option_symbol' field: {'option_symbol' in opportunity}")
    print("\n" + "="*60 + "\n")

    # Calculate position size
    print("Calculating position size...")

    # Transform scanner format to position sizing format
    if 'premium' in opportunity and 'mid_price' not in opportunity:
        opportunity['mid_price'] = opportunity['premium']

    position_size = put_seller._calculate_position_size(opportunity)

    if position_size:
        print("✓ Position sizing SUCCESS\n")
        print("Position size result:")
        print(json.dumps(position_size, indent=2))

        # Add contracts to opportunity
        opportunity['contracts'] = position_size['contracts']

        print("\n" + "="*60 + "\n")
        print("Updated opportunity (with contracts):")
        print(json.dumps({
            'symbol': opportunity['symbol'],
            'option_symbol': opportunity['option_symbol'],
            'strike_price': opportunity['strike_price'],
            'premium': opportunity['premium'],
            'contracts': opportunity['contracts']  # Added!
        }, indent=2))

        print("\n" + "="*60 + "\n")
        print("✓ Ready for execution!")
        print(f"  Would execute: SELL {opportunity['contracts']} {opportunity['option_symbol']}")
        print(f"  Premium collected: ${opportunity['contracts'] * opportunity['premium'] * 100:.2f}")
        print(f"  Capital required: ${opportunity['contracts'] * opportunity['strike_price'] * 100:,.2f}")

    else:
        print("✗ Position sizing FAILED")
        print("  Opportunity would be skipped")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
