#!/usr/bin/env python3
"""Simple backtesting example to test the wheel strategy."""

import sys
import os
from datetime import datetime, timedelta

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.utils.config import Config
from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig
from src.backtesting.analysis import BacktestAnalyzer


def simple_backtest_example():
    """Run a simple backtest example."""
    print("🔬 Simple Wheel Strategy Backtest Example")
    print("=" * 50)
    
    try:
        # Load configuration
        config = Config()
        
        # Create a short backtest for testing
        backtest_config = BacktestConfig(
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 3, 31),  # 3 months
            initial_capital=50000.0,
            symbols=['AAPL'],  # Just one stock for simplicity
            commission_per_contract=1.00,
            slippage_bps=5,
            # Conservative parameters
            put_target_dte=14,
            call_target_dte=14,
            put_delta_range=[0.15, 0.25],
            call_delta_range=[0.15, 0.25]
        )
        
        print(f"Period: {backtest_config.start_date.date()} to {backtest_config.end_date.date()}")
        print(f"Symbol: {backtest_config.symbols[0]}")
        print(f"Initial Capital: ${backtest_config.initial_capital:,.2f}")
        print(f"Target DTE: {backtest_config.put_target_dte} days")
        print(f"Delta Range: {backtest_config.put_delta_range}")
        
        print("\n⚠️  NOTE: This is a simplified backtest example.")
        print("Real backtesting requires historical options data from Alpaca.")
        print("This example demonstrates the backtesting framework structure.\n")
        
        # Create and run backtest
        engine = BacktestEngine(config, backtest_config)
        
        print("🚀 Running backtest...")
        result = engine.run_backtest()
        
        print(result.summary())
        
        # Create analyzer for additional insights
        analyzer = BacktestAnalyzer(result)
        print(analyzer.generate_performance_report())
        
        return result
        
    except Exception as e:
        print(f"❌ Backtest failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def mock_data_example():
    """Example showing how the backtesting engine works with mock data."""
    print("\n🧪 Mock Data Backtesting Example")
    print("=" * 50)
    
    print("This example shows the backtesting components:")
    print("\n1. HISTORICAL DATA MANAGER")
    print("   - Fetches stock price history")
    print("   - Retrieves options chain data")
    print("   - Calculates Black-Scholes Greeks")
    
    print("\n2. BACKTEST ENGINE")
    print("   - Simulates day-by-day trading")
    print("   - Handles option expirations and assignments")
    print("   - Manages risk controls and position sizing")
    
    print("\n3. TRADE SIMULATOR")
    print("   - Applies realistic commissions and slippage")
    print("   - Handles option and stock transactions")
    print("   - Calculates break-even points")
    
    print("\n4. PORTFOLIO MANAGER")
    print("   - Tracks cash, stocks, and options positions")
    print("   - Calculates portfolio value and P&L")
    print("   - Monitors risk metrics")
    
    print("\n5. ANALYSIS ENGINE")
    print("   - Generates performance metrics")
    print("   - Creates visualization plots")
    print("   - Exports results to Excel/CSV")
    
    # Show example metrics that would be calculated
    print("\n📊 EXAMPLE METRICS CALCULATED:")
    metrics = {
        "Total Return": "15.2%",
        "Annualized Return": "8.4%",
        "Max Drawdown": "-3.1%",
        "Sharpe Ratio": "1.82",
        "Win Rate": "78%",
        "Total Trades": "42",
        "Put Assignments": "6",
        "Assignment Rate": "14.3%",
        "Premium Collected": "$3,240"
    }
    
    for metric, value in metrics.items():
        print(f"   {metric}: {value}")
    
    print("\n📈 AVAILABLE VISUALIZATIONS:")
    print("   - Portfolio value over time")
    print("   - Drawdown analysis")
    print("   - Trade distribution by type")
    print("   - Monthly returns heatmap")
    print("   - Assignment and expiration patterns")


def usage_examples():
    """Show usage examples for the backtesting engine."""
    print("\n💡 USAGE EXAMPLES")
    print("=" * 50)
    
    print("1. BASIC BACKTEST:")
    print("   python backtest_runner.py --start-date 2023-01-01 --end-date 2023-12-31 \\")
    print("     --symbols AAPL MSFT --initial-capital 100000")
    
    print("\n2. CUSTOM STRATEGY PARAMETERS:")
    print("   python backtest_runner.py --start-date 2023-01-01 --end-date 2023-12-31 \\")
    print("     --put-dte 7 --call-dte 7 --put-delta-min 0.10 --put-delta-max 0.20")
    
    print("\n3. EXPORT RESULTS:")
    print("   python backtest_runner.py --start-date 2023-01-01 --end-date 2023-12-31 \\")
    print("     --save-plots --export-data --output-dir results/")
    
    print("\n4. PYTHON API USAGE:")
    print("""
   from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig
   from src.utils.config import Config
   
   config = Config()
   backtest_config = BacktestConfig(
       start_date=datetime(2023, 1, 1),
       end_date=datetime(2023, 12, 31),
       symbols=['AAPL', 'MSFT'],
       initial_capital=100000
   )
   
   engine = BacktestEngine(config, backtest_config)
   result = engine.run_backtest()
   print(result.summary())
   """)


if __name__ == '__main__':
    print("🎯 Options Wheel Strategy Backtesting")
    print("=" * 60)
    
    # Run the examples
    simple_backtest_example()
    mock_data_example()
    usage_examples()
    
    print(f"\n✨ Backtesting engine ready!")
    print(f"📁 Core files created:")
    print(f"   - src/backtesting/backtest_engine.py")
    print(f"   - src/backtesting/historical_data.py")
    print(f"   - src/backtesting/portfolio.py")
    print(f"   - src/backtesting/trade_simulator.py")
    print(f"   - src/backtesting/analysis.py")
    print(f"   - backtest_runner.py (main script)")
    print(f"   - tests/test_backtest_engine.py")
    
    print(f"\n🚀 To run a real backtest with historical data:")
    print(f"   python backtest_runner.py --start-date 2024-01-01 --end-date 2024-06-30 --symbols AAPL")