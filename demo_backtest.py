#!/usr/bin/env python3
"""Simple backtesting demonstration without visualization dependencies."""

import sys
import os
from datetime import datetime, timedelta

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.utils.config import Config
from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig
from src.backtesting.portfolio import BacktestPortfolio
from src.backtesting.trade_simulator import TradeSimulator


def demo_portfolio_management():
    """Demonstrate portfolio management capabilities."""
    print("📊 PORTFOLIO MANAGEMENT DEMO")
    print("=" * 40)
    
    portfolio = BacktestPortfolio(100000.0)
    print(f"Initial Cash: ${portfolio.cash:,.2f}")
    
    # Add a stock position
    stock_position = {
        'symbol': 'AAPL',
        'quantity': 100,
        'entry_price': 150.0,
        'current_price': 155.0,
        'market_value': 15500.0,
        'cost_basis': 15000.0
    }
    
    portfolio.add_stock_position(stock_position)
    print(f"\nAdded stock position: 100 AAPL @ $150")
    print(f"Current value: ${portfolio.stock_value:,.2f}")
    
    # Add an option position (short put)
    option_position = {
        'symbol': 'AAPL_PUT_145_20240315',
        'underlying': 'AAPL',
        'type': 'PUT',
        'strike': 145.0,
        'quantity': -1,  # Short position
        'entry_price': 2.50,
        'current_price': 1.80,
        'market_value': -180.0  # Negative for short position
    }
    
    portfolio.add_option_position(option_position)
    print(f"\nAdded option position: Short 1 PUT @ $145 strike")
    print(f"Premium received: $250, Current value: $180")
    
    # Update cash for premium received
    portfolio.cash += 250 - 1  # Premium minus commission
    
    # Portfolio summary
    summary = portfolio.get_portfolio_summary()
    print(f"\n📈 PORTFOLIO SUMMARY:")
    print(f"Total Value: ${summary['total_value']:,.2f}")
    print(f"Cash: ${summary['cash']:,.2f}")
    print(f"Stock Value: ${summary['stock_value']:,.2f}")
    print(f"Option Value: ${summary['option_value']:,.2f}")
    print(f"Total Return: {summary['total_return']:.2%}")


def demo_trade_simulator():
    """Demonstrate trade simulation with costs."""
    print("\n💰 TRADE SIMULATOR DEMO")
    print("=" * 40)
    
    simulator = TradeSimulator(
        commission_per_contract=1.00,
        slippage_bps=5
    )
    
    # Simulate selling a put option
    put_trade = simulator.simulate_option_trade(
        action='sell',
        contracts=1,
        price=2.50,
        option_type='PUT'
    )
    
    print(f"PUT SALE SIMULATION:")
    print(f"  Base Value: ${put_trade['base_value']:,.2f}")
    print(f"  Commission: ${put_trade['commission']:,.2f}")
    print(f"  Slippage: ${put_trade['slippage']:,.2f}")
    print(f"  Net Proceeds: ${put_trade['net_proceeds']:,.2f}")
    print(f"  Effective Price: ${put_trade['effective_price']:.2f}")
    
    # Simulate assignment
    assignment = simulator.simulate_assignment(
        option_type='PUT',
        contracts=1,
        strike=145.0
    )
    
    print(f"\nPUT ASSIGNMENT SIMULATION:")
    print(f"  Shares Assigned: {assignment['shares']}")
    print(f"  Strike Price: ${assignment['strike']:.2f}")
    print(f"  Base Value: ${assignment['base_value']:,.2f}")
    print(f"  Commission: ${assignment['commission']:,.2f}")
    print(f"  Net Cash Flow: ${assignment['net_cash_flow']:,.2f}")
    
    # Calculate break-even
    breakeven = simulator.calculate_break_even('PUT', 145.0, 2.50)
    print(f"  Break-even Price: ${breakeven:.2f}")


def demo_backtest_config():
    """Demonstrate backtest configuration options."""
    print("\n⚙️  BACKTEST CONFIGURATION DEMO")
    print("=" * 40)
    
    # Basic configuration
    basic_config = BacktestConfig(
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 6, 30),
        initial_capital=100000.0,
        symbols=['AAPL', 'MSFT', 'GOOGL']
    )
    
    print("BASIC CONFIGURATION:")
    print(f"  Period: {basic_config.start_date.date()} to {basic_config.end_date.date()}")
    print(f"  Capital: ${basic_config.initial_capital:,.2f}")
    print(f"  Symbols: {basic_config.symbols}")
    print(f"  Commission: ${basic_config.commission_per_contract:.2f}/contract")
    print(f"  Slippage: {basic_config.slippage_bps} bps")
    
    # Advanced configuration with overrides
    advanced_config = BacktestConfig(
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 6, 30),
        initial_capital=50000.0,
        symbols=['AAPL'],
        commission_per_contract=0.50,  # Lower commission
        slippage_bps=3,  # Lower slippage
        # Strategy overrides
        put_target_dte=7,
        call_target_dte=7,
        put_delta_range=[0.10, 0.20],
        call_delta_range=[0.10, 0.20]
    )
    
    print(f"\nADVANCED CONFIGURATION:")
    print(f"  Period: {advanced_config.start_date.date()} to {advanced_config.end_date.date()}")
    print(f"  Capital: ${advanced_config.initial_capital:,.2f}")
    print(f"  Symbols: {advanced_config.symbols}")
    print(f"  Commission: ${advanced_config.commission_per_contract:.2f}/contract")
    print(f"  Slippage: {advanced_config.slippage_bps} bps")
    print(f"  Put DTE: {advanced_config.put_target_dte} days")
    print(f"  Put Delta: {advanced_config.put_delta_range}")


