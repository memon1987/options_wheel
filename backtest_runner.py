#!/usr/bin/env python3
"""Main script to run wheel strategy backtests."""

import sys
import os
from datetime import datetime, timedelta
import argparse
import structlog

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.utils.config import Config
from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig
from src.backtesting.analysis import BacktestAnalyzer

logger = structlog.get_logger(__name__)


def main():
    """Main backtesting function."""
    parser = argparse.ArgumentParser(description='Options Wheel Strategy Backtesting')
    
    parser.add_argument('--start-date', type=str, required=True,
                       help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, required=True,
                       help='End date (YYYY-MM-DD)')
    parser.add_argument('--symbols', nargs='+', 
                       default=['AAPL', 'MSFT', 'GOOGL'],
                       help='Stock symbols to trade')
    parser.add_argument('--initial-capital', type=float, default=100000.0,
                       help='Initial capital amount')
    parser.add_argument('--commission', type=float, default=1.00,
                       help='Commission per options contract')
    parser.add_argument('--slippage-bps', type=int, default=5,
                       help='Slippage in basis points')
    
    # Strategy overrides
    parser.add_argument('--put-dte', type=int,
                       help='Override put target DTE')
    parser.add_argument('--call-dte', type=int,
                       help='Override call target DTE')
    parser.add_argument('--put-delta-min', type=float,
                       help='Override put delta minimum')
    parser.add_argument('--put-delta-max', type=float,
                       help='Override put delta maximum')
    parser.add_argument('--call-delta-min', type=float,
                       help='Override call delta minimum')
    parser.add_argument('--call-delta-max', type=float,
                       help='Override call delta maximum')
    
    # Output options
    parser.add_argument('--output-dir', type=str, default='backtest_results',
                       help='Output directory for results')
    parser.add_argument('--save-plots', action='store_true',
                       help='Save plot images')
    parser.add_argument('--export-data', action='store_true',
                       help='Export data to CSV/Excel')
    
    args = parser.parse_args()
    
    try:
        # Parse dates
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
        
        # Load configuration
        logger.info("Loading configuration")
        config = Config()
        
        # Create backtest configuration
        backtest_config = BacktestConfig(
            start_date=start_date,
            end_date=end_date,
            initial_capital=args.initial_capital,
            symbols=args.symbols,
            commission_per_contract=args.commission,
            slippage_bps=args.slippage_bps
        )
        
        # Apply strategy overrides
        if args.put_dte:
            backtest_config.put_target_dte = args.put_dte
        if args.call_dte:
            backtest_config.call_target_dte = args.call_dte
        if args.put_delta_min and args.put_delta_max:
            backtest_config.put_delta_range = [args.put_delta_min, args.put_delta_max]
        if args.call_delta_min and args.call_delta_max:
            backtest_config.call_delta_range = [args.call_delta_min, args.call_delta_max]
        
        # Create output directory
        os.makedirs(args.output_dir, exist_ok=True)
        
        # Run backtest
        logger.info("Starting backtest", 
                   start=start_date.date(),
                   end=end_date.date(),
                   symbols=args.symbols)
        
        engine = BacktestEngine(config, backtest_config)
        result = engine.run_backtest()
        
        # Print results
        print("\n" + "="*60)
        print("BACKTEST COMPLETED")
        print("="*60)
        print(result.summary())
        
        # Create analyzer
        analyzer = BacktestAnalyzer(result)
        
        # Generate detailed report
        detailed_report = analyzer.generate_performance_report()
        print(detailed_report)
        
        # Save results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_filename = f"wheel_backtest_{timestamp}"
        
        # Save text report
        report_path = os.path.join(args.output_dir, f"{base_filename}_report.txt")
        with open(report_path, 'w') as f:
            f.write(result.summary())
            f.write(detailed_report)
        print(f"\nReport saved to: {report_path}")
        
        # Save simple summary file
        summary_path = os.path.join(args.output_dir, f"{base_filename}_summary.txt")
        with open(summary_path, 'w') as f:
            f.write("OPTIONS WHEEL BACKTEST SUMMARY\n")
            f.write("=" * 35 + "\n\n")
            f.write(f"Period: {result.start_date.date()} to {result.end_date.date()}\n")
            f.write(f"Symbol(s): {', '.join(backtest_config.symbols)}\n")
            f.write(f"Initial Capital: ${result.initial_capital:,.2f}\n")
            f.write(f"Final Capital: ${result.final_capital:,.2f}\n\n")
            
            f.write("TRADING RESULTS\n")
            f.write("-" * 15 + "\n")
            f.write(f"Net Premium Generated: ${result.premium_collected:,.2f}\n")
            f.write(f"Total Trades Executed: {result.total_trades}\n")
            f.write(f"  • Put Trades: {result.put_trades}\n")
            f.write(f"  • Call Trades: {result.call_trades}\n")
            f.write(f"Assignments: {result.assignments}\n")
            f.write(f"Assignment Rate: {result.assignment_rate:.1%}\n")
            f.write(f"Win Rate: {result.win_rate:.1%}\n\n")
            
            f.write("AT-RISK CAPITAL\n")
            f.write("-" * 15 + "\n")
            f.write(f"Maximum At-Risk Capital: ${result.max_at_risk_capital:,.2f}\n")
            f.write(f"Average At-Risk Capital: ${result.avg_at_risk_capital:,.2f}\n")
            f.write(f"Peak At-Risk Percentage: {result.peak_at_risk_percentage:.1%}\n")
            f.write(f"Capital Efficiency: {(result.premium_collected / max(result.avg_at_risk_capital, 1)) * 100:.2f}%\n\n")
            
            f.write("PERFORMANCE\n")
            f.write("-" * 11 + "\n")
            f.write(f"Total Return: {result.total_return:.2%}\n")
            f.write(f"Annualized Return: {result.annualized_return:.2%}\n")
            f.write(f"Max Drawdown: {result.max_drawdown:.2%}\n")
            f.write(f"Sharpe Ratio: {result.sharpe_ratio:.2f}\n")
        
        print(f"Summary saved to: {summary_path}")
        
        # Export data if requested
        if args.export_data:
            excel_path = os.path.join(args.output_dir, f"{base_filename}.xlsx")
            analyzer.export_results(excel_path, format='excel')
            print(f"Data exported to: {excel_path}")
        
        # Generate and save plots if requested
        if args.save_plots:
            import matplotlib.pyplot as plt
            
            # Portfolio performance plot
            fig1 = analyzer.plot_portfolio_performance()
            plot1_path = os.path.join(args.output_dir, f"{base_filename}_performance.png")
            fig1.savefig(plot1_path, dpi=300, bbox_inches='tight')
            plt.close(fig1)
            print(f"Performance plot saved to: {plot1_path}")
            
            # Trade analysis plot
            fig2 = analyzer.plot_trade_analysis()
            plot2_path = os.path.join(args.output_dir, f"{base_filename}_trades.png")
            fig2.savefig(plot2_path, dpi=300, bbox_inches='tight')
            plt.close(fig2)
            print(f"Trade analysis plot saved to: {plot2_path}")
            
            # Wheel metrics plot
            fig3 = analyzer.plot_wheel_metrics()
            plot3_path = os.path.join(args.output_dir, f"{base_filename}_wheel.png")
            fig3.savefig(plot3_path, dpi=300, bbox_inches='tight')
            plt.close(fig3)
            print(f"Wheel metrics plot saved to: {plot3_path}")
        
        logger.info("Backtest completed successfully", 
                   total_return=result.total_return,
                   final_capital=result.final_capital)
        
        return 0
        
    except Exception as e:
        import traceback
        logger.error("Backtest failed", error=str(e))
        print(f"\nERROR: {str(e)}")
        print("\nFull traceback:")
        traceback.print_exc()
        return 1


