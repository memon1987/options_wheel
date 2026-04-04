"""Core options wheel strategy engine."""

from typing import Dict, List, Any, Optional
from datetime import datetime
import os
import structlog

from ..api.alpaca_client import AlpacaClient
from ..api.market_data import MarketDataManager
from ..risk.gap_detector import GapDetector
from ..utils.config import Config
from ..utils.logging_events import log_system_event, log_performance_metric, log_error_event, log_position_update, log_order_status_update
from ..utils.positions import get_stock_positions
from ..utils.option_symbols import parse_option_symbol
from .put_seller import PutSeller
from .call_seller import CallSeller
from .wheel_state_manager import WheelStateManager, WheelPhase

logger = structlog.get_logger(__name__)


class WheelEngine:
    """Main engine for executing options wheel strategy."""

    def __init__(self, config: Config):
        """Initialize the wheel strategy engine.

        Args:
            config: Configuration instance
        """
        self.config = config
        self.alpaca = AlpacaClient(config)
        self.market_data = MarketDataManager(self.alpaca, config)
        self.gap_detector = GapDetector(config, self.alpaca)
        self.put_seller = PutSeller(self.alpaca, self.market_data, config)
        self.call_seller = CallSeller(self.alpaca, self.market_data, config)
        state_bucket = getattr(config, 'state_storage_bucket', None) or os.getenv('STATE_STORAGE_BUCKET')
        self.wheel_state = WheelStateManager(storage_bucket=state_bucket)

        # Track pending orders within current execution cycle to prevent duplicates
        self._pending_underlyings = set()

        logger.info("Wheel engine initialized with state management",
                   event_category="system", event_type="engine_initialized")
    
    def run_strategy_cycle(self) -> Dict[str, Any]:
        """Run one complete cycle of the wheel strategy.

        Returns:
            Summary of actions taken
        """
        start_time = datetime.now()
        logger.info("Starting strategy cycle",
                   event_category="system", event_type="strategy_cycle_started")

        # Clear pending underlyings from previous cycle
        self._pending_underlyings.clear()

        cycle_summary = {
            'timestamp': start_time.isoformat(),
            'actions': [],
            'errors': [],
            'account_info': {},
            'positions_analyzed': 0,
            'new_positions': 0,
            'closed_positions': 0
        }

        try:
            # Get account information
            account_info = self.alpaca.get_account()
            cycle_summary['account_info'] = account_info

            # Get current positions
            positions = self.alpaca.get_positions()
            cycle_summary['positions_analyzed'] = len(positions)

            # Sync wheel state with current positions
            self._sync_wheel_state_with_positions(positions)

            # Analyze current positions and manage them
            position_actions = self._manage_existing_positions(positions)
            cycle_summary['actions'].extend(position_actions)

            # Look for new opportunities if we have capacity
            if self._can_open_new_positions(positions):
                new_position_actions = self._find_new_opportunities()
                cycle_summary['actions'].extend(new_position_actions)

            # Count new and closed positions
            cycle_summary['new_positions'] = len([a for a in cycle_summary['actions'] if a['action_type'] == 'new_position'])
            cycle_summary['closed_positions'] = len([a for a in cycle_summary['actions'] if a['action_type'] == 'close_position'])

            # Calculate cycle duration
            end_time = datetime.now()
            duration_seconds = (end_time - start_time).total_seconds()

            # Enhanced system event logging
            log_system_event(
                logger,
                event_type="strategy_cycle_completed",
                status="completed",
                duration_seconds=duration_seconds,
                actions_taken=len(cycle_summary['actions']),
                new_positions=cycle_summary['new_positions'],
                closed_positions=cycle_summary['closed_positions'],
                positions_analyzed=cycle_summary['positions_analyzed']
            )

            # Log performance metric
            log_performance_metric(
                logger,
                metric_name="strategy_cycle_duration",
                metric_value=duration_seconds,
                metric_unit="seconds",
                actions_taken=len(cycle_summary['actions'])
            )

            # Log daily unrealized P&L snapshot for each stock position
            self._log_daily_stock_snapshots()

        except Exception as e:
            error_msg = f"Strategy cycle failed: {str(e)}"

            # Enhanced error logging
            log_error_event(
                logger,
                error_type="strategy_cycle_exception",
                error_message=str(e),
                component="wheel_engine",
                recoverable=False
            )
            cycle_summary['errors'].append(error_msg)

        return cycle_summary
    
    def _manage_existing_positions(self, positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Manage existing positions in the portfolio.
        
        Args:
            positions: Current positions from account
            
        Returns:
            List of actions taken
        """
        actions = []
        
        # Separate stock and option positions
        stock_positions = get_stock_positions(positions)
        option_positions = [p for p in positions if p['asset_class'] == 'us_option']

        # Handle assigned stock positions (from put assignment)
        for stock_pos in stock_positions:
            symbol = stock_pos['symbol']

            # Only sell calls if wheel state allows it
            if self.wheel_state.can_sell_calls(symbol):
                action = self.call_seller.evaluate_covered_call_opportunity(stock_pos)
                if action:
                    actions.append(action)
                    # Update wheel state to track new call position
                    if action.get('contracts'):
                        self.wheel_state.add_call_position(
                            symbol, action['contracts'], action.get('premium', 0), datetime.now()
                        )
            else:
                logger.info("Covered call selling blocked by wheel state",
                           event_category="trade", event_type="covered_call_blocked",
                           symbol=symbol,
                           wheel_phase=self.wheel_state.get_wheel_phase(symbol).value)
        
        # Handle existing option positions
        for option_pos in option_positions:
            action = self._evaluate_option_position(option_pos)
            if action:
                actions.append(action)
        
        return actions
    
    def _evaluate_option_position(self, position: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Evaluate an existing option position for potential actions.
        
        Args:
            position: Option position data
            
        Returns:
            Action dictionary if action needed, None otherwise
        """
        try:
            symbol = position['symbol']
            qty = float(position['qty'])
            
            # For short positions (negative qty), we sold the option
            if qty < 0:
                # Check if we should buy to close for profit
                # This would be implemented with more sophisticated logic
                # For now, we'll use a simple profit target
                unrealized_pl = float(position['unrealized_pl'])
                
                # If we're making 50% of max profit, consider closing
                if unrealized_pl > 0:  # We're profitable
                    return {
                        'action_type': 'close_position',
                        'symbol': symbol,
                        'current_qty': qty,
                        'reason': 'profit_target',
                        'unrealized_pl': unrealized_pl
                    }
            
            return None
            
        except Exception as e:
            logger.error("Failed to evaluate option position",
                        event_category="error", event_type="option_evaluation_failed",
                        position=position, error=str(e))
            return None
    
    def _can_open_new_positions(self, positions: List[Dict[str, Any]]) -> bool:
        """Check if we can open new positions based on risk limits.
        
        Args:
            positions: Current positions
            
        Returns:
            True if we can open new positions
        """
        # Count current option positions (short puts/calls)
        option_positions = [p for p in positions if p['asset_class'] == 'us_option' and float(p['qty']) < 0]
        
        if len(option_positions) >= self.config.max_total_positions:
            logger.info("Maximum total positions reached",
                       event_category="filtering", event_type="max_positions_reached",
                       current=len(option_positions),
                       max_allowed=self.config.max_total_positions)
            return False
        
        # Check portfolio allocation
        account_info = self.alpaca.get_account()
        buying_power = float(account_info['buying_power'])
        
        if buying_power < 1000:  # Minimum buying power threshold
            logger.info("Insufficient buying power",
                       event_category="filtering", event_type="insufficient_buying_power",
                       buying_power=buying_power)
            return False
        
        return True
    
    def _find_new_opportunities(self) -> List[Dict[str, Any]]:
        """Find new options trading opportunities using proper wheel strategy logic.

        Returns:
            List of actions for new opportunities
        """
        actions = []
        start_time = datetime.now()

        try:
            # Get suitable stocks for wheel strategy
            suitable_stocks = self.market_data.filter_suitable_stocks(self.config.stock_symbols)

            # Filter by gap risk
            stock_symbols = [stock['symbol'] for stock in suitable_stocks]
            gap_filtered_symbols = self.gap_detector.filter_stocks_by_gap_risk(
                stock_symbols, datetime.now()
            )

            # Convert back to stock objects
            gap_filtered_stocks = [stock for stock in suitable_stocks
                                 if stock['symbol'] in gap_filtered_symbols]

            # Enhanced logging for debugging
            filtered_out = [s['symbol'] for s in suitable_stocks if s['symbol'] not in gap_filtered_symbols]
            logger.info("Evaluating new opportunities with wheel state logic",
                       event_category="filtering", event_type="opportunity_evaluation_started",
                       suitable_stocks=len(suitable_stocks),
                       gap_filtered_stocks=len(gap_filtered_stocks),
                       gap_filtered_symbols=", ".join(gap_filtered_symbols),
                       filtered_out_symbols=", ".join(filtered_out))

            # Log performance metric for market scan
            scan_duration = (datetime.now() - start_time).total_seconds()
            log_performance_metric(
                logger,
                metric_name="market_scan_duration",
                metric_value=scan_duration,
                metric_unit="seconds",
                symbols_scanned=len(stock_symbols),
                suitable_stocks=len(suitable_stocks),
                gap_filtered_stocks=len(gap_filtered_stocks)
            )

            # Apply configurable stock evaluation limit (Stage 3)
            max_stocks = self.config.max_stocks_evaluated_per_cycle
            stocks_to_evaluate = gap_filtered_stocks[:max_stocks] if max_stocks else gap_filtered_stocks

            if max_stocks:
                logger.info("STAGE 3: Stock evaluation limit applied",
                           event_category="filtering",
                           event_type="stage_3_limit_applied",
                           max_stocks=max_stocks,
                           total_available=len(gap_filtered_stocks),
                           evaluating=len(stocks_to_evaluate),
                           symbols_to_evaluate=", ".join(s['symbol'] for s in stocks_to_evaluate))
            else:
                logger.info("STAGE 3: No stock evaluation limit (evaluating all gap-filtered stocks)",
                           event_category="filtering",
                           event_type="stage_3_no_limit",
                           stocks_to_evaluate=len(stocks_to_evaluate),
                           symbols_to_evaluate=", ".join(s['symbol'] for s in stocks_to_evaluate))

            # Process each stock according to wheel strategy phases
            for stock in stocks_to_evaluate:
                symbol = stock['symbol']
                wheel_phase = self.wheel_state.get_wheel_phase(symbol)

                # Check execution gap before proceeding (Stage 4)
                execution_check = self.gap_detector.can_execute_trade(symbol, datetime.now())
                if not execution_check['can_execute']:
                    logger.info("STAGE 4: Execution gap check BLOCKED",
                               event_category="filtering",
                               event_type="stage_4_blocked",
                               symbol=symbol,
                               reason=execution_check['reason'],
                               gap_percent=execution_check.get('current_gap_percent', 0))
                    continue
                else:
                    logger.info("STAGE 4: Execution gap check PASSED",
                               event_category="filtering",
                               event_type="stage_4_passed",
                               symbol=symbol,
                               gap_percent=execution_check.get('current_gap_percent', 0))

                # Prioritize covered calls over puts when holding stock
                opportunity_found = False

                # Stage 5: Wheel State Check
                can_sell_calls = self.wheel_state.can_sell_calls(symbol)
                can_sell_puts = self.wheel_state.can_sell_puts(symbol)

                logger.info("STAGE 5: Wheel state check",
                           event_category="filtering",
                           event_type="stage_5_check",
                           symbol=symbol,
                           wheel_phase=wheel_phase.value,
                           can_sell_calls=can_sell_calls,
                           can_sell_puts=can_sell_puts)

                # 1. If holding stock, prioritize covered calls
                if can_sell_calls:
                    call_opportunity = self.call_seller.evaluate_covered_call_opportunity(
                        self._get_stock_position_for_symbol(symbol)
                    )
                    if call_opportunity:
                        call_opportunity['gap_check'] = execution_check
                        actions.append(call_opportunity)
                        opportunity_found = True
                        logger.info("Covered call opportunity found",
                                   event_category="trade", event_type="covered_call_opportunity_found",
                                   symbol=symbol,
                                   wheel_phase=wheel_phase.value)

                # 2. Only look for puts if no stock position (proper wheel logic)
                if not opportunity_found and can_sell_puts:
                    # Check if we already have option positions in this stock (Stage 6)
                    if self._has_existing_option_position(symbol):
                        logger.info("STAGE 6: Existing position check BLOCKED",
                                   event_category="filtering",
                                   event_type="stage_6_blocked",
                                   symbol=symbol,
                                   reason="already_has_option_position")
                        continue
                    else:
                        logger.info("STAGE 6: Existing position check PASSED",
                                   event_category="filtering",
                                   event_type="stage_6_passed",
                                   symbol=symbol)

                    put_opportunity = self.put_seller.find_put_opportunity(symbol, self.wheel_state)
                    if put_opportunity:
                        put_opportunity['gap_check'] = execution_check
                        actions.append(put_opportunity)
                        opportunity_found = True
                        logger.info("Put selling opportunity found",
                                   event_category="trade", event_type="put_opportunity_found",
                                   symbol=symbol,
                                   wheel_phase=wheel_phase.value)

                # Apply configurable position limit (Stage 9)
                max_positions = self.config.max_new_positions_per_cycle
                if max_positions and len(actions) >= max_positions:
                    logger.info("STAGE 9: Max new positions per cycle limit REACHED",
                               event_category="filtering",
                               event_type="stage_9_limit_reached",
                               max_positions=max_positions,
                               positions_found=len(actions),
                               stopping_evaluation=True)
                    break

        except Exception as e:
            logger.error("Failed to find new opportunities",
                       event_category="error", event_type="opportunity_search_failed",
                       error=str(e))

        # Log summary of opportunities found
        logger.info("New opportunities search completed",
                   event_category="trade", event_type="opportunity_search_completed",
                   opportunities_found=len(actions),
                   put_opportunities=len([a for a in actions if 'put' in a.get('action_type', '').lower()]),
                   call_opportunities=len([a for a in actions if 'call' in a.get('action_type', '').lower()]))

        return actions
    
    def _has_existing_position(self, underlying_symbol: str) -> bool:
        """Check if we already have any positions in a given underlying stock.

        Args:
            underlying_symbol: Stock symbol to check

        Returns:
            True if we have existing positions
        """
        try:
            positions = self.alpaca.get_positions()

            # Check for stock positions
            stock_positions = [p for p in positions
                             if p['symbol'] == underlying_symbol and p['asset_class'] == 'us_equity']

            # Check for option positions on this underlying
            option_positions = [p for p in positions
                              if p['asset_class'] == 'us_option' and underlying_symbol in p['symbol']]

            return len(stock_positions) > 0 or len(option_positions) > 0

        except Exception as e:
            logger.error("Failed to check existing positions",
                        event_category="error", event_type="position_check_failed",
                        symbol=underlying_symbol, error=str(e))
            return True  # Be conservative and assume we have positions

    def _has_existing_option_position(self, underlying_symbol: str) -> bool:
        """Check if we already have option positions in a given underlying stock.

        This checks THREE sources to prevent duplicate positions:
        1. Pending orders in current execution cycle (tracked locally)
        2. Open/pending orders from Alpaca API (not yet filled)
        3. Filled positions from Alpaca API

        Args:
            underlying_symbol: Stock symbol to check

        Returns:
            True if we have existing option positions OR pending/open orders
        """
        try:
            # Check 1: Pending order in current cycle (local tracking)
            if underlying_symbol in self._pending_underlyings:
                logger.info("STAGE 6: Existing position check BLOCKED - pending order in current cycle",
                           event_category="filtering",
                           event_type="stage_6_blocked",
                           symbol=underlying_symbol,
                           reason="pending_order_in_current_cycle")
                return True

            # Check 2: Open/pending orders from Alpaca API
            # This catches orders that were placed but not yet filled (race condition fix)
            try:
                open_orders = self.alpaca.get_orders(status='open')
                pending_orders = self.alpaca.get_orders(status='pending_new')
                all_pending = open_orders + pending_orders

                # Check if any pending orders are for options on this underlying
                for order in all_pending:
                    # Option symbols contain the underlying (e.g., AMD251017P00207500 contains AMD)
                    if underlying_symbol in order['symbol']:
                        logger.info("STAGE 6: Existing position check BLOCKED - open order exists",
                                   event_category="filtering",
                                   event_type="stage_6_blocked",
                                   symbol=underlying_symbol,
                                   reason="open_order_exists",
                                   order_id=order['order_id'],
                                   order_status=order['status'],
                                   order_symbol=order['symbol'])
                        return True
            except Exception as order_error:
                logger.warning("Failed to check open orders, continuing to position check",
                             event_category="error", event_type="order_check_failed",
                             symbol=underlying_symbol,
                             error=str(order_error))

            # Check 3: Filled positions from Alpaca
            positions = self.alpaca.get_positions()

            # Check for option positions on this underlying
            option_positions = [p for p in positions
                              if p['asset_class'] == 'us_option' and underlying_symbol in p['symbol']]

            has_filled_position = len(option_positions) > 0

            if has_filled_position:
                logger.info("STAGE 6: Existing position check BLOCKED - filled position exists",
                           event_category="filtering",
                           event_type="stage_6_blocked",
                           symbol=underlying_symbol,
                           reason="filled_position_exists",
                           position_count=len(option_positions))
                return True

            # No existing positions or orders found - safe to proceed
            logger.info("STAGE 6: Existing position check PASSED - no positions or orders",
                       event_category="filtering",
                       event_type="stage_6_passed",
                       symbol=underlying_symbol)
            return False

        except Exception as e:
            logger.error("Failed to check existing option positions",
                        event_category="error",
                        symbol=underlying_symbol,
                        error=str(e))
            return True  # Be conservative and assume we have positions
    
    def get_strategy_status(self) -> Dict[str, Any]:
        """Get current status of the wheel strategy.
        
        Returns:
            Status summary
        """
        try:
            account_info = self.alpaca.get_account()
            positions = self.alpaca.get_positions()
            
            # Separate positions by type
            stock_positions = get_stock_positions(positions)
            option_positions = [p for p in positions if p['asset_class'] == 'us_option']

            # Calculate metrics
            total_stock_value = sum(float(p['market_value']) for p in stock_positions)
            total_option_value = sum(float(p['market_value']) for p in option_positions)
            
            return {
                'account': {
                    'portfolio_value': account_info['portfolio_value'],
                    'buying_power': account_info['buying_power'],
                    'cash': account_info['cash']
                },
                'positions': {
                    'total_positions': len(positions),
                    'stock_positions': len(stock_positions),
                    'option_positions': len(option_positions),
                    'stock_value': total_stock_value,
                    'option_value': total_option_value
                },
                'capacity': {
                    'can_open_new_positions': self._can_open_new_positions(positions),
                    'positions_remaining': max(0, self.config.max_total_positions - len(option_positions))
                },
                'timestamp': datetime.now().isoformat(),
                'wheel_state': {
                    'symbols_in_put_phase': len(self.wheel_state.get_symbols_by_phase(WheelPhase.SELLING_PUTS)),
                    'symbols_holding_stock': len(self.wheel_state.get_symbols_by_phase(WheelPhase.HOLDING_STOCK)),
                    'symbols_selling_calls': len(self.wheel_state.get_symbols_by_phase(WheelPhase.SELLING_CALLS)),
                    'completed_wheel_cycles': len(self.wheel_state.get_all_wheel_cycles())
                }
            }

        except Exception as e:
            logger.error("Failed to get strategy status",
                        event_category="error", event_type="status_failed",
                        error=str(e))
            return {'error': str(e)}

    def _sync_wheel_state_with_positions(self, positions: List[Dict[str, Any]]):
        """Synchronize wheel state manager with current account positions.

        Args:
            positions: Current positions from account
        """
        try:
            # Track symbols we've seen to identify removed positions
            current_symbols = set()

            # Process stock positions
            stock_positions = get_stock_positions(positions)
            for stock_pos in stock_positions:
                symbol = stock_pos['symbol']
                shares = int(float(stock_pos['qty']))
                cost_basis = float(stock_pos['avg_cost'])

                if shares > 0:  # Long position
                    current_symbols.add(symbol)
                    # Update wheel state if not already tracked
                    state_summary = self.wheel_state.get_position_summary(symbol)
                    if state_summary['stock_shares'] != shares:
                        logger.info("Syncing stock position with wheel state",
                                   event_category="system", event_type="position_sync_started",
                                   symbol=symbol, shares=shares, cost_basis=cost_basis)
                        # This is a simplified sync - in practice might need more sophisticated handling
                        self.wheel_state.handle_put_assignment(
                            symbol, shares - state_summary['stock_shares'], cost_basis, datetime.now()
                        )

            # Process option positions to track active contracts
            option_positions = [p for p in positions if p['asset_class'] == 'us_option']
            for option_pos in option_positions:
                option_symbol = option_pos['symbol']
                qty = float(option_pos['qty'])

                if qty < 0:  # Short position (sold option)
                    # Extract underlying symbol from option symbol
                    # This is simplified - you might need more robust option symbol parsing
                    underlying = self._extract_underlying_from_option_symbol(option_symbol)
                    if underlying:
                        current_symbols.add(underlying)
                        contracts = abs(int(qty))

                        # Determine option type and update state accordingly
                        if 'P' in option_symbol:  # Put option
                            # Note: We don't automatically add puts here as they might violate wheel logic
                            # This sync is primarily for existing positions
                            pass
                        elif 'C' in option_symbol:  # Call option
                            # Update call position tracking
                            pass

            logger.debug("Wheel state synchronized with account positions",
                        event_category="system", event_type="position_sync_completed",
                        symbols_tracked=len(current_symbols))

        except Exception as e:
            logger.error("Failed to sync wheel state with positions",
                        event_category="error", event_type="position_sync_failed",
                        error=str(e))

    def _extract_underlying_from_option_symbol(self, option_symbol: str) -> Optional[str]:
        """Extract underlying stock symbol from option symbol.

        Delegates to the shared parse_option_symbol() utility.

        Args:
            option_symbol: Full option symbol

        Returns:
            Underlying stock symbol or None
        """
        parsed = parse_option_symbol(option_symbol)
        underlying = parsed.get('underlying')
        return underlying if underlying else None

    def _get_stock_position_for_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get stock position data for a specific symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Stock position data or None
        """
        try:
            positions = self.alpaca.get_positions()
            stock_positions = [p for p in positions
                             if p['symbol'] == symbol and p['asset_class'] == 'us_equity']

            if stock_positions and float(stock_positions[0]['qty']) > 0:
                return stock_positions[0]
            return None

        except Exception as e:
            logger.error("Failed to get stock position",
                        event_category="error", event_type="stock_position_failed",
                        symbol=symbol, error=str(e))
            return None

    def _log_daily_stock_snapshots(self):
        """Log unrealized P&L snapshot for each stock position.

        This logs daily snapshots to track stock ownership gains/losses
        while holding positions from put assignments.
        """
        for symbol, state in self.wheel_state.symbol_states.items():
            if state.get('stock_shares', 0) > 0:
                try:
                    # Get current price from market data
                    stock_metrics = self.market_data.get_stock_metrics(symbol)
                    if not stock_metrics:
                        logger.warning("Could not get stock metrics for snapshot",
                                      event_category="error", event_type="stock_metrics_failed",
                                      symbol=symbol)
                        continue

                    current_price = stock_metrics.get('current_price', 0)
                    cost_basis = state.get('stock_cost_basis', 0)
                    shares = state['stock_shares']
                    acquisition_date = state.get('acquisition_date')

                    if cost_basis > 0 and current_price > 0:
                        unrealized_pl = (current_price - cost_basis) * shares
                        unrealized_pl_pct = (current_price - cost_basis) / cost_basis

                        # Calculate days held
                        days_held = 0
                        if acquisition_date:
                            days_held = (datetime.now() - acquisition_date).days

                        log_position_update(
                            logger,
                            event_type="daily_stock_snapshot",
                            symbol=symbol,
                            shares=shares,
                            cost_basis=cost_basis,
                            current_price=current_price,
                            unrealized_pl=unrealized_pl,
                            unrealized_pl_pct=unrealized_pl_pct,
                            days_held=days_held,
                        )

                        logger.info("Daily stock snapshot logged",
                                   event_category="data", event_type="daily_snapshot_logged",
                                   symbol=symbol,
                                   shares=shares,
                                   cost_basis=cost_basis,
                                   current_price=current_price,
                                   unrealized_pl=unrealized_pl,
                                   unrealized_pl_pct=f"{unrealized_pl_pct:.2%}",
                                   days_held=days_held)

                except Exception as e:
                    logger.error("Failed to log daily stock snapshot",
                                event_category="error", event_type="daily_snapshot_failed",
                                symbol=symbol,
                                error=str(e))

    def poll_order_statuses(self) -> Dict[str, Any]:
        """Poll recent orders and log status updates for filled/expired orders.

        This method checks all orders from the last 7 days and logs status
        updates for orders that have transitioned to final states (filled,
        expired, canceled). This enables the dashboard to show accurate
        order statuses instead of just "Accepted".

        Returns:
            Summary of orders polled and status updates logged
        """
        try:
            logger.info("Starting order status polling job",
                       event_category="system",
                       event_type="order_poll_started")

            # Get all orders (Alpaca returns recent orders by default)
            all_orders = self.alpaca.get_orders()

            # Also check closed/filled orders
            try:
                # Use the trading client directly to get closed orders
                from alpaca.trading.enums import QueryOrderStatus
                closed_orders = self.alpaca.trading_client.get_orders(
                    filter=alpaca.trading.requests.GetOrdersRequest(
                        status=QueryOrderStatus.CLOSED,
                        limit=100
                    )
                )
            except Exception as e:
                logger.debug("Could not fetch closed orders directly, using all_orders",
                           event_category="error", event_type="closed_orders_failed",
                           error=str(e))
                closed_orders = []

            # Track statistics
            stats = {
                'orders_checked': 0,
                'filled_logged': 0,
                'expired_logged': 0,
                'canceled_logged': 0,
                'errors': 0
            }

            # Process orders from get_orders
            for order in all_orders:
                try:
                    stats['orders_checked'] += 1
                    order_id = str(order.get('order_id', ''))
                    status = order.get('status', '').lower()
                    symbol = order.get('symbol', '')

                    # Only log final states
                    if status == 'filled':
                        # Extract underlying from option symbol
                        underlying = self._extract_underlying_from_option_symbol(symbol)
                        # Determine strategy from option type
                        strategy = 'sell_put' if 'P' in symbol else 'sell_call' if 'C' in symbol else 'unknown'

                        log_order_status_update(
                            logger,
                            event_type="order_filled",
                            order_id=order_id,
                            symbol=symbol,
                            status=status,
                            underlying=underlying or symbol,
                            strategy=strategy,
                            filled_qty=order.get('filled_qty', 0),
                            filled_avg_price=order.get('filled_avg_price'),
                            filled_at=str(order.get('filled_at', ''))
                        )
                        stats['filled_logged'] += 1

                    elif status == 'expired':
                        underlying = self._extract_underlying_from_option_symbol(symbol)
                        strategy = 'sell_put' if 'P' in symbol else 'sell_call' if 'C' in symbol else 'unknown'

                        log_order_status_update(
                            logger,
                            event_type="order_expired",
                            order_id=order_id,
                            symbol=symbol,
                            status=status,
                            underlying=underlying or symbol,
                            strategy=strategy
                        )
                        stats['expired_logged'] += 1

                    elif status in ('canceled', 'cancelled'):
                        underlying = self._extract_underlying_from_option_symbol(symbol)
                        strategy = 'sell_put' if 'P' in symbol else 'sell_call' if 'C' in symbol else 'unknown'

                        log_order_status_update(
                            logger,
                            event_type="order_canceled",
                            order_id=order_id,
                            symbol=symbol,
                            status=status,
                            underlying=underlying or symbol,
                            strategy=strategy
                        )
                        stats['canceled_logged'] += 1

                except Exception as order_error:
                    logger.warning("Failed to process order status",
                                  event_category="error", event_type="order_status_failed",
                                  order=order,
                                  error=str(order_error))
                    stats['errors'] += 1

            logger.info("Order status polling completed",
                       event_category="system",
                       event_type="order_poll_completed",
                       **stats)

            return stats

        except Exception as e:
            logger.error("Order status polling failed",
                        event_category="error",
                        event_type="order_poll_error",
                        error=str(e))
            return {'error': str(e)}

    def reconcile_positions(self) -> Dict[str, Any]:
        """Reconcile tracked wheel state against actual Alpaca positions.

        Alpaca is the source of truth. This method fetches real positions,
        compares them against the wheel state manager's tracked state, logs
        any discrepancies as warnings, and updates the state manager to
        match reality.

        Returns:
            Summary of reconciliation actions taken
        """
        try:
            logger.info("Starting position reconciliation",
                       event_category="system",
                       event_type="reconciliation_started")

            stats = {
                'stock_positions_alpaca': 0,
                'option_positions_alpaca': 0,
                'symbols_in_state': len(self.wheel_state.symbol_states),
                'discrepancies_found': 0,
                'state_updates': 0,
                'orphaned_state_entries_cleared': 0,
            }

            # --- Fetch actual positions from Alpaca ---
            all_positions = self.alpaca.get_positions()
            # Intentionally not using get_stock_positions() here — reconciliation
            # needs all stock positions including qty=0 to detect closed positions
            stock_positions = [p for p in all_positions if p.get('asset_class') == 'us_equity']
            option_positions = [p for p in all_positions if p.get('asset_class') == 'us_option']

            stats['stock_positions_alpaca'] = len(stock_positions)
            stats['option_positions_alpaca'] = len(option_positions)

            # Build maps of what Alpaca actually holds
            alpaca_stock_shares: Dict[str, int] = {}
            for pos in stock_positions:
                symbol = pos['symbol']
                shares = int(float(pos['qty']))
                if shares > 0:
                    alpaca_stock_shares[symbol] = shares

            alpaca_option_counts: Dict[str, Dict[str, int]] = {}  # symbol -> {'puts': n, 'calls': n}
            for pos in option_positions:
                option_symbol = pos['symbol']
                qty = int(float(pos['qty']))
                underlying = self._extract_underlying_from_option_symbol(option_symbol)
                if not underlying:
                    continue
                if underlying not in alpaca_option_counts:
                    alpaca_option_counts[underlying] = {'puts': 0, 'calls': 0}
                # Short positions have negative qty
                contracts = abs(qty)
                if 'P' in option_symbol:
                    alpaca_option_counts[underlying]['puts'] += contracts
                elif 'C' in option_symbol:
                    alpaca_option_counts[underlying]['calls'] += contracts

            # --- Compare Alpaca state vs wheel state and reconcile ---

            # 1. Check each symbol tracked in wheel state
            all_tracked_symbols = set(self.wheel_state.symbol_states.keys())
            all_alpaca_symbols = set(alpaca_stock_shares.keys()) | set(alpaca_option_counts.keys())

            for symbol in all_tracked_symbols:
                state_summary = self.wheel_state.get_position_summary(symbol)
                tracked_shares = state_summary['stock_shares']
                tracked_puts = state_summary['active_puts']
                tracked_calls = state_summary['active_calls']

                actual_shares = alpaca_stock_shares.get(symbol, 0)
                actual_opts = alpaca_option_counts.get(symbol, {'puts': 0, 'calls': 0})
                actual_puts = actual_opts['puts']
                actual_calls = actual_opts['calls']

                # Check for stock share discrepancy
                if tracked_shares != actual_shares:
                    stats['discrepancies_found'] += 1
                    logger.warning("Stock share discrepancy detected",
                                  event_category="reconciliation",
                                  event_type="stock_share_mismatch",
                                  symbol=symbol,
                                  tracked_shares=tracked_shares,
                                  actual_shares=actual_shares)
                    log_system_event(
                        logger,
                        event_type="reconciliation_stock_mismatch",
                        status="corrected",
                        symbol=symbol,
                        tracked_shares=tracked_shares,
                        actual_shares=actual_shares)
                    # Update state to match Alpaca
                    self.wheel_state.symbol_states[symbol]['stock_shares'] = actual_shares
                    stats['state_updates'] += 1

                # Check for put count discrepancy
                if tracked_puts != actual_puts:
                    stats['discrepancies_found'] += 1
                    logger.warning("Active puts discrepancy detected",
                                  event_category="reconciliation",
                                  event_type="active_puts_mismatch",
                                  symbol=symbol,
                                  tracked_puts=tracked_puts,
                                  actual_puts=actual_puts)
                    log_system_event(
                        logger,
                        event_type="reconciliation_puts_mismatch",
                        status="corrected",
                        symbol=symbol,
                        tracked_puts=tracked_puts,
                        actual_puts=actual_puts)
                    self.wheel_state.symbol_states[symbol]['active_puts'] = actual_puts
                    stats['state_updates'] += 1

                # Check for call count discrepancy
                if tracked_calls != actual_calls:
                    stats['discrepancies_found'] += 1
                    logger.warning("Active calls discrepancy detected",
                                  event_category="reconciliation",
                                  event_type="active_calls_mismatch",
                                  symbol=symbol,
                                  tracked_calls=tracked_calls,
                                  actual_calls=actual_calls)
                    log_system_event(
                        logger,
                        event_type="reconciliation_calls_mismatch",
                        status="corrected",
                        symbol=symbol,
                        tracked_calls=tracked_calls,
                        actual_calls=actual_calls)
                    self.wheel_state.symbol_states[symbol]['active_calls'] = actual_calls
                    stats['state_updates'] += 1

            # 2. Check for positions in Alpaca not tracked in wheel state
            for symbol in all_alpaca_symbols - all_tracked_symbols:
                stats['discrepancies_found'] += 1
                actual_shares = alpaca_stock_shares.get(symbol, 0)
                actual_opts = alpaca_option_counts.get(symbol, {'puts': 0, 'calls': 0})

                logger.warning("Position exists in Alpaca but not in wheel state — adding",
                              event_category="reconciliation",
                              event_type="untracked_position_found",
                              symbol=symbol,
                              shares=actual_shares,
                              puts=actual_opts['puts'],
                              calls=actual_opts['calls'])
                log_system_event(
                    logger,
                    event_type="reconciliation_untracked_position",
                    status="added",
                    symbol=symbol,
                    shares=actual_shares,
                    puts=actual_opts['puts'],
                    calls=actual_opts['calls'])

                self.wheel_state.symbol_states[symbol] = {
                    'stock_shares': actual_shares,
                    'stock_cost_basis': 0.0,
                    'acquisition_date': None,
                    'active_puts': actual_opts['puts'],
                    'active_calls': actual_opts['calls'],
                    'wheel_cycle_start': None,
                    'total_premium_collected': 0.0,
                    'put_premium_collected': 0.0,
                    'call_premium_collected': 0.0,
                }
                stats['state_updates'] += 1

            # 3. Clear state entries that have no Alpaca position at all
            for symbol in all_tracked_symbols - all_alpaca_symbols:
                state_summary = self.wheel_state.get_position_summary(symbol)
                has_anything = (state_summary['stock_shares'] > 0
                                or state_summary['active_puts'] > 0
                                or state_summary['active_calls'] > 0)
                if has_anything:
                    stats['discrepancies_found'] += 1
                    logger.warning("Position tracked in wheel state but absent from Alpaca — clearing",
                                  event_category="reconciliation",
                                  event_type="stale_state_entry",
                                  symbol=symbol,
                                  tracked_shares=state_summary['stock_shares'],
                                  tracked_puts=state_summary['active_puts'],
                                  tracked_calls=state_summary['active_calls'])
                    log_system_event(
                        logger,
                        event_type="reconciliation_stale_state_cleared",
                        status="cleared",
                        symbol=symbol)
                    self.wheel_state.symbol_states[symbol]['stock_shares'] = 0
                    self.wheel_state.symbol_states[symbol]['active_puts'] = 0
                    self.wheel_state.symbol_states[symbol]['active_calls'] = 0
                    stats['orphaned_state_entries_cleared'] += 1
                    stats['state_updates'] += 1

            logger.info("Position reconciliation completed",
                       event_category="system",
                       event_type="reconciliation_completed",
                       **stats)

            # Persist reconciled state to GCS
            self.wheel_state._save_state()

            return stats

        except Exception as e:
            logger.error("Position reconciliation failed",
                        event_category="error",
                        event_type="reconciliation_error",
                        error=str(e))
            return {'error': str(e)}