def demo_wheel_strategy_logic():
    """Demonstrate the wheel strategy logic."""
    print("\n🎯 WHEEL STRATEGY LOGIC DEMO")
    print("=" * 40)
    
    print("THE WHEEL STRATEGY CYCLE:")
    print("\n1️⃣  PHASE 1: SELL CASH-SECURED PUTS")
    print("   • Target: 7 days to expiration")
    print("   • Delta: 0.10-0.20 (10-20% assignment probability)")
    print("   • Goal: Collect premium, avoid assignment")
    print("   • Capital Required: Strike price × 100 per contract")
    
    print("\n2️⃣  PHASE 2A: PUT EXPIRES WORTHLESS (80-90% of time)")
    print("   • Keep the full premium")
    print("   • Return to Phase 1 with new put")
    print("   • This is the ideal outcome")
    
    print("\n2️⃣  PHASE 2B: PUT GETS ASSIGNED (10-20% of time)")
    print("   • Receive 100 shares at strike price")
    print("   • Still keep the premium from selling the put")
    print("   • Move to Phase 3")
    
    print("\n3️⃣  PHASE 3: SELL COVERED CALLS")
    print("   • Target: 7 days to expiration") 
    print("   • Delta: 0.10-0.20 (similar to puts)")
    print("   • Strike: Above current stock price")
    print("   • Goal: Collect premium, potentially get called away")
    
    print("\n4️⃣  PHASE 4A: CALL EXPIRES WORTHLESS")
    print("   • Keep the premium")
    print("   • Still own the stock")
    print("   • Return to Phase 3 with new call")
    
    print("\n4️⃣  PHASE 4B: CALL GETS ASSIGNED")
    print("   • Stock gets called away at strike price")
    print("   • Keep the call premium")
    print("   • Calculate total profit/loss")
    print("   • Return to Phase 1 to start over")
    
    print("\n💡 KEY ADVANTAGES:")
    print("   • Generate income in sideways/slightly bearish markets")
    print("   • No stop losses on puts (we want to own quality stocks)")
    print("   • Conservative delta selection (low assignment probability)")
    print("   • Short-term expirations (rapid time decay)")
    
    print("\n⚠️  RISKS TO MANAGE:")
    print("   • Unlimited downside if stock crashes after assignment")
    print("   • Opportunity cost if stock rallies significantly")
    print("   • Early assignment risk (especially near ex-dividend dates)")
    print("   • Requires significant capital for cash-secured puts")


def main():
    """Run all demonstrations."""
    print("🎮 OPTIONS WHEEL BACKTESTING ENGINE DEMO")
    print("=" * 60)
    
    print("This demonstration shows the core components of the backtesting engine:")
    print("• Portfolio management and position tracking")
    print("• Trade simulation with realistic costs")  
    print("• Configuration options for different strategies")
    print("• Complete wheel strategy cycle explanation")
    
    demo_portfolio_management()
    demo_trade_simulator() 
    demo_backtest_config()
    demo_wheel_strategy_logic()
    
    print("\n" + "=" * 60)
    print("✅ BACKTESTING ENGINE READY!")
    print("=" * 60)
    
    print("\n📁 CREATED FILES:")
    files = [
        "src/backtesting/backtest_engine.py - Main backtesting engine",
        "src/backtesting/historical_data.py - Historical data management", 
        "src/backtesting/portfolio.py - Portfolio tracking and management",
        "src/backtesting/trade_simulator.py - Trade execution simulation",
        "src/backtesting/analysis.py - Results analysis and visualization",
        "backtest_runner.py - Command-line backtesting script",
        "tests/test_backtest_engine.py - Comprehensive test suite"
    ]
    
    for file_desc in files:
        print(f"   ✓ {file_desc}")
    
    print("\n🚀 NEXT STEPS:")
    print("1. Install visualization dependencies:")
    print("   pip install matplotlib seaborn openpyxl")
    
    print("\n2. Run a real backtest with historical data:")
    print("   python backtest_runner.py --start-date 2024-01-01 --end-date 2024-06-30 \\")
    print("     --symbols AAPL --initial-capital 50000 --save-plots --export-data")
    
    print("\n3. Test different strategy parameters:")
    print("   python backtest_runner.py --start-date 2024-01-01 --end-date 2024-06-30 \\") 
    print("     --put-dte 14 --call-dte 14 --put-delta-min 0.15 --put-delta-max 0.25")
    
    print("\n4. Run unit tests:")
    print("   python -m pytest tests/test_backtest_engine.py -v")
    
    print(f"\n🎯 The backtesting engine is fully functional and ready to test")
    print(f"   wheel strategies with historical market data from Alpaca!")


if __name__ == '__main__':
    main()