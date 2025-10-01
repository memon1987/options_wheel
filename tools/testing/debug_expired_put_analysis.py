#!/usr/bin/env python3
"""Debug version to show all put options from 9/23 with detailed breakdown."""

import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import pandas as pd
from dotenv import load_dotenv

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.utils.config import Config
from alpaca.data import OptionHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import OptionBarsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame


def parse_option_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    """Parse option symbol to extract details."""
    try:
        if 'P' in symbol:
            parts = symbol.split('P')
            option_type = 'PUT'
        elif 'C' in symbol:
            parts = symbol.split('C')
            option_type = 'CALL'
        else:
            return None

        if len(parts) != 2:
            return None

        prefix = parts[0]
        strike_str = parts[1]

        if len(prefix) >= 9:
            underlying = prefix[:-6]
            date_str = prefix[-6:]

            year = 2000 + int(date_str[:2])
            month = int(date_str[2:4])
            day = int(date_str[4:6])
            exp_date = datetime(year, month, day)

            strike_price = float(strike_str) / 1000.0

            return {
                'underlying': underlying,
                'expiration': exp_date,
                'option_type': option_type,
                'strike_price': strike_price
            }

        return None

    except Exception as e:
        return None


def main():
    """Debug analysis of all put options."""
    print("🔍 DEBUG: ALL PUT OPTIONS FROM 9/23 → 9/26")
    print("=" * 60)

    load_dotenv()
    config = Config("config/settings.yaml")

    option_client = OptionHistoricalDataClient(
        api_key=config.alpaca_api_key,
        secret_key=config.alpaca_secret_key
    )

    stock_client = StockHistoricalDataClient(
        api_key=config.alpaca_api_key,
        secret_key=config.alpaca_secret_key
    )

    # Get stock price
    target_date = datetime.strptime("2025-09-23", '%Y-%m-%d')
    stock_request = StockBarsRequest(
        symbol_or_symbols=["UNH"],
        timeframe=TimeFrame.Day,
        start=target_date,
        end=target_date + timedelta(days=1)
    )

    stock_bars = stock_client.get_stock_bars(stock_request)
    stock_df = stock_bars.df

    if stock_df.empty:
        print("❌ No stock data")
        return

    stock_df = stock_df.reset_index()
    unh_data = stock_df[stock_df['symbol'] == 'UNH']
    stock_price = float(unh_data['close'].iloc[0])

    print(f"UNH Stock Price (9/23): ${stock_price:.2f}")

    # Generate option symbols around stock price
    base_strike = round(stock_price / 2.5) * 2.5
    strikes = []
    for i in range(-8, 9):
        strike = base_strike + (i * 2.5)
        if strike > 0:
            strikes.append(strike)

    # Generate put symbols only
    put_symbols = []
    for strike in strikes:
        strike_str = f"{int(strike * 1000):08d}"
        put_symbol = f"UNH250926P{strike_str}"
        put_symbols.append(put_symbol)

    print(f"Testing {len(put_symbols)} put symbols")
    print("Sample symbols:", put_symbols[:5])

    # Get options data
    try:
        bars_request = OptionBarsRequest(
            symbol_or_symbols=put_symbols,
            timeframe=TimeFrame.Day,
            start=target_date,
            end=target_date + timedelta(days=1)
        )

        bars_response = option_client.get_option_bars(bars_request)

        if hasattr(bars_response, 'df') and not bars_response.df.empty:
            df = bars_response.df.copy()
            print(f"✅ Retrieved data for {len(df)} put option records")

            # Process each put option
            puts_data = []
            symbols = df.index.get_level_values('symbol').unique()

            for symbol in symbols:
                parsed = parse_option_symbol(symbol)
                if parsed and parsed['option_type'] == 'PUT':
                    symbol_data = df.loc[symbol]

                    if hasattr(symbol_data, 'iloc'):
                        symbol_data = symbol_data.iloc[0] if len(symbol_data) > 1 else symbol_data

                    put_info = {
                        'symbol': symbol,
                        'strike': parsed['strike_price'],
                        'close': float(symbol_data['close']),
                        'volume': int(symbol_data['volume']),
                        'open': float(symbol_data['open']),
                        'high': float(symbol_data['high']),
                        'low': float(symbol_data['low']),
                    }

                    # Calculate metrics
                    put_info['otm'] = stock_price > parsed['strike_price']
                    put_info['moneyness'] = stock_price / parsed['strike_price']

                    # Simple delta approximation for 3-day puts
                    if put_info['otm']:
                        # For OTM puts, delta is smaller
                        put_info['approx_delta'] = abs(1 - put_info['moneyness']) * 0.5
                    else:
                        # For ITM puts, delta is larger
                        put_info['approx_delta'] = abs(put_info['moneyness'] - 1) + 0.5

                    puts_data.append(put_info)

            # Sort by strike
            puts_data.sort(key=lambda x: x['strike'])

            print(f"\n📊 ALL PUT OPTIONS ANALYSIS (3-day expiration)")
            print("=" * 100)
            print(f"{'Strike':<8} {'Premium':<8} {'Volume':<8} {'OTM':<5} {'Moneyness':<10} {'Delta':<8} {'Symbol'}")
            print("=" * 100)

            strategy_puts = []
            min_premium = config.min_put_premium
            delta_min, delta_max = config.put_delta_range

            for put in puts_data:
                strike = put['strike']
                premium = put['close']
                volume = put['volume']
                otm = 'Yes' if put['otm'] else 'No'
                moneyness = put['moneyness']
                delta = put['approx_delta']
                symbol = put['symbol']

                # Check strategy criteria
                meets_criteria = (
                    premium >= min_premium and
                    volume > 0 and
                    delta_min <= delta <= delta_max
                )

                if meets_criteria:
                    strategy_puts.append(put)
                    marker = " ✅"
                else:
                    marker = ""

                print(f"{strike:<8.1f} ${premium:<7.2f} {volume:<8} {otm:<5} {moneyness:<10.3f} {delta:<8.3f} {symbol}{marker}")

            print(f"\n📋 STRATEGY CRITERIA:")
            print(f"  Minimum Premium: ${min_premium:.2f}")
            print(f"  Delta Range: {delta_min:.2f} - {delta_max:.2f}")
            print(f"  Volume > 0")

            print(f"\n🎯 RESULTS:")
            print(f"  Total Puts Found: {len(puts_data)}")
            print(f"  Strategy-Suitable: {len(strategy_puts)}")

            if strategy_puts:
                premiums = [p['close'] for p in strategy_puts]
                print(f"\n💰 STRATEGY-SUITABLE PUTS:")
                print(f"  Premium Range: ${min(premiums):.2f} - ${max(premiums):.2f}")
                print(f"  Average Premium: ${sum(premiums)/len(premiums):.2f}")

                print(f"\n🏆 TOP STRATEGY OPTIONS:")
                for put in sorted(strategy_puts, key=lambda x: x['close'], reverse=True)[:5]:
                    print(f"    {put['strike']:.1f} Put: ${put['close']:.2f} premium, {put['volume']} volume")

            # Compare with other timeframes
            print(f"\n🔄 COMPARISON WITH OTHER TIMEFRAMES:")
            print(f"  Historical (9/23 → 9/26): 3-day options")
            if strategy_puts:
                avg_premium = sum(p['close'] for p in strategy_puts) / len(strategy_puts)
                print(f"    Average Premium: ${avg_premium:.2f}")
                print(f"    Options Available: {len(strategy_puts)}")
            else:
                print(f"    No options meeting criteria")

            print(f"  Previous (9/25 → 10/3): 8-day options")
            print(f"    Average Premium: $0.92")
            print(f"    Options Available: 2")

            print(f"  Current (9/29 → 10/3): 4-day options")
            print(f"    Average Premium: $0.93")
            print(f"    Options Available: 3")

        else:
            print("❌ No data retrieved")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()