def run_example_backtest():
    """Run an example backtest for demonstration."""
    print("🚀 Running Example Wheel Strategy Backtest")
    print("=" * 50)
    
    # Example parameters
    start_date = datetime(2023, 1, 1)
    end_date = datetime(2023, 6, 30)
    symbols = ['AAPL', 'MSFT']
    
    try:
        # Load configuration
        config = Config()
        
        # Create backtest configuration
        backtest_config = BacktestConfig(
            start_date=start_date,
            end_date=end_date,
            initial_capital=50000.0,  # Smaller amount for example
            symbols=symbols,
            commission_per_contract=1.00,
            slippage_bps=5,
            # Strategy overrides for more conservative approach
            put_target_dte=14,  # 14 days instead of 7
            call_target_dte=14,
            put_delta_range=[0.15, 0.25],  # Slightly wider range
            call_delta_range=[0.15, 0.25]
        )
        
        print(f"Backtest Period: {start_date.date()} to {end_date.date()}")
        print(f"Symbols: {symbols}")
        print(f"Initial Capital: ${backtest_config.initial_capital:,.2f}")
        print("\nRunning backtest...")
        
        # Run backtest
        engine = BacktestEngine(config, backtest_config)
        result = engine.run_backtest()
        
        print(result.summary())
        
        # Simple analysis
        analyzer = BacktestAnalyzer(result)
        
        print("\n" + "="*50)
        print("EXAMPLE BACKTEST COMPLETED")
        print("="*50)
        
        return result
        
    except Exception as e:
        print(f"Example backtest failed: {str(e)}")
        logger.error("Example backtest failed", error=str(e))
        return None


if __name__ == '__main__':
    # Check if running with arguments or as example
    if len(sys.argv) > 1:
        sys.exit(main())
    else:
        print("Running in example mode...")
        print("For full backtesting, use:")
        print("python backtest_runner.py --start-date 2023-01-01 --end-date 2023-12-31 --symbols AAPL MSFT")
        print("\nStarting example backtest...\n")
        run_example_backtest()