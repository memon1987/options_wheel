#!/usr/bin/env python3
"""Analyze AMD 2025 YTD performance with open positions tracking."""

import sys
import os
from datetime import datetime
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config import Config
from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig
from src.backtesting.analysis import BacktestAnalyzer
import structlog

logger = structlog.get_logger(__name__)


def analyze_open_positions(result, engine):
    """Analyze and display open positions at end of backtest."""
    print("\n" + "="*80)
    print("OPEN POSITIONS AS OF {}".format(result.end_date.date()))
    print("="*80)

    # Get open positions from engine
    open_puts = []
    open_calls = []
    stock_positions = []

    # Check if engine has position tracking
    if hasattr(engine, 'positions'):
        for symbol, position in engine.positions.items():
            if position.get('quantity', 0) > 0:
                stock_positions.append({
                    'symbol': symbol,
                    'quantity': position['quantity'],
                    'avg_cost': position.get('avg_cost', 0),
                    'market_value': position.get('market_value', 0)
                })

    # Check trade_history for unclosed options
    if not result.trade_history.empty:
        # Filter for trades that haven't been closed/expired
        # Puts sold that haven't been assigned or expired
        put_trades = result.trade_history[
            (result.trade_history['trade_type'] == 'put_sell') &
            (result.trade_history['status'].isin(['open', 'active']))
        ]

        # Calls sold that haven't been called away or expired
        call_trades = result.trade_history[
            (result.trade_history['trade_type'] == 'call_sell') &
            (result.trade_history['status'].isin(['open', 'active']))
        ]

        for _, trade in put_trades.iterrows():
            open_puts.append({
                'symbol': trade['symbol'],
                'strike': trade['strike_price'],
                'expiration': trade['expiration_date'],
                'premium_collected': trade['premium'],
                'contracts': trade['contracts'],
                'days_held': (result.end_date - trade['entry_date']).days
            })

        for _, trade in call_trades.iterrows():
            open_calls.append({
                'symbol': trade['symbol'],
                'strike': trade['strike_price'],
                'expiration': trade['expiration_date'],
                'premium_collected': trade['premium'],
                'contracts': trade['contracts'],
                'days_held': (result.end_date - trade['entry_date']).days
            })

    # Display stock positions
    if stock_positions:
        print("\nSTOCK POSITIONS:")
        print("-" * 80)
        print(f"{'Symbol':<10} {'Quantity':>10} {'Avg Cost':>12} {'Market Value':>15} {'P&L':>15}")
        print("-" * 80)
        for pos in stock_positions:
            pnl = pos['market_value'] - (pos['avg_cost'] * pos['quantity'])
            pnl_pct = (pnl / (pos['avg_cost'] * pos['quantity'])) * 100 if pos['avg_cost'] > 0 else 0
            print(f"{pos['symbol']:<10} {pos['quantity']:>10} ${pos['avg_cost']:>11,.2f} "
                  f"${pos['market_value']:>14,.2f} ${pnl:>14,.2f} ({pnl_pct:+.1f}%)")
    else:
        print("\nSTOCK POSITIONS: None")

    # Display open put positions
    if open_puts:
        print("\nOPEN PUT POSITIONS:")
        print("-" * 80)
        print(f"{'Symbol':<10} {'Strike':>10} {'Expiration':<12} {'Premium':>12} {'Contracts':>10} {'Days':>8}")
        print("-" * 80)
        for put in open_puts:
            print(f"{put['symbol']:<10} ${put['strike']:>9,.2f} {put['expiration']!s:<12} "
                  f"${put['premium_collected']:>11,.2f} {put['contracts']:>10} {put['days_held']:>8}")

        total_premium = sum(p['premium_collected'] for p in open_puts)
        total_collateral = sum(p['strike'] * p['contracts'] * 100 for p in open_puts)
        print("-" * 80)
        print(f"Total Premium Collected: ${total_premium:,.2f}")
        print(f"Total Collateral at Risk: ${total_collateral:,.2f}")
        print(f"Return on Collateral: {(total_premium / total_collateral * 100):.2f}%")
    else:
        print("\nOPEN PUT POSITIONS: None")

    # Display open call positions
    if open_calls:
        print("\nOPEN CALL POSITIONS:")
        print("-" * 80)
        print(f"{'Symbol':<10} {'Strike':>10} {'Expiration':<12} {'Premium':>12} {'Contracts':>10} {'Days':>8}")
        print("-" * 80)
        for call in open_calls:
            print(f"{call['symbol']:<10} ${call['strike']:>9,.2f} {call['expiration']!s:<12} "
                  f"${call['premium_collected']:>11,.2f} {call['contracts']:>10} {call['days_held']:>8}")

        total_premium = sum(c['premium_collected'] for c in open_calls)
        print("-" * 80)
        print(f"Total Premium Collected: ${total_premium:,.2f}")
    else:
        print("\nOPEN CALL POSITIONS: None")

    print("\n" + "="*80)


