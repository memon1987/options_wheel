"""Put selling module for options wheel strategy."""

from typing import Dict, List, Any, Optional
from datetime import datetime
import structlog

from ..api.alpaca_client import AlpacaClient
from ..api.market_data import MarketDataManager
from ..utils.config import Config
from ..utils.logging_events import log_trade_event, log_error_event, log_risk_event

logger = structlog.get_logger(__name__)


class PutSeller:
    """Handles cash-secured put selling for the wheel strategy."""
    
    def __init__(self, alpaca_client: AlpacaClient, market_data: MarketDataManager, config: Config):
        """Initialize put seller.
        
        Args:
            alpaca_client: Alpaca API client
            market_data: Market data manager
            config: Configuration instance
        """
        self.alpaca = alpaca_client
        self.market_data = market_data
        self.config = config
        
    def find_put_opportunity(self, symbol: str, wheel_state_manager=None) -> Optional[Dict[str, Any]]:
        """Find the best put selling opportunity for a stock.

        Args:
            symbol: Stock symbol
            wheel_state_manager: Optional wheel state manager for validation

        Returns:
            Put opportunity details or None
        """
        try:
            logger.info("Evaluating put opportunity", symbol=symbol)

            # Check wheel state if manager provided
            if wheel_state_manager and not wheel_state_manager.can_sell_puts(symbol):
                logger.info("Put selling blocked by wheel state",
                           symbol=symbol,
                           wheel_phase=wheel_state_manager.get_wheel_phase(symbol).value)
                return None
            
            # Get suitable puts for this stock
            suitable_puts = self.market_data.find_suitable_puts(symbol)
            
            if not suitable_puts:
                logger.info("No suitable puts found", symbol=symbol)
                return None
            
            # Select the best put (first in sorted list)
            best_put = suitable_puts[0]
            
            # Calculate position size and validate
            position_details = self._calculate_position_size(best_put)
            
            if not position_details:
                logger.info("Position size validation failed", symbol=symbol)
                return None
            
            # Create opportunity
            opportunity = {
                'action_type': 'new_position',
                'strategy': 'sell_put',
                'symbol': symbol,
                'option_symbol': best_put['symbol'],
                'strike_price': best_put['strike_price'],
                'expiration_date': best_put['expiration_date'],
                'dte': best_put['dte'],
                'delta': best_put.get('delta', 0),
                'premium': best_put['mid_price'],
                'annual_return': best_put.get('annual_return', 0),
                'contracts': position_details['contracts'],
                'capital_required': position_details['capital_required'],
                'max_profit': position_details['max_profit'],
                'breakeven': position_details['breakeven'],
                'timestamp': datetime.now().isoformat()
            }
            
            logger.info("Put opportunity identified", 
                       symbol=symbol,
                       strike=best_put['strike_price'],
                       premium=best_put['mid_price'],
                       dte=best_put['dte'],
                       contracts=position_details['contracts'])
            
            return opportunity
            
        except Exception as e:
            logger.error("Failed to find put opportunity", symbol=symbol, error=str(e))
            return None
    
    def _calculate_position_size(self, put_option: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Calculate appropriate position size for put selling.
        
        Args:
            put_option: Put option details
            
        Returns:
            Position sizing details or None if invalid
        """
        try:
            # Get account info
            account_info = self.alpaca.get_account()
            portfolio_value = float(account_info['portfolio_value'])
            # Use options_buying_power for options trading (more accurate for options margin)
            # Fall back to regular buying_power if not available
            buying_power = float(account_info.get('options_buying_power') or account_info['buying_power'])
            
            # Calculate maximum position size based on portfolio allocation
            max_position_value = portfolio_value * self.config.max_position_size
            
            # Calculate capital required per contract (strike price * 100)
            strike_price = put_option['strike_price']
            capital_per_contract = strike_price * 100
            
            # Calculate maximum contracts based on position size limit
            max_contracts_by_position = int(max_position_value // capital_per_contract)
            
            # Calculate maximum contracts based on available buying power
            max_contracts_by_buying_power = int(buying_power // capital_per_contract)
            
            # Take the minimum to ensure we don't exceed limits
            max_contracts = min(max_contracts_by_position, max_contracts_by_buying_power, 10)  # Cap at 10 contracts

            logger.info("STAGE 8: Position sizing calculation",
                       event_category="filtering",
                       event_type="stage_8_calculation",
                       symbol=put_option['symbol'],
                       strike=strike_price,
                       portfolio_value=portfolio_value,
                       buying_power=buying_power,
                       capital_per_contract=capital_per_contract,
                       max_by_position=max_contracts_by_position,
                       max_by_buying_power=max_contracts_by_buying_power,
                       max_contracts_allowed=max_contracts)

            if max_contracts <= 0:
                logger.warning("STAGE 8 BLOCKED: Position sizing - insufficient capital",
                              event_category="filtering",
                              event_type="stage_8_blocked",
                              strike=strike_price,
                              capital_per_contract=capital_per_contract,
                              buying_power=buying_power,
                              reason="max_contracts_zero")
                return None

            # Conservative sizing - start with 1 contract for new positions
            contracts = 1
            
            # Calculate metrics
            capital_required = contracts * capital_per_contract
            premium_per_contract = put_option['mid_price']
            max_profit = contracts * premium_per_contract * 100  # Premium collected
            breakeven = strike_price - premium_per_contract
            
            # Validate against risk limits
            portfolio_allocation = capital_required / portfolio_value
            if portfolio_allocation > self.config.max_position_size:
                logger.warning("STAGE 8 BLOCKED: Position size exceeds allocation limit",
                              event_category="filtering",
                              event_type="stage_8_blocked",
                              allocation=portfolio_allocation,
                              max_allowed=self.config.max_position_size,
                              reason="portfolio_allocation_exceeded")
                return None

            logger.info("STAGE 8 PASSED: Position sizing approved",
                       event_category="filtering",
                       event_type="stage_8_passed",
                       symbol=put_option['symbol'],
                       contracts=contracts,
                       capital_required=capital_required,
                       portfolio_allocation=round(portfolio_allocation, 3),
                       max_profit=max_profit)

            return {
                'contracts': contracts,
                'capital_required': capital_required,
                'max_profit': max_profit,
                'breakeven': breakeven,
                'portfolio_allocation': portfolio_allocation,
                'premium_per_contract': premium_per_contract
            }
            
        except Exception as e:
            logger.error("Failed to calculate position size", error=str(e))
            return None
    
    def execute_put_sale(self, opportunity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Execute a put selling trade.

        Args:
            opportunity: Put opportunity details

        Returns:
            Trade execution result
        """
        try:
            option_symbol = opportunity['option_symbol']
            contracts = opportunity['contracts']
            premium = opportunity['premium']
            strike_price = opportunity.get('strike_price', 0)

            # CRITICAL: Validate buying power before placing order
            collateral_required = strike_price * 100 * contracts  # Cash-secured put

            try:
                account = self.alpaca.get_account()
                available_bp = account.get('options_buying_power', 0)

                if collateral_required > available_bp:
                    # Enhanced error logging for BigQuery analytics
                    log_error_event(
                        logger,
                        error_type="insufficient_buying_power",
                        error_message=f'Need ${collateral_required:,.2f} but only ${available_bp:,.2f} available',
                        component="put_seller",
                        recoverable=True,
                        symbol=option_symbol,
                        underlying=opportunity.get('symbol', ''),
                        required=collateral_required,
                        available=available_bp,
                        shortage=collateral_required - available_bp
                    )
                    return {
                        'success': False,
                        'error': 'insufficient_buying_power',
                        'message': f'Need ${collateral_required:,.2f} but only ${available_bp:,.2f} available',
                        'symbol': option_symbol,
                        'timestamp': datetime.now().isoformat()
                    }

                logger.info("Buying power check passed",
                           required=collateral_required,
                           available=available_bp,
                           margin=available_bp - collateral_required)

            except Exception as bp_error:
                logger.error("Failed to check buying power", error=str(bp_error))
                # Continue anyway - let Alpaca reject if needed

            # Calculate limit price: mid + 10% of spread (biased toward ask for premium collection)
            bid = opportunity.get('bid')
            ask = opportunity.get('ask')

            if bid and ask:
                spread = ask - bid
                limit_price = round(premium + (spread * 0.10), 2)
            else:
                # Fallback if bid/ask not available
                limit_price = round(premium * 0.95, 2)

            logger.info("Executing put sale",
                       symbol=option_symbol,
                       contracts=contracts,
                       premium=premium,
                       bid=bid,
                       ask=ask,
                       spread=round(ask - bid, 2) if bid and ask else None,
                       limit_price=limit_price,
                       collateral_required=collateral_required)

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
                # Order placed successfully
                result = {
                    'success': True,
                    'order_id': order_result.get('order_id'),
                    'symbol': option_symbol,
                    'contracts': contracts,
                    'limit_price': limit_price,
                    'strategy': 'sell_put',
                    'timestamp': datetime.now().isoformat()
                }

                # Enhanced logging for BigQuery analytics
                log_trade_event(
                    logger,
                    event_type="put_sale_executed",
                    symbol=option_symbol,
                    underlying=opportunity.get('symbol', ''),
                    strategy="sell_put",
                    success=True,
                    strike_price=strike_price,
                    premium=premium,
                    contracts=contracts,
                    limit_price=limit_price,
                    order_id=order_result.get('order_id'),
                    collateral_required=collateral_required,
                    dte=opportunity.get('dte', 0)
                )

                return result

            else:
                # Order failed - return structured error
                error_type = order_result.get('error_type', 'unknown') if order_result else 'unknown'
                error_msg = order_result.get('error_message', 'Unknown error') if order_result else 'No result returned'

                # Enhanced error logging for BigQuery analytics
                log_error_event(
                    logger,
                    error_type=error_type,
                    error_message=error_msg,
                    component="put_seller",
                    recoverable=True,
                    symbol=option_symbol,
                    underlying=opportunity.get('symbol', ''),
                    strike_price=strike_price,
                    contracts=contracts,
                    limit_price=limit_price
                )

                return {
                    'success': False,
                    'error': error_type,
                    'message': error_msg,
                    'symbol': option_symbol,
                    'strategy': 'sell_put',
                    'timestamp': datetime.now().isoformat()
                }
                
        except Exception as e:
            # Enhanced error logging for BigQuery analytics
            log_error_event(
                logger,
                error_type="execution_exception",
                error_message=str(e),
                component="put_seller",
                recoverable=False,
                symbol=opportunity.get('option_symbol', ''),
                underlying=opportunity.get('symbol', '')
            )
            return None
    
    def evaluate_put_assignment(self, put_position: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate if a short put position might get assigned.
        
        Args:
            put_position: Short put position details
            
        Returns:
            Assignment evaluation
        """
        try:
            # Extract underlying symbol from option symbol
            # This would need proper parsing based on option symbol format
            underlying_symbol = put_position['symbol'].split()[0]  # Simplified extraction
            
            # Get current stock price
            stock_metrics = self.market_data.get_stock_metrics(underlying_symbol)
            current_price = stock_metrics.get('current_price', 0)
            
            # Extract strike price (this would need proper option symbol parsing)
            strike_price = 0  # Would extract from option symbol or position data
            
            assignment_risk = "low"
            if current_price <= strike_price * 1.02:  # Within 2% of strike
                assignment_risk = "high"
            elif current_price <= strike_price * 1.05:  # Within 5% of strike
                assignment_risk = "medium"
            
            return {
                'symbol': underlying_symbol,
                'current_price': current_price,
                'strike_price': strike_price,
                'assignment_risk': assignment_risk,
                'days_to_expiration': 0,  # Would calculate from expiration date
                'position_value': float(put_position['market_value'])
            }
            
        except Exception as e:
            logger.error("Failed to evaluate put assignment", error=str(e))
            return {'assignment_risk': 'unknown'}
    
    def should_close_put_early(self, put_position: Dict[str, Any], current_option_data: Dict[str, Any] = None) -> bool:
        """Determine if a short put should be closed early for profit or stop loss.
        
        Args:
            put_position: Short put position details
            current_option_data: Current option market data with delta, etc.
            
        Returns:
            True if position should be closed early
        """
        try:
            unrealized_pl = float(put_position['unrealized_pl'])
            position_value = abs(float(put_position['market_value']))
            
            # Profit target: If we've captured target % of the premium, consider closing
            if unrealized_pl > 0 and position_value > 0:
                profit_percentage = unrealized_pl / position_value
                
                if profit_percentage >= self.config.profit_target_percent:
                    logger.info("Put position reached profit target", 
                               symbol=put_position['symbol'],
                               profit_pct=profit_percentage)
                    return True
            
            # Stop loss logic for short-term options (disabled by default for puts)
            if self.config.use_put_stop_loss and unrealized_pl < 0:
                return self._check_put_stop_loss(put_position, current_option_data)
            
            return False
            
        except Exception as e:
            logger.error("Failed to evaluate early close", error=str(e))
            return False

    def _check_put_stop_loss(self, put_position: Dict[str, Any], current_option_data: Dict[str, Any] = None) -> bool:
        """Check if put position should be closed due to stop loss.
        
        Args:
            put_position: Put position details
            current_option_data: Current option market data
            
        Returns:
            True if stop loss should be triggered
        """
        try:
            unrealized_pl = float(put_position['unrealized_pl'])
            position_value = abs(float(put_position['market_value']))
            
            # Method 1: Traditional premium-based stop loss (adjusted for time decay)
            if position_value > 0:
                loss_percentage = abs(unrealized_pl) / position_value
                
                # For short-term options, use a higher threshold since time decay is expected
                stop_loss_threshold = self.config.put_stop_loss_percent * self.config.stop_loss_multiplier
                
                if loss_percentage >= stop_loss_threshold:
                    logger.warning("Put position hit premium stop loss", 
                                 symbol=put_position['symbol'],
                                 loss_pct=loss_percentage,
                                 threshold=stop_loss_threshold)
                    return True
            
            # Method 2: Delta-based stop loss (if current option data available)
            if current_option_data and 'delta' in current_option_data:
                current_delta = abs(current_option_data['delta'])
                
                # If delta has doubled, the underlying has moved significantly against us
                # This is more reliable than premium-based for short-term options
                if current_delta > 0.5:  # Delta > 0.5 means we're likely ITM
                    logger.warning("Put position hit delta stop loss", 
                                 symbol=put_position['symbol'],
                                 current_delta=current_delta)
                    return True
            
            # Method 3: Intrinsic value stop loss (if we can calculate it)
            # This would require current stock price and strike price parsing
            # For now, rely on methods 1 and 2
            
            return False
            
        except Exception as e:
            logger.error("Failed to check put stop loss", error=str(e))
            return False