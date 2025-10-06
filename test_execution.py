#!/usr/bin/env python3
"""Quick local test of scan-to-execution flow."""

import json
from datetime import datetime
from src.utils.config import Config
from src.api.alpaca_client import AlpacaClient
from src.api.market_data import MarketDataManager
from src.strategy.put_seller import PutSeller
from src.data.opportunity_store import OpportunityStore

def main():
    print("=== Local Execution Test ===\n")

    # Initialize
    config = Config()
    alpaca_client = AlpacaClient(config)
    market_data = MarketDataManager(alpaca_client, config)
    opportunity_store = OpportunityStore(config)
    put_seller = PutSeller(alpaca_client, market_data, config)

    # Get opportunities
    execution_time = datetime.now()
    opportunities = opportunity_store.get_pending_opportunities(execution_time)

    print(f"Found {len(opportunities)} opportunities\n")

    if opportunities:
        print("First opportunity structure:")
        print(json.dumps(opportunities[0], indent=2))
        print("\n" + "="*50 + "\n")

        # Check what fields are missing for execute_put_sale
        required_fields = ['option_symbol', 'contracts', 'premium', 'strike_price']
        first_opp = opportunities[0]

        print("Field check:")
        for field in required_fields:
            if field in first_opp:
                print(f"  ✓ {field}: {first_opp[field]}")
            else:
                print(f"  ✗ {field}: MISSING")

        # Try to add missing contracts field
        if 'contracts' not in first_opp:
            print("\n" + "="*50)
            print("ISSUE: 'contracts' field is missing!")
            print("Need to calculate position size before execution")
            print("="*50)

            # Calculate contracts (simplified - normally done by position sizing)
            strike_price = first_opp.get('strike_price', 0)
            if strike_price > 0:
                account = alpaca_client.get_account()
                portfolio_value = account.get('portfolio_value', 100000)
                max_position_size = config.max_position_size

                capital_per_contract = strike_price * 100
                max_by_allocation = int((portfolio_value * max_position_size) / capital_per_contract)
                contracts = min(1, max_by_allocation)  # Conservative: 1 contract

                print(f"\nCalculated contracts: {contracts}")
                print(f"  Capital per contract: ${capital_per_contract:,.2f}")
                print(f"  Portfolio value: ${portfolio_value:,.2f}")
                print(f"  Max position size: {max_position_size}")

if __name__ == "__main__":
    main()