def main():
    """Run AMD YTD 2025 backtest analysis."""
    print("="*80)
    print("AMD OPTIONS WHEEL STRATEGY - 2025 YTD ANALYSIS")
    print("="*80)
    print()

    # Define backtest period: Jan 1, 2025 to today
    start_date = datetime(2025, 1, 1)
    end_date = datetime.now()

    print(f"Backtest Period: {start_date.date()} to {end_date.date()}")
    print(f"Symbol: AMD")
    print(f"Strategy: Options Wheel (Cash-Secured Puts + Covered Calls)")
    print()

    try:
        # Load configuration
        logger.info("Loading configuration")
        config = Config()

        # Create backtest configuration for AMD
        backtest_config = BacktestConfig(
            start_date=start_date,
            end_date=end_date,
            initial_capital=100000.0,
            symbols=['AMD'],
            commission_per_contract=1.00,
            slippage_bps=5
        )

        print("Running backtest (this may take several minutes)...")
        print("Fetching historical options data from Alpaca...")
        print()

        # Run backtest
        engine = BacktestEngine(config, backtest_config)
        result = engine.run_backtest()

        # Print main results
        print("\n" + "="*80)
        print("BACKTEST RESULTS SUMMARY")
        print("="*80)
        print(result.summary())

        # Create analyzer for detailed metrics
        analyzer = BacktestAnalyzer(result)

        # Generate detailed performance report
        print("\n" + "="*80)
        print("DETAILED PERFORMANCE ANALYSIS")
        print("="*80)
        detailed_report = analyzer.generate_performance_report()
        print(detailed_report)

        # Analyze open positions
        analyze_open_positions(result, engine)

        # Save results
        output_dir = project_root / 'backtest_results' / 'amd_ytd_2025'
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Save comprehensive report
        report_path = output_dir / f"amd_ytd_report_{timestamp}.txt"
        with open(report_path, 'w') as f:
            f.write("AMD OPTIONS WHEEL STRATEGY - 2025 YTD ANALYSIS\n")
            f.write("="*80 + "\n\n")
            f.write(f"Backtest Period: {start_date.date()} to {end_date.date()}\n")
            f.write(f"Symbol: AMD\n\n")
            f.write(result.summary())
            f.write("\n\n")
            f.write(detailed_report)

        print(f"\n✅ Full report saved to: {report_path}")

        # Export trade history to Excel
        excel_path = output_dir / f"amd_ytd_trades_{timestamp}.xlsx"
        if not result.trade_history.empty:
            with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                result.trade_history.to_excel(writer, sheet_name='Trades', index=False)
                result.portfolio_history.to_excel(writer, sheet_name='Portfolio', index=False)

            print(f"✅ Trade data exported to: {excel_path}")

        print("\n" + "="*80)
        print("ANALYSIS COMPLETE")
        print("="*80)

        return 0

    except Exception as e:
        import traceback
        logger.error("AMD YTD analysis failed", error=str(e))
        print(f"\n❌ ERROR: {str(e)}")
        print("\nFull traceback:")
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    import pandas as pd
    sys.exit(main())
