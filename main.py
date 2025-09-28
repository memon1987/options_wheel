"""Main entry point for Options Wheel Strategy."""

import argparse
import sys
from datetime import datetime
import json

from src.utils.config import Config
from src.utils.logger import setup_logging, get_logger
from src.strategy.wheel_engine import WheelEngine
from src.data.options_scanner import OptionsScanner
from src.data.portfolio_tracker import PortfolioTracker
from src.api.alpaca_client import AlpacaClient
from src.api.market_data import MarketDataManager


def main():
    """Main application entry point."""
    parser = argparse.ArgumentParser(description='Options Wheel Strategy')
    parser.add_argument('--config', default='config/settings.yaml', help='Configuration file path')
    parser.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Logging level')
    parser.add_argument('--command', required=True, 
                       choices=['run', 'scan', 'status', 'report'], 
                       help='Command to execute')
    parser.add_argument('--dry-run', action='store_true', help='Run without executing trades')
    
    args = parser.parse_args()
    
    try:
        # Load configuration
        config = Config(args.config)
        
        # Setup logging
        setup_logging(args.log_level)
        logger = get_logger(__name__)
        
        logger.info("Starting Options Wheel Strategy", 
                   command=args.command, 
                   config_file=args.config,
                   dry_run=args.dry_run)
        
        # Initialize components
        alpaca_client = AlpacaClient(config)
        market_data = MarketDataManager(alpaca_client, config)
        portfolio_tracker = PortfolioTracker(alpaca_client, config)
        scanner = OptionsScanner(alpaca_client, market_data, config)
        
        # Execute command
        if args.command == 'run':
            run_strategy(config, args.dry_run, logger)
        elif args.command == 'scan':
            scan_opportunities(scanner, logger)
        elif args.command == 'status':
            show_status(portfolio_tracker, logger)
        elif args.command == 'report':
            generate_report(portfolio_tracker, logger)
        
        logger.info("Command completed successfully")
        
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error("Application failed", error=str(e))
        sys.exit(1)


def run_strategy(config: Config, dry_run: bool, logger):
    """Run the wheel strategy."""
    logger.info("Initializing wheel strategy engine", dry_run=dry_run)
    
    if dry_run:
        logger.warning("DRY RUN MODE - No trades will be executed")
    
    wheel_engine = WheelEngine(config)
    
    try:
        # Run one strategy cycle
        cycle_result = wheel_engine.run_strategy_cycle()
        
        logger.info("Strategy cycle completed",
                   actions_taken=len(cycle_result['actions']),
                   new_positions=cycle_result.get('new_positions', 0),
                   closed_positions=cycle_result.get('closed_positions', 0))
        
        # Print summary
        print("\n" + "="*60)
        print("STRATEGY CYCLE SUMMARY")
        print("="*60)
        print(f"Timestamp: {cycle_result['timestamp']}")
        print(f"Positions Analyzed: {cycle_result['positions_analyzed']}")
        print(f"Actions Taken: {len(cycle_result['actions'])}")
        print(f"New Positions: {cycle_result.get('new_positions', 0)}")
        print(f"Closed Positions: {cycle_result.get('closed_positions', 0)}")
        
        if cycle_result['actions']:
            print("\nActions:")
            for i, action in enumerate(cycle_result['actions'], 1):
                print(f"  {i}. {action.get('strategy', 'N/A')} - {action.get('symbol', 'N/A')}")
        
        if cycle_result['errors']:
            print("\nErrors:")
            for error in cycle_result['errors']:
                print(f"  - {error}")
        
        # Account summary
        account = cycle_result.get('account_info', {})
        if account:
            print(f"\nAccount Summary:")
            print(f"  Portfolio Value: ${account.get('portfolio_value', 0):,.2f}")
            print(f"  Cash: ${account.get('cash', 0):,.2f}")
            print(f"  Buying Power: ${account.get('buying_power', 0):,.2f}")
        
    except Exception as e:
        logger.error("Strategy execution failed", error=str(e))
        print(f"\nStrategy execution failed: {str(e)}")


