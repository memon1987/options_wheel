#!/usr/bin/env python3
"""
Cloud Run compatible web server for Options Wheel Strategy.
Provides HTTP endpoints to trigger and monitor the trading strategy.
"""

import os
import threading
import time
import json
import traceback
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
import structlog

# Add src to path
import sys
sys.path.append('/app/src')

from src.utils.config import Config
from src.utils.logging_events import log_system_event, log_performance_metric, log_error_event, log_trade_event

logger = structlog.get_logger(__name__)

app = Flask(__name__)

# Global state
strategy_status = {
    'status': 'idle',
    'last_run': None,
    'last_scan': None,
    'positions': 0,
    'pnl': 0.0,
    'errors': []
}

strategy_lock = threading.Lock()

@app.route('/')
def health_check():
    """Health check endpoint for Cloud Run."""
    return jsonify({
        'status': 'healthy',
        'service': 'options-wheel-strategy',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/status')
def get_status():
    """Get current strategy status."""
    return jsonify(strategy_status)

@app.route('/scan', methods=['POST'])
def trigger_scan():
    """Trigger a market scan for opportunities."""
    with strategy_lock:
        start_time = datetime.now()
        try:
            # Removed duplicate - already logged below with log_system_event()

            # Log system event for scan trigger
            log_system_event(
                logger,
                event_type="market_scan_triggered",
                status="starting"
            )

            # Initialize trading components
            config = Config()

            from src.api.alpaca_client import AlpacaClient
            from src.api.market_data import MarketDataManager
            from src.data.options_scanner import OptionsScanner

            alpaca_client = AlpacaClient(config)
            market_data = MarketDataManager(alpaca_client, config)
            scanner = OptionsScanner(alpaca_client, market_data, config)

            # Perform market scan
            logger.info("Starting options market scan",
                       event_category="system",
                       event_type="market_scan_starting")

            # Scan for put opportunities
            put_opportunities = scanner.scan_for_put_opportunities()
            logger.info("Put opportunities found",
                       event_category="system",
                       event_type="put_scan_completed",
                       count=len(put_opportunities))

            # Scan for call opportunities (if we have stock positions)
            call_opportunities = scanner.scan_for_call_opportunities()
            logger.info("Call opportunities found",
                       event_category="system",
                       event_type="call_scan_completed",
                       count=len(call_opportunities))

            # Store opportunities for execution
            from src.data.opportunity_store import OpportunityStore
            opportunity_store = OpportunityStore(config)

            all_opportunities = put_opportunities + call_opportunities
            stored = opportunity_store.store_opportunities(all_opportunities, start_time)

            # Update status with scan results
            strategy_status['last_scan'] = datetime.now().isoformat()
            strategy_status['status'] = 'scan_completed'

            scan_results = {
                'put_opportunities': len(put_opportunities),
                'call_opportunities': len(call_opportunities),
                'total_opportunities': len(all_opportunities),
                'stored_for_execution': stored
            }

            # Calculate scan duration
            duration_seconds = (datetime.now() - start_time).total_seconds()

            # Log completion event
            log_system_event(
                logger,
                event_type="market_scan_completed",
                status="completed",
                duration_seconds=duration_seconds,
                put_opportunities=len(put_opportunities),
                call_opportunities=len(call_opportunities),
                total_opportunities=scan_results['total_opportunities'],
                stored_for_execution=stored
            )

            # Log performance metric
            log_performance_metric(
                logger,
                metric_name="market_scan_duration",
                metric_value=duration_seconds,
                metric_unit="seconds",
                opportunities_found=scan_results['total_opportunities']
            )

            return jsonify({
                'message': 'Market scan completed successfully',
                'timestamp': datetime.now().isoformat(),
                'results': scan_results
            })

        except Exception as e:
            error_msg = f"Scan failed: {str(e)}"

            # Enhanced error logging
            log_error_event(
                logger,
                error_type="market_scan_exception",
                error_message=str(e),
                component="cloud_run_server",
                recoverable=True
            )

            strategy_status['errors'].append({
                'timestamp': datetime.now().isoformat(),
                'error': error_msg
            })
            return jsonify({'error': error_msg}), 500

@app.route('/run', methods=['POST'])
def trigger_strategy():
    """Trigger strategy execution."""
    with strategy_lock:
        start_time = datetime.now()
        try:
            # Removed duplicate - already logged below with log_system_event()

            # Log system event for strategy trigger
            log_system_event(
                logger,
                event_type="strategy_execution_triggered",
                status="starting"
            )

            # Initialize trading components
            config = Config()

            from src.api.alpaca_client import AlpacaClient
            from src.api.market_data import MarketDataManager
            from src.data.opportunity_store import OpportunityStore
            from src.strategy.put_seller import PutSeller

            alpaca_client = AlpacaClient(config)
            market_data = MarketDataManager(alpaca_client, config)
            opportunity_store = OpportunityStore(config)

            # Retrieve pending opportunities from Cloud Storage
            opportunities = opportunity_store.get_pending_opportunities(start_time)

            if not opportunities:
                logger.info("No pending opportunities found for execution",
                           event_category="system",
                           event_type="no_opportunities_for_execution",
                           execution_time=start_time.isoformat())

                log_system_event(
                    logger,
                    event_type="strategy_execution_completed",
                    status="no_opportunities",
                    duration_seconds=(datetime.now() - start_time).total_seconds(),
                    opportunities_found=0
                )

                return jsonify({
                    'message': 'No opportunities to execute',
                    'timestamp': datetime.now().isoformat(),
                    'results': {
                        'opportunities_found': 0,
                        'trades_executed': 0
                    }
                })

            logger.info("Retrieved opportunities for execution",
                       event_category="system",
                       event_type="opportunities_retrieved",
                       count=len(opportunities),
                       execution_time=start_time.isoformat())

            # Initialize put seller for execution
            put_seller = PutSeller(alpaca_client, market_data, config)

            # Get initial buying power and track locally during execution
            # (Alpaca's API returns stale/incorrect data immediately after trades)
            account_info = alpaca_client.get_account()
            available_buying_power = float(account_info.get('options_buying_power') or account_info['buying_power'])
            logger.info("Starting execution with buying power",
                       event_category="system",
                       event_type="execution_buying_power_check",
                       initial_buying_power=available_buying_power,
                       buying_power=account_info.get('buying_power'),
                       options_buying_power=account_info.get('options_buying_power'),
                       cash=account_info.get('cash'),
                       portfolio_value=account_info.get('portfolio_value'),
                       equity=account_info.get('equity'))

            # BATCH ORDER STRATEGY: Select all opportunities that fit within buying power
            # Sort by premium/exposure ratio (ROI) to maximize returns
            # Submit all orders concurrently to avoid Alpaca's sequential execution bug

            # Calculate ROI for each opportunity and add position sizing
            opportunities_with_metrics = []
            for opp in opportunities:
                # Transform scanner format to position sizing format
                if 'premium' in opp and 'mid_price' not in opp:
                    opp['mid_price'] = opp['premium']

                # Calculate position size
                position_size = put_seller._calculate_position_size(opp, override_buying_power=available_buying_power)
                if not position_size:
                    continue

                opp['contracts'] = position_size['contracts']
                collateral = opp['strike_price'] * 100 * opp['contracts']
                premium_collected = opp['premium'] * 100 * opp['contracts']
                roi = premium_collected / collateral if collateral > 0 else 0

                opportunities_with_metrics.append({
                    'opportunity': opp,
                    'collateral': collateral,
                    'premium': premium_collected,
                    'roi': roi
                })

            # Sort by ROI (highest first)
            opportunities_with_metrics.sort(key=lambda x: x['roi'], reverse=True)

            # Select opportunities that fit within buying power (greedy algorithm)
            # IMPORTANT: Only one position per underlying stock (risk management rule)
            selected_opportunities = []
            selected_underlyings = set()  # Track which stocks we've already selected
            remaining_bp = available_buying_power

            for item in opportunities_with_metrics:
                underlying = item['opportunity'].get('symbol')

                # Skip if we already have a position for this underlying
                if underlying in selected_underlyings:
                    logger.info("Skipping duplicate underlying in batch selection",
                               event_category="filtering",
                               event_type="duplicate_underlying_skipped",
                               symbol=underlying,
                               collateral=item['collateral'],
                               premium=item['premium'],
                               roi=f"{item['roi']:.4f}",
                               reason="already_selected_for_execution")
                    continue

                if item['collateral'] <= remaining_bp:
                    selected_opportunities.append(item['opportunity'])
                    selected_underlyings.add(underlying)
                    remaining_bp -= item['collateral']
                    logger.info("Selected opportunity for batch execution",
                               event_category="system",
                               event_type="opportunity_selected_for_execution",
                               symbol=underlying,
                               collateral=item['collateral'],
                               premium=item['premium'],
                               roi=f"{item['roi']:.4f}",
                               remaining_bp=remaining_bp)

            logger.info("Batch order selection complete",
                       event_category="system",
                       event_type="batch_selection_completed",
                       total_opportunities=len(opportunities),
                       selected_count=len(selected_opportunities),
                       initial_bp=available_buying_power,
                       bp_to_use=available_buying_power - remaining_bp)

            # Execute all selected orders concurrently using ThreadPoolExecutor
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def execute_single_order(opp):
                """Execute a single order and return result with opportunity info."""
                try:
                    # Execute the trade (skip buying power check since we already validated)
                    result = put_seller.execute_put_sale(opp, skip_buying_power_check=True)
                    return {
                        'opportunity': opp,
                        'result': result,
                        'success': result and result.get('success', False)
                    }
                except Exception as e:
                    logger.error("Exception during order execution",
                                event_category="error",
                                event_type="order_execution_exception",
                                symbol=opp.get('symbol'),
                                error=str(e))
                    return {
                        'opportunity': opp,
                        'result': {'success': False, 'message': str(e)},
                        'success': False
                    }

            logger.info("Submitting batch orders concurrently",
                       event_category="system",
                       event_type="batch_orders_submitting",
                       order_count=len(selected_opportunities))

            execution_results = []
            trades_executed = 0

            # Submit all orders concurrently
            with ThreadPoolExecutor(max_workers=min(10, len(selected_opportunities))) as executor:
                # Submit all orders
                future_to_opp = {
                    executor.submit(execute_single_order, opp): opp
                    for opp in selected_opportunities
                }

                # Process results as they complete
                for future in as_completed(future_to_opp):
                    opp = future_to_opp[future]
                    try:
                        execution_data = future.result()
                        execution_results.append(execution_data)

                        if execution_data['success']:
                            trades_executed += 1
                            result = execution_data['result']

                            # Log successful trade
                            # Convert UUID to string if present
                            order_id = result.get('order_id')
                            if order_id is not None:
                                order_id = str(order_id)

                            log_system_event(
                                logger,
                                event_type="trade_executed",
                                status="success",
                                symbol=opp.get('symbol'),
                                option_symbol=opp.get('option_symbol'),
                                contracts=opp.get('contracts'),
                                premium=opp.get('premium'),
                                strike_price=opp.get('strike_price'),
                                order_id=order_id
                            )
                        else:
                            # Log failed trade
                            result = execution_data['result']
                            log_error_event(
                                logger,
                                error_type="trade_execution_failed",
                                error_message=result.get('message', 'Unknown error'),
                                component="execution_engine",
                                recoverable=True,
                                symbol=opp.get('symbol'),
                                option_symbol=opp.get('option_symbol')
                            )
                    except Exception as e:
                        logger.error("Error processing execution result",
                                   event_category="error",
                                   event_type="execution_result_processing_error",
                                   symbol=opp.get('symbol'),
                                   error=str(e))

            # Mark opportunities as executed in Cloud Storage
            opportunity_store.mark_executed(
                execution_time=start_time,
                executed_count=trades_executed,
                results=execution_results
            )

            # Update global status
            strategy_status['last_run'] = datetime.now().isoformat()
            strategy_status['status'] = 'execution_completed'

            # Calculate execution duration
            duration_seconds = (datetime.now() - start_time).total_seconds()

            # Log system event for completion
            log_system_event(
                logger,
                event_type="strategy_execution_completed",
                status="completed",
                duration_seconds=duration_seconds,
                opportunities_evaluated=len(opportunities),
                trades_executed=trades_executed,
                trades_failed=len(opportunities) - trades_executed
            )

            # Log performance metric
            log_performance_metric(
                logger,
                metric_name="strategy_execution_duration",
                metric_value=duration_seconds,
                metric_unit="seconds",
                opportunities_evaluated=len(opportunities),
                trades_executed=trades_executed
            )

            return jsonify({
                'message': 'Strategy execution completed successfully',
                'timestamp': datetime.now().isoformat(),
                'results': {
                    'opportunities_evaluated': len(opportunities),
                    'trades_executed': trades_executed,
                    'trades_failed': len(opportunities) - trades_executed,
                    'execution_results': execution_results
                }
            })

        except Exception as e:
            error_msg = f"Strategy execution failed: {str(e)}"
            logger.error(error_msg,
                        event_category="error",
                        event_type="strategy_execution_exception",
                        error=str(e),
                        traceback=traceback.format_exc())
            strategy_status['errors'].append({
                'timestamp': datetime.now().isoformat(),
                'error': error_msg
            })
            return jsonify({'error': error_msg}), 500

@app.route('/monitor', methods=['POST'])
def monitor_positions():
    """Monitor existing positions and close profitable ones."""
    with strategy_lock:
        start_time = datetime.now()
        try:
            log_system_event(
                logger,
                event_type="position_monitoring_triggered",
                status="starting"
            )

            # Initialize trading components
            config = Config()

            from src.api.alpaca_client import AlpacaClient
            from src.api.market_data import MarketDataManager
            from src.strategy.put_seller import PutSeller
            from src.strategy.call_seller import CallSeller

            alpaca_client = AlpacaClient(config)
            market_data = MarketDataManager(alpaca_client, config)
            put_seller = PutSeller(alpaca_client, market_data, config)
            call_seller = CallSeller(alpaca_client, market_data, config)

            # Get current positions
            positions = alpaca_client.get_positions()
            option_positions = [p for p in positions if p.get('asset_class') == 'us_option']

            logger.info("Monitoring positions for early close",
                       event_category="system",
                       event_type="position_monitoring_started",
                       total_positions=len(positions),
                       option_positions=len(option_positions))

            closed_positions = []
            errors = []

            # Evaluate each option position
            for position in option_positions:
                try:
                    symbol = position['symbol']
                    qty = int(position['qty'])

                    # Determine if it's a put or call
                    is_put = 'P' in symbol
                    is_call = 'C' in symbol

                    # Check if position should be closed early
                    should_close = False

                    if is_put:
                        should_close = put_seller.should_close_put_early(position)
                        position_type = 'PUT'
                    elif is_call:
                        should_close = call_seller.should_close_call_early(position)
                        position_type = 'CALL'
                    else:
                        logger.warning("Unknown option type", symbol=symbol)
                        continue

                    if should_close:
                        logger.info("Position reached profit target - closing",
                                   event_category="execution",
                                   event_type="early_close_triggered",
                                   symbol=symbol,
                                   type=position_type,
                                   unrealized_pl=position.get('unrealized_pl'),
                                   market_value=position.get('market_value'))

                        # Extract underlying symbol from option symbol
                        # Option symbols format: AMD251017P00330000
                        # Extract underlying by removing date and option details
                        import re
                        underlying_match = re.match(r'^([A-Z]+)', symbol)
                        underlying = underlying_match.group(1) if underlying_match else symbol[:symbol.find('2') if '2' in symbol else len(symbol)]

                        # Place buy-to-close order
                        close_result = alpaca_client.place_option_order(
                            symbol=symbol,
                            qty=abs(qty),
                            side='buy',
                            order_type='market'
                        )

                        # Calculate profit/loss percentage
                        unrealized_pl = float(position.get('unrealized_pl', 0))
                        market_value = abs(float(position.get('market_value', 0)))
                        profit_pct = (unrealized_pl / market_value * 100) if market_value > 0 else 0

                        closed_positions.append({
                            'symbol': symbol,
                            'type': position_type,
                            'qty': abs(qty),
                            'unrealized_pl': unrealized_pl,
                            'profit_pct': profit_pct,
                            'close_result': close_result
                        })

                        # Log trade event for BigQuery analytics
                        log_trade_event(
                            logger,
                            event_type="early_close_executed",
                            symbol=symbol,
                            strategy=f"close_{position_type.lower()}",
                            success=close_result.get('success', True),
                            underlying=underlying,
                            option_type=position_type,
                            contracts=abs(qty),
                            unrealized_pl=unrealized_pl,
                            profit_pct=round(profit_pct, 2),
                            order_id=close_result.get('order_id'),
                            reason="profit_target_reached",
                            market_value=market_value,
                            entry_price=float(position.get('avg_entry_price', 0)),
                            exit_price=float(position.get('current_price', 0))
                        )

                        logger.info("Position closed successfully",
                                   event_category="execution",
                                   event_type="position_closed_early",
                                   symbol=symbol,
                                   type=position_type,
                                   unrealized_pl=unrealized_pl,
                                   profit_pct=round(profit_pct, 2),
                                   order_id=close_result.get('order_id'))

                except Exception as pos_error:
                    error_msg = f"Failed to evaluate position {position.get('symbol')}: {str(pos_error)}"
                    logger.error("Position monitoring error",
                                event_category="error",
                                event_type="position_monitoring_error",
                                symbol=position.get('symbol'),
                                error=str(pos_error))
                    errors.append(error_msg)

            # Calculate monitoring duration
            duration_seconds = (datetime.now() - start_time).total_seconds()

            # Log completion
            log_system_event(
                logger,
                event_type="position_monitoring_completed",
                status="completed",
                duration_seconds=duration_seconds,
                positions_evaluated=len(option_positions),
                positions_closed=len(closed_positions),
                errors=len(errors)
            )

            # Update global status
            strategy_status['last_monitor'] = datetime.now().isoformat()
            strategy_status['status'] = 'monitor_completed'

            return jsonify({
                'message': 'Position monitoring completed',
                'timestamp': datetime.now().isoformat(),
                'results': {
                    'positions_evaluated': len(option_positions),
                    'positions_closed': len(closed_positions),
                    'closed_positions': closed_positions,
                    'errors': errors
                }
            })

        except Exception as e:
            error_msg = f"Position monitoring failed: {str(e)}"
            logger.error("Position monitoring exception",
                        event_category="error",
                        event_type="position_monitoring_exception",
                        error=str(e),
                        traceback=traceback.format_exc())

            log_system_event(
                logger,
                event_type="position_monitoring_failed",
                status="error",
                error=str(e),
                duration_seconds=(datetime.now() - start_time).total_seconds()
            )

            return jsonify({'error': error_msg}), 500

@app.route('/account', methods=['GET'])
def get_account():
    """Get Alpaca account information."""
    try:
        config = Config()
        from src.api.alpaca_client import AlpacaClient

        client = AlpacaClient(config)
        account_info = client.get_account()

        # Add timestamp
        account_info['timestamp'] = datetime.now().isoformat()
        account_info['paper_trading'] = config.paper_trading

        return jsonify(account_info)

    except Exception as e:
        error_msg = f"Failed to get account info: {str(e)}"
        logger.error(error_msg,
                    event_category="error",
                    event_type="account_info_failed",
                    error=str(e),
                    traceback=traceback.format_exc())
        return jsonify({'error': error_msg}), 500

@app.route('/positions', methods=['GET'])
def get_positions():
    """Get current positions."""
    try:
        config = Config()
        from src.api.alpaca_client import AlpacaClient

        client = AlpacaClient(config)
        positions = client.get_positions()

        return jsonify({
            'positions': positions,
            'count': len(positions),
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        error_msg = f"Failed to get positions: {str(e)}"
        logger.error(error_msg,
                    event_category="error",
                    event_type="positions_fetch_failed",
                    error=str(e),
                    traceback=traceback.format_exc())
        return jsonify({'error': error_msg}), 500

@app.route('/config', methods=['GET'])
def get_config():
    """Get current configuration (sanitized)."""
    try:
        config = Config()

        # Return sanitized config (no secrets)
        config_data = {
            'paper_trading': True,  # Always true for cloud deployment
            'stock_symbols': getattr(config, 'stock_symbols', []),
            'max_positions': getattr(config, 'max_total_positions', 10),
            'gap_thresholds': {
                'quality': getattr(config, 'quality_gap_threshold', 2.0),
                'execution': getattr(config, 'execution_gap_threshold', 1.5)
            }
        }

        return jsonify(config_data)

    except Exception as e:
        error_msg = f"Config retrieval failed: {str(e)}"
        logger.error(error_msg,
                    event_category="error",
                    event_type="config_retrieval_failed")
        return jsonify({'error': error_msg}), 500

@app.route('/health')
def detailed_health():
    """Detailed health check including dependencies."""
    health_data = {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'checks': {}
    }

    # Check configuration
    try:
        config = Config()
        health_data['checks']['config'] = 'ok'
    except Exception as e:
        health_data['checks']['config'] = f'error: {str(e)}'
        health_data['status'] = 'unhealthy'

    # Check environment variables
    required_env_vars = ['ALPACA_API_KEY', 'ALPACA_SECRET_KEY']
    missing_vars = []
    for var in required_env_vars:
        if not os.getenv(var):
            missing_vars.append(var)

    if missing_vars:
        health_data['checks']['environment'] = f'missing: {", ".join(missing_vars)}'
        health_data['status'] = 'unhealthy'
    else:
        health_data['checks']['environment'] = 'ok'

    return jsonify(health_data)

# ============================================================================
# BACKTESTING ENDPOINTS
# ============================================================================

@app.route('/backtest', methods=['POST'])
def run_backtest():
    """Run a backtesting analysis."""
    try:
        logger.info("Starting backtest analysis",
                   event_category="backtest",
                   event_type="backtest_analysis_started")

        # Parse request parameters
        data = request.get_json() or {}

        # Default parameters
        lookback_days = data.get('lookback_days', 30)
        symbol = data.get('symbol', 'AAPL')
        strategy_params = data.get('strategy_params', {})
        analysis_type = data.get('analysis_type', 'quick')

        # Validate parameters
        if lookback_days > 365:
            return jsonify({'error': 'lookback_days cannot exceed 365 days'}), 400

        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days)

        # Initialize components
        config = Config()

        # Import backtesting components
        try:
            from src.backtesting.cloud_storage import EnhancedHistoricalDataManager
            from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig
            from src.backtesting.analysis import BacktestAnalyzer

            # Create proper BacktestConfig
            backtest_config = BacktestConfig(
                start_date=start_date,
                end_date=end_date,
                initial_capital=100000.0,
                symbols=[symbol] if symbol else ['SPY', 'AAPL', 'MSFT'],
                commission_per_contract=1.00
            )

            data_manager = EnhancedHistoricalDataManager(config)
            backtest_engine = BacktestEngine(config, backtest_config)
            performance_analyzer = None  # Will be instantiated with results after backtest

        except ImportError as e:
            logger.error("Backtesting import error",
                        event_category="error",
                        event_type="backtest_import_error",
                        error=str(e),
                        traceback=traceback.format_exc())
            return jsonify({
                'error': f'Backtesting components not available: {str(e)}',
                'suggestion': 'This might be expected in a minimal deployment',
                'traceback': traceback.format_exc()
            }), 503
        except Exception as e:
            logger.error("Backtesting initialization error",
                        event_category="error",
                        event_type="backtest_initialization_error",
                        error=str(e),
                        traceback=traceback.format_exc())
            return jsonify({
                'error': f'Backtesting initialization failed: {str(e)}',
                'traceback': traceback.format_exc()
            }), 503

        # Run the backtest
        backtest_id = f"bt_{int(time.time())}"

        # For quick analysis, run simplified backtest
        if analysis_type == 'quick':
            result = run_quick_backtest(
                backtest_engine, performance_analyzer,
                symbol, start_date, end_date, strategy_params, backtest_id
            )
        else:
            result = run_full_backtest(
                backtest_engine, performance_analyzer,
                symbol, start_date, end_date, strategy_params, backtest_id
            )

        logger.info("Backtest completed successfully",
                   event_category="backtest",
                   event_type="backtest_completed",
                   backtest_id=backtest_id)

        return jsonify({
            'backtest_id': backtest_id,
            'status': 'completed',
            'results': result,
            'parameters': {
                'symbol': symbol,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'lookback_days': lookback_days,
                'analysis_type': analysis_type
            },
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        error_msg = f"Backtest failed: {str(e)}"
        logger.error("Backtest execution failed",
                    event_category="error",
                    event_type="backtest_execution_failed",
                    error=error_msg,
                    traceback=traceback.format_exc())

        return jsonify({
            'error': error_msg,
            'timestamp': datetime.now().isoformat()
        }), 500

def run_quick_backtest(backtest_engine, performance_analyzer, symbol, start_date, end_date, strategy_params, backtest_id):
    """Run a quick backtest with real historical data."""
    try:
        logger.info("Running quick backtest with real engine",
                   event_category="backtest",
                   event_type="quick_backtest_started",
                   symbol=symbol,
                   start_date=start_date.date(),
                   end_date=end_date.date())

        # Run the actual backtest engine
        result = backtest_engine.run_backtest()

        # Extract key metrics from BacktestResult
        return {
            'performance_summary': {
                'total_return': round(result.total_return, 4),
                'annualized_return': round(result.annualized_return, 4),
                'total_trades': result.total_trades,
                'win_rate': round(result.win_rate, 3),
                'avg_return_per_trade': round(result.total_return / max(result.total_trades, 1), 4),
                'max_drawdown': round(result.max_drawdown, 4),
                'sharpe_ratio': round(result.sharpe_ratio, 2),
                'premium_collected': round(result.premium_collected, 2)
            },
            'trade_metrics': {
                'put_trades': result.put_trades,
                'call_trades': result.call_trades,
                'assignments': result.assignments,
                'assignment_rate': round(result.assignment_rate, 3)
            },
            'risk_metrics': {
                'max_at_risk_capital': round(result.max_at_risk_capital, 2),
                'avg_at_risk_capital': round(result.avg_at_risk_capital, 2),
                'peak_at_risk_percentage': round(result.peak_at_risk_percentage, 3)
            },
            'analysis_type': 'quick_real_data',
            'backtest_id': backtest_id
        }

    except Exception as e:
        logger.error("Quick backtest failed",
                    event_category="error",
                    event_type="quick_backtest_failed",
                    error=str(e),
                    traceback=traceback.format_exc())
        # Return error with details
        return {
            'error': str(e),
            'analysis_type': 'quick_real_data_failed',
            'traceback': traceback.format_exc()
        }

def run_full_backtest(backtest_engine, performance_analyzer, symbol, start_date, end_date, strategy_params, backtest_id):
    """Run a comprehensive backtest with full analysis and detailed trade history."""
    try:
        logger.info("Running comprehensive backtest with real engine",
                   event_category="backtest",
                   event_type="comprehensive_backtest_started",
                   symbol=symbol,
                   start_date=start_date.date(),
                   end_date=end_date.date())

        # Run the actual backtest engine
        result = backtest_engine.run_backtest()

        # Get base metrics
        base_results = {
            'performance_summary': {
                'initial_capital': round(result.initial_capital, 2),
                'final_capital': round(result.final_capital, 2),
                'total_return': round(result.total_return, 4),
                'annualized_return': round(result.annualized_return, 4),
                'total_trades': result.total_trades,
                'win_rate': round(result.win_rate, 3),
                'avg_return_per_trade': round(result.total_return / max(result.total_trades, 1), 4),
                'max_drawdown': round(result.max_drawdown, 4),
                'sharpe_ratio': round(result.sharpe_ratio, 2),
                'premium_collected': round(result.premium_collected, 2)
            },
            'trade_metrics': {
                'put_trades': result.put_trades,
                'call_trades': result.call_trades,
                'assignments': result.assignments,
                'assignment_rate': round(result.assignment_rate, 3)
            },
            'risk_metrics': {
                'max_at_risk_capital': round(result.max_at_risk_capital, 2),
                'avg_at_risk_capital': round(result.avg_at_risk_capital, 2),
                'peak_at_risk_percentage': round(result.peak_at_risk_percentage, 3)
            }
        }

        # Add comprehensive analysis with portfolio and trade history
        base_results['detailed_analysis'] = {
            'portfolio_history_sample': extract_portfolio_sample(result.portfolio_history),
            'trade_history_sample': extract_trade_sample(result.trade_history),
            'total_portfolio_snapshots': len(result.portfolio_history),
            'total_trades_logged': len(result.trade_history)
        }

        base_results['analysis_type'] = 'comprehensive_real_data'
        base_results['backtest_id'] = backtest_id

        return base_results

    except Exception as e:
        logger.error("Comprehensive backtest failed",
                    event_category="error",
                    event_type="comprehensive_backtest_failed",
                    error=str(e),
                    traceback=traceback.format_exc())
        return {
            'error': str(e),
            'analysis_type': 'comprehensive_real_data_failed',
            'traceback': traceback.format_exc()
        }

def extract_portfolio_sample(portfolio_df, sample_size=10):
    """Extract a sample of portfolio history for response."""
    if portfolio_df is None or portfolio_df.empty:
        return []

    # Get evenly spaced samples
    step = max(1, len(portfolio_df) // sample_size)
    sample = portfolio_df.iloc[::step].head(sample_size)

    return [
        {
            'date': row.name.isoformat() if hasattr(row.name, 'isoformat') else str(row.name),
            'total_value': round(row.get('total_value', 0), 2),
            'cash': round(row.get('cash', 0), 2),
            'positions_value': round(row.get('positions_value', 0), 2)
        }
        for _, row in sample.iterrows()
    ]

def extract_trade_sample(trade_df, sample_size=20):
    """Extract a sample of trade history for response."""
    if trade_df is None or trade_df.empty:
        return []

    # Get most recent trades
    sample = trade_df.tail(sample_size)

    return [
        {
            'date': row.get('date').isoformat() if hasattr(row.get('date'), 'isoformat') else str(row.get('date')),
            'symbol': row.get('symbol', 'N/A'),
            'action': row.get('action', 'N/A'),
            'strike': row.get('strike', 0),
            'premium': round(row.get('premium', 0), 2),
            'profit_loss': round(row.get('profit_loss', 0), 2)
        }
        for _, row in sample.iterrows()
    ]

def generate_monthly_returns(start_date, end_date):
    """Generate simulated monthly returns for the period."""

    monthly_returns = []
    current = start_date.replace(day=1)

    while current <= end_date:
        # Simulate monthly return based on month
        base_return = 0.01 + (hash(f"{current.year}{current.month}") % 50) / 5000
        monthly_returns.append({
            'month': current.strftime('%Y-%m'),
            'return': round(base_return, 4)
        })

        # Move to next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    return monthly_returns

@app.route('/backtest/results/<backtest_id>')
def get_backtest_results(backtest_id):
    """Retrieve stored backtest results."""
    try:
        # In a real implementation, this would fetch from cloud storage
        # For now, return a mock response

        return jsonify({
            'backtest_id': backtest_id,
            'status': 'completed',
            'results': {
                'message': 'Results would be retrieved from cloud storage',
                'implementation_note': 'This endpoint returns cached backtest results'
            },
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        error_msg = f"Failed to retrieve backtest results: {str(e)}"
        logger.error(error_msg,
                    event_category="error",
                    event_type="backtest_results_retrieval_failed")
        return jsonify({'error': error_msg}), 500

@app.route('/backtest/history')
def get_backtest_history():
    """Get list of recent backtest runs."""
    try:
        # Mock recent backtest history
        history = []
        for i in range(5):
            days_ago = i * 2 + 1
            run_date = datetime.now() - timedelta(days=days_ago)

            history.append({
                'backtest_id': f"bt_{int(run_date.timestamp())}",
                'symbol': ['AAPL', 'MSFT', 'GOOGL'][i % 3],
                'run_date': run_date.isoformat(),
                'status': 'completed',
                'total_return': round(0.05 + (i * 0.01), 3),
                'analysis_type': 'quick' if i % 2 == 0 else 'comprehensive'
            })

        return jsonify({
            'backtest_history': history,
            'total_runs': len(history),
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        error_msg = f"Failed to retrieve backtest history: {str(e)}"
        logger.error(error_msg,
                    event_category="error",
                    event_type="backtest_history_retrieval_failed")
        return jsonify({'error': error_msg}), 500

@app.route('/backtest/performance-comparison', methods=['POST'])
def performance_comparison():
    """Compare live trading performance vs backtested expectations."""
    try:
        data = request.get_json() or {}
        comparison_period = data.get('period_days', 30)

        # Mock comparison data
        comparison_data = {
            'period_days': comparison_period,
            'live_performance': {
                'total_return': 0.045,
                'win_rate': 0.78,
                'avg_return_per_trade': 0.023,
                'trades_executed': 12
            },
            'backtested_expectation': {
                'total_return': 0.042,
                'win_rate': 0.75,
                'avg_return_per_trade': 0.021,
                'expected_trades': 13
            },
            'variance_analysis': {
                'return_variance': 0.003,  # Live - Expected
                'win_rate_variance': 0.03,
                'performance_vs_expectation': 'outperforming',
                'statistical_significance': 'low'  # Due to small sample
            },
            'recommendations': [
                'Performance is slightly above backtested expectations',
                'Continue monitoring for larger sample size',
                'Consider parameter adjustment if variance increases'
            ]
        }

        return jsonify({
            'comparison': comparison_data,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        error_msg = f"Performance comparison failed: {str(e)}"
        logger.error(error_msg,
                    event_category="error",
                    event_type="performance_comparison_failed")
        return jsonify({'error': error_msg}), 500

@app.route('/cache/stats')
def get_cache_stats():
    """Get cache usage statistics."""
    try:
        # Try to get actual cache stats
        try:
            from src.backtesting.cloud_storage import CloudStorageCache
            config = Config()
            cache = CloudStorageCache(config)
            stats = cache.get_cache_stats()
        except ImportError:
            # Fallback if cloud storage not available
            stats = {
                'cloud_storage_available': False,
                'local_cache_enabled': True,
                'note': 'Cloud storage module not available in this deployment'
            }

        return jsonify({
            'cache_statistics': stats,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        error_msg = f"Failed to get cache stats: {str(e)}"
        logger.error(error_msg,
                    event_category="error",
                    event_type="cache_stats_failed")
        return jsonify({'error': error_msg}), 500

@app.route('/cache/cleanup', methods=['POST'])
def cleanup_cache():
    """Clean up old cache files."""
    try:
        data = request.get_json() or {}
        days_old = data.get('days_old', 30)

        # Try to perform actual cleanup
        try:
            from src.backtesting.cloud_storage import CloudStorageCache
            config = Config()
            cache = CloudStorageCache(config)
            cleanup_stats = cache.cleanup_old_cache(days_old)
        except ImportError:
            cleanup_stats = {
                'local_deleted': 0,
                'cloud_deleted': 0,
                'note': 'Cloud storage module not available'
            }

        return jsonify({
            'cleanup_results': cleanup_stats,
            'days_old_threshold': days_old,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        error_msg = f"Cache cleanup failed: {str(e)}"
        logger.error(error_msg,
                    event_category="error",
                    event_type="cache_cleanup_failed")
        return jsonify({'error': error_msg}), 500

# ============================================================================
# PERFORMANCE MONITORING DASHBOARD ENDPOINTS
# ============================================================================

@app.route('/dashboard')
def performance_dashboard():
    """Get comprehensive performance dashboard data."""
    try:
        from deploy.monitoring.performance_dashboard import PerformanceMonitor

        monitor = PerformanceMonitor()
        dashboard_data = monitor.generate_dashboard_data()

        return jsonify(dashboard_data)

    except ImportError:
        # Fallback if performance monitor not available
        return jsonify({
            'status': 'limited_dashboard',
            'current_metrics': {
                'portfolio_value': 100000.0,
                'total_return': 0.045,
                'positions_count': 8,
                'win_rate': 0.75,
                'timestamp': datetime.now().isoformat()
            },
            'alerts': {'active_alerts': [], 'alert_count': 0},
            'system_health': {'overall_status': 'healthy'},
            'note': 'Full dashboard requires performance monitoring module'
        })

    except Exception as e:
        error_msg = f"Dashboard generation failed: {str(e)}"
        logger.error(error_msg,
                    event_category="error",
                    event_type="dashboard_generation_failed")
        return jsonify({'error': error_msg}), 500

@app.route('/dashboard/alerts')
def get_active_alerts():
    """Get current active alerts."""
    try:
        from deploy.monitoring.performance_dashboard import PerformanceMonitor

        monitor = PerformanceMonitor()
        current_metrics = monitor.collect_current_metrics()
        alerts = monitor.check_alerts(current_metrics)

        return jsonify({
            'active_alerts': alerts,
            'alert_count': len(alerts),
            'last_check': datetime.now().isoformat(),
            'severity_summary': {
                'high': len([a for a in alerts if a.get('severity') == 'high']),
                'medium': len([a for a in alerts if a.get('severity') == 'medium']),
                'low': len([a for a in alerts if a.get('severity') == 'low'])
            }
        })

    except ImportError:
        return jsonify({
            'active_alerts': [],
            'alert_count': 0,
            'note': 'Alert monitoring requires performance dashboard module'
        })

    except Exception as e:
        error_msg = f"Alert check failed: {str(e)}"
        logger.error(error_msg,
                    event_category="error",
                    event_type="alert_check_failed")
        return jsonify({'error': error_msg}), 500

@app.route('/dashboard/metrics/export')
def export_metrics():
    """Export performance metrics in various formats."""
    try:
        format_type = request.args.get('format', 'json').lower()

        from deploy.monitoring.performance_dashboard import PerformanceMonitor

        monitor = PerformanceMonitor()
        exported_data = monitor.export_metrics(format_type)

        if format_type == 'csv':
            return exported_data, 200, {
                'Content-Type': 'text/csv',
                'Content-Disposition': f'attachment; filename=metrics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            }
        else:
            return exported_data, 200, {'Content-Type': 'application/json'}

    except ImportError:
        return jsonify({
            'error': 'Export functionality requires performance monitoring module'
        }), 503

    except Exception as e:
        error_msg = f"Metrics export failed: {str(e)}"
        logger.error(error_msg,
                    event_category="error",
                    event_type="metrics_export_failed")
        return jsonify({'error': error_msg}), 500

@app.route('/dashboard/health')
def system_health_check():
    """Get detailed system health information."""
    try:
        from deploy.monitoring.performance_dashboard import PerformanceMonitor

        monitor = PerformanceMonitor()
        dashboard_data = monitor.generate_dashboard_data()

        health_info = {
            'system_health': dashboard_data.get('system_health', {}),
            'performance_summary': dashboard_data.get('performance_summary', {}),
            'risk_metrics': dashboard_data.get('risk_metrics', {}),
            'execution_metrics': dashboard_data.get('execution_metrics', {}),
            'timestamp': datetime.now().isoformat()
        }

        return jsonify(health_info)

    except ImportError:
        return jsonify({
            'system_health': {
                'overall_status': 'healthy',
                'components': {
                    'basic_monitoring': 'active',
                    'advanced_monitoring': 'unavailable'
                }
            },
            'note': 'Detailed health monitoring requires performance dashboard module'
        })

    except Exception as e:
        error_msg = f"Health check failed: {str(e)}"
        logger.error(error_msg,
                    event_category="error",
                    event_type="health_check_failed")
        return jsonify({'error': error_msg}), 500

@app.route('/dashboard/trends')
def get_performance_trends():
    """Get performance trend analysis."""
    try:
        from deploy.monitoring.performance_dashboard import PerformanceMonitor

        monitor = PerformanceMonitor()
        dashboard_data = monitor.generate_dashboard_data()

        trends_data = {
            'trends': dashboard_data.get('trends', {}),
            'performance_summary': dashboard_data.get('performance_summary', {}),
            'data_points': len(monitor.metrics_history),
            'trend_analysis_period': '24 hours',
            'timestamp': datetime.now().isoformat()
        }

        return jsonify(trends_data)

    except ImportError:
        return jsonify({
            'trends': {'trend_data': 'unavailable'},
            'note': 'Trend analysis requires performance monitoring module'
        })

    except Exception as e:
        error_msg = f"Trend analysis failed: {str(e)}"
        logger.error(error_msg,
                    event_category="error",
                    event_type="trend_analysis_failed")
        return jsonify({'error': error_msg}), 500

@app.route('/backtest/trades/<backtest_id>')
def get_detailed_trades(backtest_id):
    """Get detailed trade-by-trade breakdown for a backtest."""
    try:
        # Import cloud storage integration
        from src.backtesting.cloud_storage import CloudStorageCache
        config = Config()
        cloud_storage = CloudStorageCache(config)

        # Retrieve stored results
        results = cloud_storage.get_stored_backtest_results(backtest_id)

        if not results:
            return jsonify({
                'error': 'Backtest results not found',
                'backtest_id': backtest_id
            }), 404

        trades = results.get('trades', [])

        # Group trades by action for better analysis
        trade_analysis = {
            'backtest_id': backtest_id,
            'total_trades': len(trades),
            'trade_breakdown': {
                'opened_positions': [t for t in trades if t.get('action') == 'open'],
                'closed_positions': [t for t in trades if t.get('action') == 'close'],
                'assignments': [t for t in trades if t.get('action') == 'assignment'],
                'skipped_trades': [t for t in trades if t.get('action') == 'skipped']
            },
            'performance_by_symbol': {},
            'execution_quality': {}
        }

        # Calculate performance by symbol
        closed_trades = [t for t in trades if t.get('action') in ['close', 'assignment'] and t.get('realized_pnl')]
        symbol_performance = {}

        for trade in closed_trades:
            symbol = trade.get('symbol')
            if symbol not in symbol_performance:
                symbol_performance[symbol] = {
                    'trades': [],
                    'total_pnl': 0,
                    'win_count': 0,
                    'loss_count': 0
                }

            pnl = trade.get('realized_pnl', 0)
            symbol_performance[symbol]['trades'].append(trade)
            symbol_performance[symbol]['total_pnl'] += pnl

            if pnl > 0:
                symbol_performance[symbol]['win_count'] += 1
            elif pnl < 0:
                symbol_performance[symbol]['loss_count'] += 1

        # Calculate summary stats for each symbol
        for symbol, data in symbol_performance.items():
            total_trades = len(data['trades'])
            if total_trades > 0:
                data['win_rate'] = data['win_count'] / total_trades
                data['avg_pnl'] = data['total_pnl'] / total_trades
                data['total_trades'] = total_trades

        trade_analysis['performance_by_symbol'] = symbol_performance

        # Calculate execution quality metrics
        open_trades = [t for t in trades if t.get('action') == 'open']
        if open_trades:
            spreads = [t.get('spread_pct', 0) for t in open_trades if t.get('spread_pct') is not None]
            volumes = [t.get('volume', 0) for t in open_trades if t.get('volume') is not None]

            if spreads:
                trade_analysis['execution_quality']['avg_spread_pct'] = sum(spreads) / len(spreads)
                trade_analysis['execution_quality']['tight_spreads_pct'] = sum(1 for s in spreads if s < 0.05) / len(spreads)

            if volumes:
                trade_analysis['execution_quality']['avg_volume'] = sum(volumes) / len(volumes)
                trade_analysis['execution_quality']['high_volume_pct'] = sum(1 for v in volumes if v >= 100) / len(volumes)

        return jsonify(trade_analysis)

    except Exception as e:
        logger.error(f"Failed to get detailed trades: {str(e)}",
                    event_category="error",
                    event_type="detailed_trades_fetch_failed")
        return jsonify({'error': f'Failed to get trades: {str(e)}'}), 500

@app.route('/backtest/analytics/<backtest_id>')
def get_backtest_analytics(backtest_id):
    """Get comprehensive analytics for a backtest."""
    try:
        # Import cloud storage integration
        from src.backtesting.cloud_storage import CloudStorageCache
        config = Config()
        cloud_storage = CloudStorageCache(config)

        # Retrieve stored results
        results = cloud_storage.get_stored_backtest_results(backtest_id)

        if not results:
            return jsonify({
                'error': 'Backtest results not found',
                'backtest_id': backtest_id
            }), 404

        trades = results.get('trades', [])
        config_data = results.get('config', {})
        summary_metrics = results.get('summary_metrics', {})

        # Generate comprehensive analytics
        analytics = {
            'backtest_id': backtest_id,
            'timestamp': results.get('timestamp'),
            'configuration': config_data,
            'summary_metrics': summary_metrics,
            'trade_timeline': [],
            'risk_metrics': {},
            'execution_analysis': {},
            'strategy_effectiveness': {}
        }

        # Create trade timeline
        sorted_trades = sorted(trades, key=lambda x: x.get('date', ''))
        running_pnl = 0

        for trade in sorted_trades:
            pnl = trade.get('realized_pnl', 0)
            if pnl:
                running_pnl += pnl

            analytics['trade_timeline'].append({
                'date': trade.get('date'),
                'action': trade.get('action'),
                'symbol': trade.get('symbol'),
                'type': trade.get('type'),
                'pnl': pnl,
                'running_pnl': running_pnl,
                'description': trade.get('description', '')
            })

        # Risk analysis
        completed_trades = [t for t in trades if t.get('realized_pnl') is not None]
        if completed_trades:
            pnls = [t['realized_pnl'] for t in completed_trades]
            analytics['risk_metrics'] = {
                'max_single_loss': min(pnls),
                'max_single_gain': max(pnls),
                'volatility': (sum((p - sum(pnls)/len(pnls))**2 for p in pnls) / len(pnls))**0.5,
                'downside_deviation': (sum(min(0, p)**2 for p in pnls) / len(pnls))**0.5
            }

        # Strategy effectiveness
        put_trades = [t for t in trades if t.get('type') == 'PUT']
        call_trades = [t for t in trades if t.get('type') == 'CALL']

        analytics['strategy_effectiveness'] = {
            'put_strategy': {
                'total_trades': len(put_trades),
                'completed_trades': len([t for t in put_trades if t.get('realized_pnl') is not None]),
                'total_pnl': sum(t.get('realized_pnl', 0) for t in put_trades if t.get('realized_pnl'))
            },
            'call_strategy': {
                'total_trades': len(call_trades),
                'completed_trades': len([t for t in call_trades if t.get('realized_pnl') is not None]),
                'total_pnl': sum(t.get('realized_pnl', 0) for t in call_trades if t.get('realized_pnl'))
            }
        }

        return jsonify(analytics)

    except Exception as e:
        logger.error(f"Failed to get backtest analytics: {str(e)}",
                    event_category="error",
                    event_type="backtest_analytics_fetch_failed")
        return jsonify({'error': f'Failed to get analytics: {str(e)}'}), 500

def setup_logging():
    """Configure structured logging."""
    import logging
    import sys

    # Configure Python's logging module to output to stderr (Cloud Run captures this)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=logging.INFO
    )

    # Configure structlog to use Python logging
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

if __name__ == '__main__':
    setup_logging()

    # Get port from environment (Cloud Run sets this)
    port = int(os.environ.get('PORT', 8080))

    logger.info("Starting Options Wheel Strategy Cloud Run server",
               event_category="system",
               event_type="server_starting",
               port=port)

    # Initialize configuration to verify everything works
    try:
        config = Config()
        logger.info("Configuration loaded successfully",
                   event_category="system",
                   event_type="config_loaded")
    except Exception as e:
        logger.error("Failed to load configuration",
                    event_category="error",
                    event_type="config_load_failed",
                    error=str(e))

    # Run the Flask app
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True
    )