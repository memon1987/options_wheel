#!/usr/bin/env python3
"""Check current options trading status."""

import os
import requests
from dotenv import load_dotenv

def check_options_status():
    """Check if options trading is enabled."""
    
    load_dotenv()
    
    api_key = os.getenv('ALPACA_API_KEY')
    secret_key = os.getenv('ALPACA_SECRET_KEY')
    
    headers = {
        'APCA-API-KEY-ID': api_key,
        'APCA-API-SECRET-KEY': secret_key,
    }
    
    try:
        response = requests.get(
            "https://paper-api.alpaca.markets/v2/account",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            
            print("📊 ACCOUNT OPTIONS STATUS")
            print("=" * 40)
            print(f"Account Status: {data.get('status', 'Unknown')}")
            print(f"Account ID: {data.get('id', 'Unknown')}")
            
            # Check options-specific fields
            options_fields = [
                'options_buying_power',
                'options_approved_level', 
                'max_options_trading_level',
                'options_trading_level'
            ]
            
            print(f"\nOptions Trading Status:")
            options_enabled = False
            
            for field in options_fields:
                value = data.get(field)
                if value is not None:
                    print(f"  {field}: {value}")
                    options_enabled = True
                else:
                    print(f"  {field}: Not set")
            
            if options_enabled:
                print("\n✅ Options trading appears to be enabled!")
            else:
                print("\n❌ Options trading not enabled or not visible in account data")
                print("\n📋 Next steps:")
                print("1. Log into https://app.alpaca.markets")
                print("2. Go to Account → Trading Permissions")
                print("3. Apply for Options Trading Level 2 (for wheel strategy)")
                print("4. Wait for approval (1-2 business days)")
                print("5. Regenerate API keys with options permissions")
            
            # Check if we can access options data
            print(f"\n🔄 Testing options chain access...")
            
            try:
                from alpaca.data import OptionHistoricalDataClient
                option_client = OptionHistoricalDataClient(
                    api_key=api_key, 
                    secret_key=secret_key
                )
                print("✅ Options data client created successfully")
            except Exception as e:
                print(f"❌ Options data access failed: {str(e)}")
            
        else:
            print(f"❌ API call failed: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Error checking options status: {str(e)}")

if __name__ == '__main__':
    check_options_status()