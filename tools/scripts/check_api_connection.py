#!/usr/bin/env python3
"""Test script to verify Alpaca API connection."""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.config import Config
from src.api.alpaca_client import AlpacaClient

def test_connection():
    """Test the Alpaca API connection."""
    try:
        print('🔄 Loading configuration...')
        config = Config()
        
        print('🔄 Initializing Alpaca client...')
        client = AlpacaClient(config)
        
        print('🔄 Testing API connection...')
        account = client.get_account()
        
        print('\n✅ API CONNECTION SUCCESSFUL!')
        print('=' * 50)
        print(f'Environment: {"Paper Trading" if config.paper_trading else "Live Trading"}')
        print(f'Portfolio Value: ${account["portfolio_value"]:,.2f}')
        print(f'Cash: ${account["cash"]:,.2f}')
        print(f'Buying Power: ${account["buying_power"]:,.2f}')
        print(f'Equity: ${account["equity"]:,.2f}')
        
        if 'options_buying_power' in account:
            print(f'Options Buying Power: ${account["options_buying_power"]:,.2f}')
        if 'options_approved_level' in account:
            print(f'Options Approval Level: {account["options_approved_level"]}')
        
        print('\n🔄 Testing position retrieval...')
        positions = client.get_positions()
        print(f'Current Positions: {len(positions)}')
        
        if positions:
            print('\nPositions:')
            for pos in positions[:5]:  # Show first 5 positions
                print(f'  {pos["symbol"]}: {pos["qty"]} shares, ${pos["market_value"]:,.2f}')
        
        print('\n🔄 Testing market data...')
        quote = client.get_stock_quote('AAPL')
        print(f'AAPL Quote: Bid=${quote["bid"]:.2f}, Ask=${quote["ask"]:.2f}')
        
        print('\n🎉 All API tests passed successfully!')
        return True
        
    except Exception as e:
        print(f'\n❌ API CONNECTION FAILED: {str(e)}')
        print('\nTroubleshooting steps:')
        print('1. Check your .env file has the correct API keys')
        print('2. Verify you are using paper trading keys if ALPACA_ENV=paper')
        print('3. Ensure your Alpaca account has options trading enabled')
        print('4. Check your internet connection')
        print('5. Make sure your API keys have the correct permissions')
        return False

if __name__ == '__main__':
    success = test_connection()
    sys.exit(0 if success else 1)