#!/usr/bin/env python3
"""
Test the complete trading workflow locally.
This simulates what the Cloud Run server does.
"""

import sys
import os
from datetime import datetime

# Set API credentials
os.environ['ALPACA_API_KEY'] = 'PKXGSCWDVM56LO4S08QN'
os.environ['ALPACA_SECRET_KEY'] = 'COef1N9zNDJECF0G04rWmwM3C8FzZzJaLtIYzoIz'

# Add src to path
sys.path.insert(0, '/Users/zmemon/options_wheel-1')

from src.utils.config import Config
from src.api.alpaca_client import AlpacaClient
from src.api.market_data import MarketDataManager
from src.data.options_scanner import OptionsScanner

def main():
    print("=" * 80)
    print("TRADING WORKFLOW TEST")
    print("=" * 80)

    # Initialize components
    print("\n1. INITIALIZING COMPONENTS...")
    print("-" * 80)
    config = Config()
    print(f"✓ Config loaded")
    print(f"  - Paper trading: {config.paper_trading}")
    print(f"  - Stock symbols: {config.stock_symbols}")

    alpaca_client = AlpacaClient(config)
    print(f"✓ Alpaca client initialized")

    market_data = MarketDataManager(alpaca_client, config)
    print(f"✓ Market data manager initialized")

    scanner = OptionsScanner(alpaca_client, market_data, config)
    print(f"✓ Options scanner initialized")

    # Check account
    print("\n2. CHECKING ACCOUNT...")
    print("-" * 80)
    try:
        account = alpaca_client.get_account()
        print(f"✓ Account retrieved")
        print(f"  - Portfolio value: ${account['portfolio_value']:,.2f}")
        print(f"  - Cash: ${account['cash']:,.2f}")
        print(f"  - Buying power: ${account['buying_power']:,.2f}")
    except Exception as e:
        print(f"✗ Error: {e}")
        return

    # Check market status
    print("\n3. CHECKING MARKET STATUS...")
    print("-" * 80)
    try:
        clock = alpaca_client.trading_client.get_clock()
        print(f"✓ Market status retrieved")
        print(f"  - Market open: {clock.is_open}")
        print(f"  - Current time: {clock.timestamp}")
        if not clock.is_open:
            print(f"  - Next open: {clock.next_open}")
            print(f"\n  ⚠️  Market is closed. Scan will likely find no opportunities.")
    except Exception as e:
        print(f"✗ Error: {e}")

    # Run market scan
    print("\n4. RUNNING MARKET SCAN...")
    print("-" * 80)
    try:
        print("  Scanning for put opportunities...")
        put_opportunities = scanner.scan_for_put_opportunities()
        print(f"  ✓ Put opportunities found: {len(put_opportunities)}")

        if put_opportunities:
            print(f"\n  Sample put opportunity:")
            opp = put_opportunities[0]
            print(f"    Symbol: {opp.get('symbol', 'N/A')}")
            print(f"    Strike: ${opp.get('strike', 0):.2f}")
            print(f"    Premium: ${opp.get('premium', 0):.2f}")
            print(f"    DTE: {opp.get('dte', 0)} days")

        print("\n  Scanning for call opportunities...")
        call_opportunities = scanner.scan_for_call_opportunities()
        print(f"  ✓ Call opportunities found: {len(call_opportunities)}")

        if call_opportunities:
            print(f"\n  Sample call opportunity:")
            opp = call_opportunities[0]
            print(f"    Symbol: {opp.get('symbol', 'N/A')}")
            print(f"    Strike: ${opp.get('strike', 0):.2f}")
            print(f"    Premium: ${opp.get('premium', 0):.2f}")
            print(f"    DTE: {opp.get('dte', 0)} days")

        total_opportunities = len(put_opportunities) + len(call_opportunities)
        print(f"\n  📊 Total opportunities: {total_opportunities}")

    except Exception as e:
        print(f"✗ Scan error: {e}")
        import traceback
        traceback.print_exc()
        return

    # Check positions
    print("\n5. CHECKING CURRENT POSITIONS...")
    print("-" * 80)
    try:
        positions = alpaca_client.get_positions()
        print(f"✓ Positions retrieved: {len(positions)}")

        if positions:
            for pos in positions:
                print(f"\n  Position: {pos['symbol']}")
                print(f"    Qty: {pos['qty']}")
                print(f"    Value: ${pos['market_value']:,.2f}")
                print(f"    P&L: ${pos['unrealized_pl']:,.2f}")
        else:
            print("  No active positions")

    except Exception as e:
        print(f"✗ Error: {e}")

    print("\n" + "=" * 80)
    print("WORKFLOW TEST COMPLETE")
    print("=" * 80)

    # Summary
    if total_opportunities > 0:
        print("\n✅ System is ready to trade!")
        print(f"   Found {total_opportunities} trading opportunities")
        print("   When market opens, the strategy can execute trades")
    else:
        print("\n⚠️  No trading opportunities found")
        print("   This is expected when:")
        print("   - Market is closed (no real-time options data)")
        print("   - Volatility is too low/high")
        print("   - Gap risk thresholds not met")
        print("   - No stocks meet all criteria")
        print("\n   System will automatically find opportunities during market hours")

if __name__ == '__main__':
    main()
