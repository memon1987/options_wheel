#!/usr/bin/env python3
"""Test complete execution flow locally - simulates /run endpoint."""

import json
from src.utils.config import Config
from src.api.alpaca_client import AlpacaClient
from src.api.market_data import MarketDataManager
from src.strategy.put_seller import PutSeller

def main():
    print("="*70)
    print("  LOCAL EXECUTION FLOW TEST - Simulating /run endpoint")
    print("="*70)
    print()

    # Initialize (same as /run endpoint)
    config = Config()
    alpaca_client = AlpacaClient(config)
    market_data = MarketDataManager(alpaca_client, config)
    put_seller = PutSeller(alpaca_client, market_data, config)

    # Sample opportunities (as they come from Cloud Storage scan)
    opportunities = [
        {
            "type": "put",
            "symbol": "AMD",
            "option_symbol": "AMD251010P00155000",
            "current_stock_price": 164.36,
            "strike_price": 155.0,
            "premium": 1.17,
            "dte": 6,
            "delta": 0.1841,
            "expiration_date": "2025-10-10",
            "bid": 1.14,
            "ask": 1.21
        },
        {
            "type": "put",
            "symbol": "NVDA",
            "option_symbol": "NVDA251010P00177500",
            "current_stock_price": 187.175,
            "strike_price": 177.5,
            "premium": 0.935,
            "dte": 6,
            "delta": 0.1619,
            "expiration_date": "2025-10-10",
            "bid": 0.91,
            "ask": 0.96
        }
    ]

    print(f"Retrieved {len(opportunities)} opportunities from scan\n")

    # Execute each opportunity (same logic as /run endpoint)
    execution_results = []
    trades_executed = 0

    for idx, opp in enumerate(opportunities):
        print(f"\n{'='*70}")
        print(f"  Opportunity {idx+1}/{len(opportunities)}: {opp['symbol']}")
        print(f"{'='*70}")

        print(f"  Symbol: {opp['symbol']}")
        print(f"  Option: {opp['option_symbol']}")
        print(f"  Strike: ${opp['strike_price']:.2f}")
        print(f"  Premium: ${opp['premium']:.2f}")
        print()

        # Calculate position size if not already present
        if 'contracts' not in opp:
            print("  ⚙️  Calculating position size...")

            # Transform scanner format to position sizing format
            if 'premium' in opp and 'mid_price' not in opp:
                opp['mid_price'] = opp['premium']

            position_size = put_seller._calculate_position_size(opp)

            if position_size:
                opp['contracts'] = position_size['contracts']
                print(f"  ✓ Position sizing: {position_size['contracts']} contract(s)")
                print(f"    Capital required: ${position_size['capital_required']:,.2f}")
                print(f"    Max profit: ${position_size['max_profit']:.2f}")
                print(f"    Portfolio allocation: {position_size['portfolio_allocation']*100:.1f}%")
            else:
                print(f"  ✗ Position sizing failed - skipping")
                execution_results.append(None)
                continue

        print()
        print(f"  📋 Ready to execute:")
        print(f"    SELL {opp['contracts']} {opp['option_symbol']}")
        print(f"    Premium: ${opp['contracts'] * opp['premium'] * 100:.2f}")
        print(f"    Collateral: ${opp['contracts'] * opp['strike_price'] * 100:,.2f}")
        print()

        # Execute the trade (auto-execute in test mode)
        print(f"  🚀 Executing trade on Alpaca PAPER account...")
        result = put_seller.execute_put_sale(opp)
        execution_results.append(result)

        if result and result.get('success'):
            trades_executed += 1
            print(f"  ✅ Trade EXECUTED successfully!")
            print(f"    Order ID: {result.get('order_id')}")
            print(f"    Status: {result.get('status')}")
        else:
            error_msg = result.get('message', 'Unknown error') if result else 'No result returned'
            print(f"  ❌ Trade FAILED: {error_msg}")

    # Summary
    print()
    print("="*70)
    print("  EXECUTION SUMMARY")
    print("="*70)
    print(f"  Opportunities evaluated: {len(opportunities)}")
    print(f"  Trades executed: {trades_executed}")
    print(f"  Trades failed/skipped: {len(opportunities) - trades_executed}")
    print("="*70)
    print()

    if trades_executed > 0:
        print("✅ Test complete! Check Alpaca paper account for executed trades.")
    else:
        print("ℹ️  No trades executed. Run again with 'yes' to test real execution.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Test cancelled by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
