#!/usr/bin/env python3
"""Analyze why no covered calls were sold during UNH stock holding period."""

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


def analyze_missed_calls():
    """Analyze why covered calls weren't sold during stock holding period."""
    print("🔍 ANALYZING MISSED COVERED CALL OPPORTUNITIES")
    print("=" * 70)

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

    # Analyze Week 7: August 18 (stock at $308, cost basis $260)
    analysis_date = datetime.strptime("2025-08-18", '%Y-%m-%d')
    friday_expiration = datetime.strptime("2025-08-22", '%Y-%m-%d')

    print(f"Analysis Date: {analysis_date.strftime('%Y-%m-%d')} (Monday)")
    print(f"Target Expiration: {friday_expiration.strftime('%Y-%m-%d')} (Friday)")
    print(f"Strategy: Covered calls on 100 shares at $260 cost basis")

    # Get stock price
    stock_request = StockBarsRequest(
        symbol_or_symbols=["UNH"],
        timeframe=TimeFrame.Day,
        start=analysis_date,
        end=analysis_date + timedelta(days=1)
    )

    stock_bars = stock_client.get_stock_bars(stock_request)
    stock_df = stock_bars.df

    if stock_df.empty:
        print("❌ No stock data")
        return

    stock_df = stock_df.reset_index()
    unh_data = stock_df[stock_df['symbol'] == 'UNH']
    stock_price = float(unh_data['close'].iloc[0])

    print(f"UNH Stock Price: ${stock_price:.2f}")
    print(f"Unrealized Gain: ${stock_price - 260:.2f} per share (${(stock_price - 260) * 100:.0f} total)")
    print()

    # Generate call option symbols for Friday expiration
    base_strike = round(stock_price / 2.5) * 2.5
    call_strikes = []

    # Generate strikes from current price up to +20%
    for i in range(-2, 12):  # Start slightly below current price
        strike = base_strike + (i * 2.5)
        if strike >= 260:  # Must be above cost basis for profitable call
            call_strikes.append(strike)

    call_symbols = []
    for strike in call_strikes:
        strike_str = f"{int(strike * 1000):08d}"
        call_symbol = f"UNH250822C{strike_str}"  # Friday 8/22 expiration
        call_symbols.append((strike, call_symbol))

    print(f"Generated {len(call_symbols)} call symbols for analysis")
    print("Sample symbols:", [symbol for _, symbol in call_symbols[:3]])

    # Get call options data
    symbols_only = [symbol for _, symbol in call_symbols]

    try:
        bars_request = OptionBarsRequest(
            symbol_or_symbols=symbols_only,
            timeframe=TimeFrame.Day,
            start=analysis_date,
            end=analysis_date + timedelta(days=1)
        )

        bars_response = option_client.get_option_bars(bars_request)

        if hasattr(bars_response, 'df') and not bars_response.df.empty:
            df = bars_response.df.copy()
            print(f"✅ Retrieved data for {len(df)} call option records")

            # Analyze each call option
            calls_data = []
            symbols_found = df.index.get_level_values('symbol').unique()

            print(f"\n📊 CALL OPTIONS ANALYSIS")
            print("=" * 90)
            print(f"{'Strike':<8} {'Symbol':<20} {'Premium':<10} {'Volume':<8} {'OTM':<8} {'Profit':<10} {'Quality'}")
            print("=" * 90)

            for strike, symbol in call_symbols:
                if symbol in symbols_found:
                    symbol_data = df.loc[symbol]

                    if hasattr(symbol_data, 'iloc'):
                        symbol_data = symbol_data.iloc[0] if len(symbol_data) > 1 else symbol_data

                    bid = float(symbol_data.get('close', 0))  # Using close as proxy for bid
                    volume = int(symbol_data.get('volume', 0))

                    # Calculate metrics
                    otm_amount = strike - stock_price
                    otm_percent = (otm_amount / stock_price) * 100
                    is_otm = strike > stock_price

                    # Profit calculation (premium + capital gain)
                    capital_gain = strike - 260  # Gain vs cost basis
                    total_profit = bid + capital_gain

                    # Quality scoring (simplified)
                    volume_score = min(1.0, volume / 100) if volume > 0 else 0
                    otm_score = 1.0 if is_otm else 0.5  # Prefer OTM
                    profit_score = min(1.0, total_profit / 50)  # $50 target
                    quality_score = (volume_score * 0.4 + otm_score * 0.3 + profit_score * 0.3)

                    call_info = {
                        'strike': strike,
                        'symbol': symbol,
                        'bid': bid,
                        'volume': volume,
                        'otm_amount': otm_amount,
                        'otm_percent': otm_percent,
                        'is_otm': is_otm,
                        'capital_gain': capital_gain,
                        'total_profit': total_profit,
                        'quality_score': quality_score
                    }
                    calls_data.append(call_info)

                    # Display row
                    otm_str = f"{otm_percent:+.1f}%" if is_otm else f"{otm_percent:.1f}%"
                    profit_str = f"${total_profit:.2f}"
                    quality_str = f"{quality_score:.3f}"

                    marker = ""
                    if volume > 0 and bid > 0.5 and is_otm:
                        marker = " ✅"
                    elif volume == 0:
                        marker = " ❌ No Vol"
                    elif bid < 0.5:
                        marker = " ❌ Low Prem"
                    elif not is_otm:
                        marker = " ⚠️ ITM"

                    print(f"{strike:<8.0f} {symbol:<20} ${bid:<9.2f} {volume:<8} {otm_str:<8} {profit_str:<10} {quality_str:<7}{marker}")

                else:
                    print(f"{strike:<8.0f} {symbol:<20} {'NO DATA':<10} {'N/A':<8} {'N/A':<8} {'N/A':<10} {'N/A':<7} ❌ No Data")

            # Strategy criteria analysis
            print(f"\n📋 STRATEGY CRITERIA ANALYSIS")
            print("-" * 50)

            # Filter by strategy criteria
            min_premium = config.min_call_premium if hasattr(config, 'min_call_premium') else 0.50
            min_volume = 10

            suitable_calls = [
                call for call in calls_data
                if call['bid'] >= min_premium
                and call['volume'] >= min_volume
                and call['is_otm']
                and call['bid'] > 0
            ]

            print(f"Minimum Premium: ${min_premium:.2f}")
            print(f"Minimum Volume: {min_volume}")
            print(f"Must be OTM: Yes")
            print(f"Must have positive bid: Yes")

            print(f"\nResults:")
            print(f"  Total Calls Found: {len(calls_data)}")
            print(f"  Strategy-Suitable: {len(suitable_calls)}")

            if suitable_calls:
                print(f"\n🏆 SUITABLE COVERED CALLS:")
                best_call = max(suitable_calls, key=lambda x: x['quality_score'])

                for call in sorted(suitable_calls, key=lambda x: x['quality_score'], reverse=True):
                    marker = " 🎯 BEST" if call == best_call else ""
                    print(f"    {call['strike']:.0f}C: ${call['bid']:.2f} premium, ${call['total_profit']:.2f} total profit, {call['volume']} vol{marker}")

                print(f"\n💰 BEST OPPORTUNITY DETAILS:")
                print(f"    Strike: ${best_call['strike']:.0f}")
                print(f"    Premium: ${best_call['bid']:.2f}")
                print(f"    Capital Gain: ${best_call['capital_gain']:.2f}")
                print(f"    Total Profit: ${best_call['total_profit']:.2f}")
                print(f"    OTM Buffer: {best_call['otm_percent']:.1f}%")
                print(f"    Volume: {best_call['volume']:,}")

                print(f"\n❓ WHY WASN'T THIS EXECUTED?")
                print(f"    This suggests the strategy criteria may be too restrictive")
                print(f"    or there's an issue with the option filtering logic.")

            else:
                print(f"\n❌ NO SUITABLE CALLS FOUND")

                # Analyze why not
                print(f"\n📊 FAILURE ANALYSIS:")

                if calls_data:
                    low_premium = [c for c in calls_data if c['bid'] < min_premium]
                    low_volume = [c for c in calls_data if c['volume'] < min_volume]
                    itm_calls = [c for c in calls_data if not c['is_otm']]
                    no_bid = [c for c in calls_data if c['bid'] <= 0]

                    print(f"    Low Premium (< ${min_premium:.2f}): {len(low_premium)}")
                    print(f"    Low Volume (< {min_volume}): {len(low_volume)}")
                    print(f"    In-The-Money: {len(itm_calls)}")
                    print(f"    No Bid/Zero Premium: {len(no_bid)}")

                    if low_premium:
                        avg_premium = sum(c['bid'] for c in low_premium) / len(low_premium)
                        print(f"    Average low premium: ${avg_premium:.2f}")

                    if low_volume:
                        avg_volume = sum(c['volume'] for c in low_volume) / len(low_volume)
                        print(f"    Average low volume: {avg_volume:.0f}")

                else:
                    print(f"    No option data available at all")

        else:
            print("❌ No call option data retrieved")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    analyze_missed_calls()