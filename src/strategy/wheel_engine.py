"""Core options wheel strategy engine."""

from typing import Dict, List, Any, Optional
from datetime import datetime
import structlog

from ..api.alpaca_client import AlpacaClient
from ..api.market_data import MarketDataManager
from ..risk.gap_detector import GapDetector
from ..utils.config import Config
from ..utils.logging_events import log_system_event, log_performance_metric, log_error_event
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
        self.wheel_state = WheelStateManager()

        logger.info("Wheel engine initialized with state management")
    
    def run_strategy_cycle(self) -> Dict[str, Any]:
        """Run one complete cycle of the wheel strategy.

        Returns:
            Summary of actions taken
        """
        start_time = datetime.now()
        logger.info("Starting strategy cycle")

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
        stock_positions = [p for p in positions if p['asset_class'] == 'us_equity']
        option_positions = [p for p in positions if p['asset_class'] == 'us_option']
        
        # Handle assigned stock positions (from put assignment)
        for stock_pos in stock_positions:
            if float(stock_pos['qty']) > 0:  # Long stock position
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
                       current=len(option_positions), 
                       max_allowed=self.config.max_total_positions)
            return False
        
        # Check portfolio allocation
        account_info = self.alpaca.get_account()
        buying_power = float(account_info['buying_power'])
        
        if buying_power < 1000:  # Minimum buying power threshold
            logger.info("Insufficient buying power", buying_power=buying_power)
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
                       suitable_stocks=len(suitable_stocks),
                       gap_filtered_stocks=len(gap_filtered_stocks),
                       gap_filtered_symbols=gap_filtered_symbols,
                       filtered_out_symbols=filtered_out)

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

            # Process each stock according to wheel strategy phases
            for stock in gap_filtered_stocks:  # Evaluate all gap-filtered stocks
                symbol = stock['symbol']
                wheel_phase = self.wheel_state.get_wheel_phase(symbol)

                # Check execution gap before proceeding
                execution_check = self.gap_detector.can_execute_trade(symbol, datetime.now())
                if not execution_check['can_execute']:
                    logger.info("Trade execution blocked by gap check",
                               symbol=symbol,
                               reason=execution_check['reason'],
                               gap_percent=execution_check.get('current_gap_percent', 0))
                    continue

                # Prioritize covered calls over puts when holding stock
                opportunity_found = False

                # 1. If holding stock, prioritize covered calls
                if self.wheel_state.can_sell_calls(symbol):
                    call_opportunity = self.call_seller.evaluate_covered_call_opportunity(
                        self._get_stock_position_for_symbol(symbol)
                    )
                    if call_opportunity:
                        call_opportunity['gap_check'] = execution_check
                        actions.append(call_opportunity)
                        opportunity_found = True
                        logger.info("Covered call opportunity found",
                                   symbol=symbol,
                                   wheel_phase=wheel_phase.value)

                # 2. Only look for puts if no stock position (proper wheel logic)
                if not opportunity_found and self.wheel_state.can_sell_puts(symbol):
                    # Check if we already have option positions in this stock
                    if self._has_existing_option_position(symbol):
                        continue

                    put_opportunity = self.put_seller.find_put_opportunity(symbol, self.wheel_state)
                    if put_opportunity:
                        put_opportunity['gap_check'] = execution_check
                        actions.append(put_opportunity)
                        opportunity_found = True
                        logger.info("Put selling opportunity found",
                                   symbol=symbol,
                                   wheel_phase=wheel_phase.value)

                # No limit on positions per cycle - let other risk controls manage portfolio

        except Exception as e:
            logger.error("Failed to find new opportunities", error=str(e))

        # Log summary of opportunities found
        logger.info("New opportunities search completed",
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
                        symbol=underlying_symbol, error=str(e))
            return True  # Be conservative and assume we have positions

    def _has_existing_option_position(self, underlying_symbol: str) -> bool:
        """Check if we already have option positions in a given underlying stock.

        Args:
            underlying_symbol: Stock symbol to check

        Returns:
            True if we have existing option positions
        """
        try:
            positions = self.alpaca.get_positions()

            # Check for option positions on this underlying
            option_positions = [p for p in positions
                              if p['asset_class'] == 'us_option' and underlying_symbol in p['symbol']]

            return len(option_positions) > 0

        except Exception as e:
            logger.error("Failed to check existing option positions",
                        symbol=underlying_symbol, error=str(e))
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
            stock_positions = [p for p in positions if p['asset_class'] == 'us_equity']
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
            logger.error("Failed to get strategy status", error=str(e))
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
            stock_positions = [p for p in positions if p['asset_class'] == 'us_equity']
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
                        symbols_tracked=len(current_symbols))

        except Exception as e:
            logger.error("Failed to sync wheel state with positions", error=str(e))

    def _extract_underlying_from_option_symbol(self, option_symbol: str) -> Optional[str]:
        """Extract underlying stock symbol from option symbol.

        Args:
            option_symbol: Full option symbol

        Returns:
            Underlying stock symbol or None
        """
        try:
            # Simple extraction - assumes format like "AAPL250117C00150000"
            # Find the last letter before the date (P or C)
            for i, char in enumerate(option_symbol):
                if char.isdigit():
                    return option_symbol[:i]
            return None
        except Exception:
            return None

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
            logger.error("Failed to get stock position", symbol=symbol, error=str(e))
            return None