def scan_opportunities(scanner: OptionsScanner, logger):
    """Scan for trading opportunities."""
    logger.info("Scanning for trading opportunities")
    
    try:
        # Get market overview
        market_overview = scanner.get_market_overview()
        
        # Scan for opportunities
        opportunities = scanner.scan_all_opportunities()
        
        # Print results
        print("\n" + "="*60)
        print("OPTIONS OPPORTUNITIES SCAN")
        print("="*60)
        print(f"Scan Time: {opportunities['scan_timestamp']}")
        print(f"Total Opportunities: {opportunities['total_opportunities']}")
        
        # Market overview
        print(f"\nMarket Overview:")
        print(f"  Configured Stocks: {market_overview.get('configured_stocks', 0)}")
        print(f"  Suitable Stocks: {market_overview.get('suitable_stocks', 0)}")
        print(f"  Market Conditions: {market_overview.get('market_conditions', 'unknown')}")
        
        # Put opportunities
        puts = opportunities.get('puts', [])
        if puts:
            print(f"\nTop Put Opportunities ({len(puts)}):")
            print("  Rank | Symbol | Strike | Premium | DTE | Annual Return | Score")
            print("  -----|--------|--------|---------|-----|---------------|------")
            for i, put in enumerate(puts[:10], 1):
                print(f"  {i:2d}   | {put['symbol']:6s} | ${put['strike_price']:6.0f} | "
                     f"${put['premium']:5.2f}  | {put['dte']:3d} | "
                     f"{put['annual_return_percent']:8.1f}%   | {put['attractiveness_score']:5.1f}")
        
        # Call opportunities
        calls = opportunities.get('calls', [])
        if calls:
            print(f"\nTop Call Opportunities ({len(calls)}):")
            print("  Rank | Symbol | Strike | Premium | DTE | Annual Return | Score")
            print("  -----|--------|--------|---------|-----|---------------|------")
            for i, call in enumerate(calls[:10], 1):
                print(f"  {i:2d}   | {call['symbol']:6s} | ${call['strike_price']:6.0f} | "
                     f"${call['premium']:5.2f}  | {call['dte']:3d} | "
                     f"{call['annual_premium_return_percent']:8.1f}%   | {call['attractiveness_score']:5.1f}")
        
        if not puts and not calls:
            print("\nNo suitable opportunities found at this time.")
        
    except Exception as e:
        logger.error("Opportunity scan failed", error=str(e))
        print(f"\nOpportunity scan failed: {str(e)}")


def show_status(tracker: PortfolioTracker, logger):
    """Show current portfolio status."""
    logger.info("Getting portfolio status")
    
    try:
        snapshot = tracker.get_current_portfolio_snapshot()
        
        print("\n" + "="*60)
        print("PORTFOLIO STATUS")
        print("="*60)
        print(f"Snapshot Time: {snapshot['timestamp']}")
        
        # Account info
        account = snapshot.get('account', {})
        print(f"\nAccount:")
        print(f"  Portfolio Value: ${account.get('portfolio_value', 0):,.2f}")
        print(f"  Cash: ${account.get('cash', 0):,.2f} ({account.get('cash', 0)/account.get('portfolio_value', 1)*100:.1f}%)")
        print(f"  Buying Power: ${account.get('buying_power', 0):,.2f}")
        print(f"  Equity: ${account.get('equity', 0):,.2f}")
        
        # Positions
        positions = snapshot.get('positions', {})
        print(f"\nPositions:")
        print(f"  Total Positions: {positions.get('total_count', 0)}")
        print(f"  Stock Positions: {positions.get('stock_positions', 0)}")
        print(f"  Option Positions: {positions.get('option_positions', 0)}")
        print(f"  Total Value: ${positions.get('total_value', 0):,.2f}")
        
        # Performance
        performance = snapshot.get('performance', {})
        total_pl = performance.get('total_unrealized_pl', 0)
        pl_percent = performance.get('unrealized_pl_percent', 0)
        print(f"\nPerformance:")
        print(f"  Unrealized P&L: ${total_pl:,.2f} ({pl_percent:+.2f}%)")
        
        # Wheel metrics
        wheel_metrics = snapshot.get('wheel_metrics', {})
        print(f"\nWheel Strategy:")
        print(f"  Active Wheels: {wheel_metrics.get('active_wheels', 0)}")
        print(f"  Cash Secured Puts: {wheel_metrics.get('cash_secured_puts', 0)}")
        print(f"  Assigned Stocks: {wheel_metrics.get('assigned_stocks', 0)}")
        print(f"  Covered Calls: {wheel_metrics.get('covered_calls', 0)}")
        
        # Underlying positions
        underlying = snapshot.get('underlying_positions', {})
        if underlying:
            print(f"\nPositions by Underlying:")
            for symbol, data in underlying.items():
                stage = data.get('wheel_stage', 'unknown')
                value = data.get('total_value', 0)
                pl = data.get('total_pl', 0)
                print(f"  {symbol}: {stage} (${value:,.0f}, P&L: ${pl:+,.0f})")
        
    except Exception as e:
        logger.error("Status retrieval failed", error=str(e))
        print(f"\nStatus retrieval failed: {str(e)}")


