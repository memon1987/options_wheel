#!/usr/bin/env python3
"""Detailed trade-by-trade analysis of Monday-only backtest results."""

import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# Run the Monday backtest to get results
from monday_only_backtest import MondayOnlyBacktester


def analyze_trade_by_trade():
    """Generate detailed trade-by-trade analysis."""
    print("📊 DETAILED TRADE-BY-TRADE ANALYSIS")
    print("=" * 80)
    print("Monday-Only UNH Options Wheel Strategy (Past 12 Weeks)")
    print("Strategy: 5 DTE Friday Expirations, Monday Entries Only")

    # Run the backtest to get detailed results
    backtester = MondayOnlyBacktester()
    results = backtester.run_monday_backtest('UNH', weeks=12)

    if 'error' in results:
        print(f"❌ Error: {results['error']}")
        return

    # Extract completed trades
    completed_trades = [t for t in results['all_trades'] if t.get('status') == 'closed']

    print(f"\n🎯 STRATEGY OVERVIEW")
    print("-" * 50)
    print(f"Testing Period: {results['start_date']} to {results['end_date']}")
    print(f"Total Trading Mondays: {results['total_mondays']}")
    print(f"Trades Executed: {len(completed_trades)}")
    print(f"Execution Rate: {len(completed_trades)/results['total_mondays']*100:.1f}%")

    if not completed_trades:
        print("\n❌ No completed trades to analyze")
        return

    print(f"\n📈 PERFORMANCE SUMMARY")
    print("-" * 50)
    print(f"Win Rate: {results['win_rate']:.1f}%")
    print(f"Total Premium Collected: ${results['total_premium_collected']:.2f}")
    print(f"Total P&L: ${results['total_pnl']:.2f}")
    print(f"Average P&L per Trade: ${results['average_pnl_per_trade']:.2f}")
    print(f"Overall Return: {results['pnl_percentage']:.1f}%")
    print(f"Assignment Rate: {results['assignment_rate']:.1f}%")

    # Analyze each trade in detail
    print(f"\n🔍 TRADE-BY-TRADE WALKTHROUGH")
    print("=" * 80)

    for i, trade in enumerate(completed_trades, 1):
        print(f"\n📅 TRADE #{i}: {trade['entry_date'].strftime('%Y-%m-%d')} → {trade['expiration_date'].strftime('%Y-%m-%d')}")
        print("-" * 70)

        # Entry Analysis
        print(f"📥 ENTRY DETAILS:")
        print(f"   Date: {trade['entry_date'].strftime('%A, %B %d, %Y')}")
        print(f"   UNH Stock Price: ${trade['entry_stock_price']:.2f}")
        print(f"   Option: {trade['strike_price']:.0f} Put")
        print(f"   Premium Collected: ${trade['entry_premium']:.2f}")
        print(f"   Delta: {trade['entry_delta']:.3f}")
        print(f"   Volume: {trade['volume']:,} contracts")
        print(f"   Quality Score: {trade['quality_score']:.3f}")

        # Position Analysis
        otm_amount = trade['entry_stock_price'] - trade['strike_price']
        otm_percent = (otm_amount / trade['entry_stock_price']) * 100

        print(f"\n📊 POSITION ANALYSIS:")
        print(f"   Strike vs Stock: ${trade['strike_price']:.0f} vs ${trade['entry_stock_price']:.2f}")
        print(f"   OTM Amount: ${otm_amount:.2f} ({otm_percent:.1f}%)")
        print(f"   Breakeven: ${trade['strike_price'] - trade['entry_premium']:.2f}")
        print(f"   Max Profit: ${trade['entry_premium']:.2f} (if expires worthless)")
        print(f"   Assignment Risk: Stock below ${trade['strike_price']:.0f}")

        # Show daily progression if available
        if 'daily_tracking' in trade and trade['daily_tracking']:
            print(f"\n📈 DAILY PROGRESSION:")
            print(f"   {'Date':<12} {'Stock':<8} {'Days':<5} {'Option':<8} {'P&L':<8} {'P&L%':<8}")
            print(f"   {'-'*12} {'-'*8} {'-'*5} {'-'*8} {'-'*8} {'-'*8}")

            for tracking in trade['daily_tracking']:
                date_str = tracking['date'].strftime('%m/%d')
                stock_str = f"${tracking['stock_price']:.2f}"
                dte_str = f"{tracking['days_to_expiration']}"
                option_str = f"${tracking['option_price']:.2f}"
                pnl_str = f"${tracking['position_pnl']:.2f}"
                pnl_pct_str = f"{tracking['pnl_percent']:.1f}%"

                print(f"   {date_str:<12} {stock_str:<8} {dte_str:<5} {option_str:<8} {pnl_str:<8} {pnl_pct_str:<8}")

        # Exit Analysis
        print(f"\n📤 EXIT DETAILS:")
        print(f"   Exit Date: {trade['close_date'].strftime('%A, %B %d, %Y')}")
        print(f"   Exit Reason: {trade['close_reason'].title()}")
        print(f"   Final Stock Price: ${trade['final_stock_price']:.2f}")
        print(f"   Final Option Price: ${trade['final_option_price']:.2f}")
        print(f"   Days Held: {trade['days_held']}")

        # P&L Analysis
        print(f"\n💰 PROFIT & LOSS:")
        print(f"   Premium Collected: ${trade['entry_premium']:.2f}")
        print(f"   Option Cost to Close: ${trade['final_option_price']:.2f}")
        print(f"   Net P&L: ${trade['final_pnl']:.2f}")
        print(f"   Return: {trade['final_pnl_percent']:.1f}%")

        if trade.get('assigned', False):
            print(f"   🎯 ASSIGNMENT OCCURRED")
            print(f"   Stock purchased at: ${trade['strike_price']:.2f}")
            print(f"   Market price: ${trade['final_stock_price']:.2f}")
            print(f"   Unrealized stock loss: ${trade['final_stock_price'] - trade['strike_price']:.2f}")
            print(f"   Effective cost basis: ${trade['strike_price'] - trade['entry_premium']:.2f}")
        else:
            print(f"   ✅ OPTION EXPIRED WORTHLESS - KEPT FULL PREMIUM")

        # Trade Outcome
        if trade['final_pnl'] > 0:
            outcome = "🟢 WINNING TRADE"
        else:
            outcome = "🔴 LOSING TRADE"

        print(f"\n{outcome}")

        # Risk Analysis
        print(f"\n⚠️  RISK FACTORS:")
        max_loss = trade['strike_price'] * 100 - trade['entry_premium'] * 100  # Per contract
        print(f"   Max Theoretical Loss: ${max_loss:.0f} per contract (if stock goes to $0)")
        print(f"   Actual Risk Taken: {abs(otm_percent):.1f}% out-of-the-money buffer")

        # What We Learned
        print(f"\n🎓 LESSONS:")
        if trade.get('assigned', False):
            print(f"   • Assignment occurred due to stock dropping {otm_percent:.1f}% below strike")
            print(f"   • 5-day options provide limited time for recovery")
            print(f"   • Consider wider OTM strikes for crash protection")
        else:
            print(f"   • Successful trade - stock stayed above ${trade['strike_price']:.0f}")
            print(f"   • {otm_percent:.1f}% OTM buffer was sufficient")
            print(f"   • 5-day time decay worked in our favor")

    # Overall Strategy Analysis
    print(f"\n🎯 OVERALL STRATEGY ANALYSIS")
    print("=" * 60)

    winning_trades = [t for t in completed_trades if t['final_pnl'] > 0]
    losing_trades = [t for t in completed_trades if t['final_pnl'] <= 0]
    assigned_trades = [t for t in completed_trades if t.get('assigned', False)]

    print(f"📊 TRADE BREAKDOWN:")
    print(f"   Winning Trades: {len(winning_trades)} ({len(winning_trades)/len(completed_trades)*100:.1f}%)")
    print(f"   Losing Trades: {len(losing_trades)} ({len(losing_trades)/len(completed_trades)*100:.1f}%)")
    print(f"   Assignments: {len(assigned_trades)} ({len(assigned_trades)/len(completed_trades)*100:.1f}%)")

    if winning_trades:
        avg_win = sum(t['final_pnl'] for t in winning_trades) / len(winning_trades)
        avg_win_pct = sum(t['final_pnl_percent'] for t in winning_trades) / len(winning_trades)
        print(f"   Average Win: ${avg_win:.2f} ({avg_win_pct:.1f}%)")

    if losing_trades:
        avg_loss = sum(t['final_pnl'] for t in losing_trades) / len(losing_trades)
        avg_loss_pct = sum(t['final_pnl_percent'] for t in losing_trades) / len(losing_trades)
        print(f"   Average Loss: ${avg_loss:.2f} ({avg_loss_pct:.1f}%)")

    print(f"\n📈 RISK/REWARD PROFILE:")
    profit_factor = sum(t['final_pnl'] for t in winning_trades) / abs(sum(t['final_pnl'] for t in losing_trades)) if losing_trades else float('inf')
    print(f"   Profit Factor: {profit_factor:.2f}")
    print(f"   Risk/Reward Ratio: 1:{profit_factor:.2f}")

    # Market Conditions Analysis
    stock_prices = [t['entry_stock_price'] for t in completed_trades]
    print(f"\n📊 MARKET CONDITIONS:")
    print(f"   UNH Price Range: ${min(stock_prices):.2f} - ${max(stock_prices):.2f}")
    print(f"   Price Volatility: {(max(stock_prices) - min(stock_prices))/min(stock_prices)*100:.1f}%")

    # Strategy Effectiveness
    print(f"\n🎯 STRATEGY EFFECTIVENESS:")
    print(f"   Monday-Only Entry: Limited opportunities ({len(completed_trades)}/{results['total_mondays']} weeks traded)")
    print(f"   5-Day Expiration: Fast theta decay but limited recovery time")
    print(f"   Friday Expiration: Weekly cycle alignment")

    if len(assigned_trades) > 0:
        print(f"   Assignment Risk: Realized in {len(assigned_trades)} out of {len(completed_trades)} trades")

    # Recommendations
    print(f"\n💡 STRATEGY RECOMMENDATIONS:")
    if results['pnl_percentage'] < 0:
        print(f"   ⚠️  Strategy shows negative return (-{abs(results['pnl_percentage']):.1f}%)")
        print(f"   • Consider wider OTM strikes to reduce assignment risk")
        print(f"   • Evaluate 7-10 DTE options for more time decay opportunity")
        print(f"   • Implement profit-taking rules (e.g., close at 50% profit)")
    else:
        print(f"   ✅ Strategy shows positive return (+{results['pnl_percentage']:.1f}%)")
        print(f"   • Current approach appears effective")
        print(f"   • Consider position sizing optimization")

    print(f"   • Monitor market volatility - strategy may perform differently in varying conditions")
    print(f"   • Track assignment costs vs premium collection over longer periods")


if __name__ == '__main__':
    analyze_trade_by_trade()