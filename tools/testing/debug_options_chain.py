#!/usr/bin/env python3
"""Debug script to examine options chain data structure."""

import os
import sys
from dotenv import load_dotenv

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.api.alpaca_client import AlpacaClient
from src.utils.config import Config
from alpaca.data.requests import OptionChainRequest


def debug_options_chain():
    """Debug the options chain API response."""
    load_dotenv()
    config = Config("config/settings.yaml")
    client = AlpacaClient(config)

    print("🔍 DEBUGGING OPTIONS CHAIN API")
    print("=" * 50)

    symbol = "UNH"
    print(f"Symbol: {symbol}")

    try:
        # Use the raw Alpaca client directly
        request = OptionChainRequest(underlying_symbol=symbol)
        print(f"Request: {request}")

        chain = client.option_data_client.get_option_chain(request)
        print(f"\nRaw chain type: {type(chain)}")
        print(f"Chain length: {len(chain) if hasattr(chain, '__len__') else 'N/A'}")

        # Examine first few items
        if isinstance(chain, dict):
            for i, (option_symbol, contract) in enumerate(chain.items()):
                if i >= 3:  # Only check first 3 items
                    break
                print(f"\nItem {i}:")
                print(f"  Option Symbol: {option_symbol}")
                print(f"  Contract Type: {type(contract)}")

                if hasattr(contract, 'strike_price'):
                    print(f"  Strike: {getattr(contract, 'strike_price', 'N/A')}")
                    print(f"  Expiration: {getattr(contract, 'expiration_date', 'N/A')}")
                    print(f"  Option Type: {getattr(contract, 'option_type', 'N/A')}")
                    print(f"  Bid: {getattr(contract, 'bid', 'N/A')}")
                    print(f"  Ask: {getattr(contract, 'ask', 'N/A')}")
                    print(f"  Delta: {getattr(contract, 'delta', 'N/A')}")
                    print(f"  Volume: {getattr(contract, 'volume', 'N/A')}")
                else:
                    print(f"  Contract Value: {contract}")
        else:
            print(f"Chain is not a dict: {chain}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    debug_options_chain()