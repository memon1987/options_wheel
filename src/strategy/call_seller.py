"""Call selling module for options wheel strategy."""

from typing import Dict, List, Any, Optional
from datetime import datetime
import structlog

from ..api.alpaca_client import AlpacaClient
from ..api.market_data import MarketDataManager
from ..utils.config import Config
from ..utils.logging_events import log_trade_event, log_error_event, log_position_update

logger = structlog.get_logger(__name__)


class CallSeller:
    """Handles covered call selling for the wheel strategy."""
    
    def __init__(self, alpaca_client: AlpacaClient, market_data: MarketDataManager, config: Config):
        """Initialize call seller.
        
        Args:
            alpaca_client: Alpaca API client
            market_data: Market data manager
            config: Configuration instance
        """
        self.alpaca = alpaca_client
        self.market_data = market_data
        self.config = config
        
    def evaluate_covered_call_opportunity(self, stock_position: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Evaluate covered call opportunity for an assigned stock position.
        
        Args:
            stock_position: Stock position from assignment
            
        Returns:
            Call opportunity details or None
        """
        try:
            symbol = stock_position['symbol']
            shares_owned = int(float(stock_position['qty']))
            
            # Only sell calls if we own shares in round lots (100 shares per contract)
            if shares_owned < 100:
                logger.info("Insufficient shares for covered calls", 
                           symbol=symbol, shares=shares_owned)
                return None
            
            logger.info("Evaluating covered call opportunity", 
                       symbol=symbol, shares=shares_owned)
            
            # Get cost basis per share for filtering
            stock_cost_basis = float(stock_position['cost_basis']) / shares_owned

            # Get suitable calls for this stock (with cost basis protection)
            suitable_calls = self.market_data.find_suitable_calls(symbol, min_strike_price=stock_cost_basis)
            
            if not suitable_calls:
                logger.info("No suitable calls found", symbol=symbol)
                return None
            
            # Select the best call (first in sorted list)
            best_call = suitable_calls[0]
            
            # Calculate position details
            position_details = self._calculate_call_position(best_call, shares_owned, stock_position)
            
            if not position_details:
                logger.info("Call position validation failed", symbol=symbol)
                return None
            
            # Create opportunity
            opportunity = {
                'action_type': 'new_position',
                'strategy': 'sell_call',
                'symbol': symbol,
                'option_symbol': best_call['symbol'],
                'strike_price': best_call['strike_price'],
                'expiration_date': best_call['expiration_date'],
                'dte': best_call['dte'],
                'delta': best_call.get('delta', 0),
                'premium': best_call['mid_price'],
                'annual_return': best_call.get('annual_return', 0),
                'contracts': position_details['contracts'],
                'shares_covered': position_details['shares_covered'],
                'max_profit': position_details['max_profit'],
                'stock_cost_basis': float(stock_position['cost_basis']),
                'current_stock_price': position_details['current_stock_price'],
                'total_return_if_called': position_details['total_return_if_called'],
                'timestamp': datetime.now().isoformat()
            }
            
            logger.info("Covered call opportunity identified", 
                       symbol=symbol,
                       strike=best_call['strike_price'],
                       premium=best_call['mid_price'],
                       dte=best_call['dte'],
                       contracts=position_details['contracts'])
            
            return opportunity
            
        except Exception as e:
            logger.error("Failed to evaluate covered call opportunity", 
                        symbol=stock_position.get('symbol', 'unknown'), error=str(e))
            return None
    
    def _calculate_call_position(self, call_option: Dict[str, Any], shares_owned: int, 
                                stock_position: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Calculate covered call position details.
        
        Args:
            call_option: Call option details
            shares_owned: Number of shares owned
            stock_position: Stock position details
            
        Returns:
            Position details or None if invalid
        """
        try:
            # Calculate number of contracts we can sell (1 contract = 100 shares)
            max_contracts = shares_owned // 100
            
            # Conservative approach - sell calls on all round lots
            contracts = max_contracts
            
            if contracts <= 0:
                return None
            
            shares_covered = contracts * 100
            strike_price = call_option['strike_price']
            premium_per_contract = call_option['mid_price']
            
            # Get current stock price
            symbol = stock_position['symbol']
            stock_metrics = self.market_data.get_stock_metrics(symbol)
            current_price = stock_metrics.get('current_price', 0)
            
            # Calculate returns
            premium_income = contracts * premium_per_contract * 100
            stock_cost_basis = float(stock_position['cost_basis']) / shares_owned  # Cost per share
            
            # If called away, calculate total return
            if current_price > 0:
                capital_gain_per_share = strike_price - stock_cost_basis
                total_capital_gain = capital_gain_per_share * shares_covered
                total_return_if_called = premium_income + total_capital_gain
                
                # Return as percentage
                total_cost_basis = stock_cost_basis * shares_covered
                if total_cost_basis > 0:
                    return_percentage = (total_return_if_called / total_cost_basis) * 100
                else:
                    return_percentage = 0
            else:
                total_return_if_called = premium_income
                return_percentage = 0
            
            return {
                'contracts': contracts,
                'shares_covered': shares_covered,
                'max_profit': premium_income,
                'current_stock_price': current_price,
                'total_return_if_called': total_return_if_called,
                'return_percentage': return_percentage,
                'premium_per_contract': premium_per_contract
            }
            
        except Exception as e:
            logger.error("Failed to calculate call position", error=str(e))
            return None
    
    def execute_call_sale(self, opportunity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Execute a covered call trade.
        
        Args:
            opportunity: Call opportunity details
            
        Returns:
            Trade execution result
        """
        try:
            option_symbol = opportunity['option_symbol']
            contracts = opportunity['contracts']
            premium = opportunity['premium']
            
            # Calculate limit price (slightly below mid to improve fill probability)
            limit_price = round(premium * 0.95, 2)  # 5% below mid price
            
            logger.info("Executing covered call sale", 
                       symbol=option_symbol,
                       contracts=contracts,
                       limit_price=limit_price)
            
            # Place the sell order
            order_result = self.alpaca.place_option_order(
                symbol=option_symbol,
                qty=contracts,
                side='sell',
                order_type='limit',
                limit_price=limit_price
            )

            # Handle order result (success or structured error)
            if order_result and order_result.get('success', True):
                result = {
                    'success': True,
                    'order_id': order_result.get('order_id'),
                    'symbol': option_symbol,
                    'contracts': contracts,
                    'limit_price': limit_price,
                    'strategy': 'sell_call',
                    'timestamp': datetime.now().isoformat()
                }

                # Enhanced logging for BigQuery analytics
                log_trade_event(
                    logger,
                    event_type="call_sale_executed",
                    symbol=option_symbol,
                    underlying=opportunity.get('symbol', ''),
                    strategy="sell_call",
                    success=True,
                    strike_price=opportunity.get('strike_price', 0),
                    premium=premium,
                    contracts=contracts,
                    limit_price=limit_price,
                    order_id=order_result.get('order_id'),
                    shares_covered=opportunity.get('shares_covered', 0),
                    stock_cost_basis=opportunity.get('stock_cost_basis', 0),
                    total_return_if_called=opportunity.get('total_return_if_called', 0),
                    dte=opportunity.get('dte', 0)
                )

                return result
            else:
                # Order failed - return structured error
                error_type = order_result.get('error_type', 'unknown') if order_result else 'unknown'
                error_msg = order_result.get('error_message', 'Unknown error') if order_result else 'No result returned'

                # Enhanced error logging
                log_error_event(
                    logger,
                    error_type=error_type,
                    error_message=error_msg,
                    component="call_seller",
                    recoverable=True,
                    symbol=option_symbol,
                    underlying=opportunity.get('symbol', ''),
                    strike_price=opportunity.get('strike_price', 0),
                    contracts=contracts,
                    limit_price=limit_price
                )

                return None
                
        except Exception as e:
            # Enhanced error logging
            log_error_event(
                logger,
                error_type="execution_exception",
                error_message=str(e),
                component="call_seller",
                recoverable=False,
                symbol=opportunity.get('option_symbol', ''),
                underlying=opportunity.get('symbol', '')
            )
            return None
    
    def evaluate_call_assignment_risk(self, call_position: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate if a short call position might get assigned.
        
        Args:
            call_position: Short call position details
            
        Returns:
            Assignment evaluation
        """
        try:
            # Extract underlying symbol from option symbol
            # This would need proper parsing based on option symbol format
            underlying_symbol = call_position['symbol'].split()[0]  # Simplified extraction
            
            # Get current stock price
            stock_metrics = self.market_data.get_stock_metrics(underlying_symbol)
            current_price = stock_metrics.get('current_price', 0)
            
            # Extract strike price (this would need proper option symbol parsing)
            strike_price = 0  # Would extract from option symbol or position data
            
            assignment_risk = "low"
            if current_price >= strike_price * 0.98:  # Within 2% of strike (above)
                assignment_risk = "high"
            elif current_price >= strike_price * 0.95:  # Within 5% of strike
                assignment_risk = "medium"
            
            # Calculate potential profit/loss if assigned
            intrinsic_value = max(0, current_price - strike_price)
            
            return {
                'symbol': underlying_symbol,
                'current_price': current_price,
                'strike_price': strike_price,
                'assignment_risk': assignment_risk,
                'intrinsic_value': intrinsic_value,
                'days_to_expiration': 0,  # Would calculate from expiration date
                'position_value': float(call_position['market_value'])
            }
            
        except Exception as e:
            logger.error("Failed to evaluate call assignment", error=str(e))
            return {'assignment_risk': 'unknown'}
    
    def should_close_call_early(self, call_position: Dict[str, Any], current_option_data: Dict[str, Any] = None) -> bool:
        """Determine if a short call should be closed early for profit or stop loss.
        
        Args:
            call_position: Short call position details
            current_option_data: Current option market data with delta, etc.
            
        Returns:
            True if position should be closed early
        """
        try:
            unrealized_pl = float(call_position['unrealized_pl'])
            position_value = abs(float(call_position['market_value']))
            
            # Profit target: If we've captured target % of the premium, consider closing
            if unrealized_pl > 0 and position_value > 0:
                profit_percentage = unrealized_pl / position_value
                
                if profit_percentage >= self.config.profit_target_percent:
                    logger.info("Call position reached profit target", 
                               symbol=call_position['symbol'],
                               profit_pct=profit_percentage)
                    return True
            
            # Stop loss logic for short-term options (enabled for calls)
            if self.config.use_call_stop_loss and unrealized_pl < 0:
                return self._check_call_stop_loss(call_position, current_option_data)
            
            return False
            
        except Exception as e:
            logger.error("Failed to evaluate early close", error=str(e))
            return False

    def _check_call_stop_loss(self, call_position: Dict[str, Any], current_option_data: Dict[str, Any] = None) -> bool:
        """Check if call position should be closed due to stop loss.
        
        Args:
            call_position: Call position details
            current_option_data: Current option market data
            
        Returns:
            True if stop loss should be triggered
        """
        try:
            unrealized_pl = float(call_position['unrealized_pl'])
            position_value = abs(float(call_position['market_value']))
            
            # Method 1: Traditional premium-based stop loss (adjusted for time decay)
            if position_value > 0:
                loss_percentage = abs(unrealized_pl) / position_value
                
                # For short-term options, use a higher threshold since time decay is expected
                stop_loss_threshold = self.config.call_stop_loss_percent * self.config.stop_loss_multiplier
                
                if loss_percentage >= stop_loss_threshold:
                    logger.warning("Call position hit premium stop loss", 
                                 symbol=call_position['symbol'],
                                 loss_pct=loss_percentage,
                                 threshold=stop_loss_threshold)
                    return True
            
            # Method 2: Delta-based stop loss (if current option data available)
            if current_option_data and 'delta' in current_option_data:
                current_delta = abs(current_option_data['delta'])
                
                # If delta > 0.5, the call is likely ITM and stock moved significantly up
                if current_delta > 0.5:  # Delta > 0.5 means we're likely ITM
                    logger.warning("Call position hit delta stop loss", 
                                 symbol=call_position['symbol'],
                                 current_delta=current_delta)
                    return True
            
            return False
            
        except Exception as e:
            logger.error("Failed to check call stop loss", error=str(e))
            return False
    
    def handle_call_assignment(self, assignment_info: Dict[str, Any], wheel_state_manager=None) -> Dict[str, Any]:
        """Handle when a short call gets assigned (shares called away).

        Args:
            assignment_info: Assignment details
            wheel_state_manager: Optional wheel state manager for proper state transitions

        Returns:
            Assignment handling result with wheel state updates
        """
        try:
            symbol = assignment_info['symbol']
            shares_assigned = assignment_info.get('shares', 0)
            strike_price = assignment_info.get('strike_price', 0)
            assignment_date = assignment_info.get('date', datetime.now())

            logger.info("Handling call assignment",
                       symbol=symbol,
                       shares=shares_assigned,
                       strike=strike_price)

            # Update wheel state if manager provided
            wheel_result = None
            if wheel_state_manager:
                wheel_result = wheel_state_manager.handle_call_assignment(
                    symbol, shares_assigned, strike_price, assignment_date, assignment_info
                )

            # Calculate realized profit/loss
            # This would include the premium received plus capital gain/loss
            realized_pnl = 0.0
            if wheel_result and 'capital_gain' in wheel_result:
                realized_pnl = wheel_result['capital_gain']

            result = {
                'action_type': 'assignment_handled',
                'strategy': 'call_assignment',
                'symbol': symbol,
                'shares_assigned': shares_assigned,
                'assignment_price': strike_price,
                'realized_pnl': realized_pnl,
                'timestamp': assignment_date.isoformat(),
                'wheel_cycle_completed': wheel_result.get('wheel_cycle_completed', False) if wheel_result else False,
                'next_action': 'look_for_new_put_opportunity' if wheel_result and wheel_result.get('wheel_cycle_completed') else 'continue_wheel_strategy'
            }

            # Include wheel state information if available
            if wheel_result:
                result['wheel_state_transition'] = {
                    'phase_before': wheel_result.get('phase_before', {}).value if hasattr(wheel_result.get('phase_before', {}), 'value') else None,
                    'phase_after': wheel_result.get('phase_after', {}).value if hasattr(wheel_result.get('phase_after', {}), 'value') else None,
                    'remaining_shares': wheel_result.get('remaining_shares', 0)
                }

                if wheel_result.get('completed_cycle'):
                    result['completed_wheel_cycle'] = wheel_result['completed_cycle']

            logger.info("Call assignment handled with wheel state management",
                       symbol=symbol,
                       shares_assigned=shares_assigned,
                       wheel_cycle_completed=result['wheel_cycle_completed'],
                       next_phase=result.get('wheel_state_transition', {}).get('phase_after'))

            # Enhanced position update logging
            log_position_update(
                logger,
                event_type="call_assignment",
                symbol=symbol,
                position_type="call",
                action="assignment",
                shares=shares_assigned,
                assignment_price=strike_price,
                realized_pnl=realized_pnl,
                wheel_cycle_completed=result['wheel_cycle_completed'],
                phase_before=result.get('wheel_state_transition', {}).get('phase_before'),
                phase_after=result.get('wheel_state_transition', {}).get('phase_after')
            )

            return result

        except Exception as e:
            logger.error("Failed to handle call assignment", error=str(e))
            return {'error': str(e)}