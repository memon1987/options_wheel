#!/usr/bin/env python3
"""
Test script to check actual Alpaca paper account positions and details.
This will show us what's REALLY in the account vs what the server reports.
"""

import sys
import os
from datetime import datetime

# Add src to path
sys.path.insert(0, '/Users/zmemon/options_wheel-1')

from src.utils.config import Config
from src.api.alpaca_client import AlpacaClient

def main():
    print("=" * 80)
    print("ALPACA PAPER ACCOUNT STATUS CHECK")
    print("=" * 80)

    # Initialize
    config = Config()
    client = AlpacaClient(config)

    # Get account info
    print("\n1. ACCOUNT INFORMATION:")
    print("-" * 80)
    try:
        account = client.get_account()
        print(f"   Cash Available: ${account['cash']:,.2f}")
        print(f"   Portfolio Value: ${account['portfolio_value']:,.2f}")
        print(f"   Buying Power: ${account['buying_power']:,.2f}")
        print(f"   Options Buying Power: ${account.get('options_buying_power', 0):,.2f}")
        print(f"   Options Approval Level: {account.get('options_approved_level', 'N/A')}")
    except Exception as e:
        print(f"   ERROR: {e}")

    # Get positions
    print("\n2. CURRENT POSITIONS:")
    print("-" * 80)
    try:
        positions = client.get_positions()
        if not positions:
            print("   No positions found")
        else:
            for pos in positions:
                print(f"\n   Symbol: {pos['symbol']}")
                print(f"   Qty: {pos['qty']}")
                print(f"   Market Value: ${pos['market_value']:,.2f}")
                print(f"   Cost Basis: ${pos['cost_basis']:,.2f}")
                print(f"   P&L: ${pos['unrealized_pl']:,.2f}")
                print(f"   Side: {pos['side']}")
                print(f"   Asset Class: {pos['asset_class']}")
    except Exception as e:
        print(f"   ERROR: {e}")

    # Get orders using direct trading client
    print("\n3. RECENT ORDERS (Last 10):")
    print("-" * 80)
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus

        request = GetOrdersRequest(
            status=QueryOrderStatus.ALL,
            limit=10
        )
        orders = client.trading_client.get_orders(filter=request)

        if not orders:
            print("   No orders found")
        else:
            for order in orders:
                print(f"\n   {order.submitted_at} - {order.symbol}")
                print(f"   Side: {order.side} | Type: {order.type}")
                print(f"   Qty: {order.qty}")
                print(f"   Status: {order.status}")
                if order.filled_at:
                    print(f"   Filled: {order.filled_at} @ ${float(order.filled_avg_price):.2f}")
    except Exception as e:
        print(f"   ERROR: {e}")

    # Check market status using direct trading client
    print("\n4. MARKET STATUS:")
    print("-" * 80)
    try:
        clock = client.trading_client.get_clock()
        print(f"   Market Open: {clock.is_open}")
        print(f"   Current Time: {clock.timestamp}")
        print(f"   Next Open: {clock.next_open}")
        print(f"   Next Close: {clock.next_close}")
    except Exception as e:
        print(f"   ERROR: {e}")

    print("\n" + "=" * 80)
    print("ACCOUNT CHECK COMPLETE")
    print("=" * 80)

if __name__ == '__main__':
    main()