def generate_report(tracker: PortfolioTracker, logger):
    """Generate comprehensive performance report."""
    logger.info("Generating performance report")
    
    try:
        report = tracker.generate_performance_report()
        
        print("\n" + "="*60)
        print("PERFORMANCE REPORT")
        print("="*60)
        print(f"Report Date: {report['report_date']}")
        
        # Current portfolio summary
        current = report.get('current_portfolio', {})
        account = current.get('account', {})
        print(f"\nCurrent Portfolio:")
        print(f"  Value: ${account.get('portfolio_value', 0):,.2f}")
        print(f"  Cash: ${account.get('cash', 0):,.2f}")
        
        # 30-day performance
        perf_30d = report.get('performance_30d', {})
        if 'error' not in perf_30d:
            print(f"\n30-Day Performance:")
            print(f"  Total Return: ${perf_30d.get('total_return', 0):,.2f} ({perf_30d.get('total_return_percent', 0):+.2f}%)")
            print(f"  Annualized Return: {perf_30d.get('annualized_return_percent', 0):+.2f}%")
            print(f"  Volatility: {perf_30d.get('volatility_percent', 0):.2f}%")
            print(f"  Sharpe Ratio: {perf_30d.get('sharpe_ratio', 0):.2f}")
            print(f"  Max Drawdown: {perf_30d.get('max_drawdown_percent', 0):.2f}%")
        else:
            print(f"\n30-Day Performance: {perf_30d['error']}")
        
        # Risk summary
        risk_summary = report.get('risk_summary', {})
        print(f"\nRisk Summary:")
        print(f"  Cash Percentage: {risk_summary.get('cash_percentage', 0):.1f}%")
        print(f"  Max Concentration: {risk_summary.get('max_concentration', 0):.1f}% ({risk_summary.get('max_concentration_symbol', 'N/A')})")
        print(f"  Total Positions: {risk_summary.get('total_positions', 0)}")
        print(f"  Risk Level: {risk_summary.get('risk_level', 'Unknown')}")
        
        # Recent activity
        activity = report.get('recent_activity', {})
        print(f"\nRecent Activity:")
        print(f"  Recent Trades: {activity.get('total_trades', 0)}")
        
        # Recommendations
        recommendations = report.get('recommendations', [])
        if recommendations:
            print(f"\nRecommendations:")
            for i, rec in enumerate(recommendations, 1):
                print(f"  {i}. {rec}")
        
        # Export option
        print(f"\nExporting detailed data...")
        filename = tracker.export_performance_data()
        if filename:
            print(f"Data exported to: {filename}")
        
    except Exception as e:
        logger.error("Report generation failed", error=str(e))
        print(f"\nReport generation failed: {str(e)}")


if __name__ == '__main__':
    main()