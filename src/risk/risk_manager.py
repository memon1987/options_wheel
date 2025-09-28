"""Risk management system for options wheel strategy."""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import structlog

from ..utils.config import Config

logger = structlog.get_logger(__name__)


class RiskManager:
    """Comprehensive risk management for options wheel trading."""
    
    def __init__(self, config: Config):
        """Initialize risk manager.
        
        Args:
            config: Configuration instance
        """
        self.config = config
        
    def validate_new_position(self, opportunity: Dict[str, Any], 
                            account_info: Dict[str, Any], 
                            current_positions: List[Dict[str, Any]]) -> Tuple[bool, str]:
        """Validate if a new position meets risk criteria.
        
        Args:
            opportunity: Proposed position details
            account_info: Current account information
            current_positions: List of current positions
            
        Returns:
            Tuple of (is_valid, reason)
        """
        try:
            # 1. Portfolio allocation check
            portfolio_value = float(account_info['portfolio_value'])
            
            if opportunity['strategy'] == 'sell_put':
                capital_required = opportunity['capital_required']
            else:  # sell_call
                capital_required = 0  # Covered call doesn't require additional capital
            
            if capital_required > 0:
                position_allocation = capital_required / portfolio_value
                if position_allocation > self.config.max_position_size:
                    return False, f"Position allocation {position_allocation:.2%} exceeds limit {self.config.max_position_size:.2%}"
            
            # 2. Maximum positions check
            option_positions = [p for p in current_positions if p['asset_class'] == 'us_option']
            if len(option_positions) >= self.config.max_total_positions:
                return False, f"Maximum positions reached: {len(option_positions)}/{self.config.max_total_positions}"
            
            # 3. Concentration risk - max positions per stock
            underlying_symbol = opportunity['symbol']
            same_stock_positions = [p for p in current_positions 
                                  if underlying_symbol in p.get('symbol', '')]
            
            if len(same_stock_positions) >= self.config.max_positions_per_stock:
                return False, f"Maximum positions per stock reached for {underlying_symbol}"
            
            # 3.5. Maximum exposure per ticker check (total assignment value)
            current_exposure = 0.0
            
            # Calculate current exposure from existing positions for this ticker
            for pos in same_stock_positions:
                if pos.get('asset_class') == 'us_option' and 'PUT' in pos.get('symbol', ''):
                    # For puts: exposure = strike * 100 * abs(quantity)
                    # Parse strike from option symbol or use position data
                    if 'strike' in pos:
                        strike = float(pos['strike'])
                    else:
                        # Try to extract strike from symbol (format: TICKER+EXPIRY+P+STRIKE)
                        # This is a fallback - ideally position should have strike data
                        continue  # Skip if we can't determine strike
                    
                    contracts = abs(float(pos.get('qty', 0)))
                    current_exposure += strike * 100 * contracts
                
                elif pos.get('asset_class') == 'us_equity':
                    # For stock positions: exposure = current market value
                    current_exposure += abs(float(pos.get('market_value', 0)))
            
            # Calculate new position exposure
            if opportunity['strategy'] == 'sell_put':
                strike = float(opportunity.get('strike', opportunity.get('strike_price', 0)))
                contracts = int(opportunity.get('contracts', 1))  # Default to 1 contract
                new_exposure = strike * 100 * contracts
                
                total_exposure = current_exposure + new_exposure
                
                if total_exposure > self.config.max_exposure_per_ticker:
                    return False, f"Total exposure ${total_exposure:,.0f} would exceed limit ${self.config.max_exposure_per_ticker:,.0f} for {underlying_symbol}"
            
            # 4. Cash reserve check
            cash = float(account_info['cash'])
            min_cash_required = portfolio_value * self.config.min_cash_reserve
            
            if opportunity['strategy'] == 'sell_put':
                available_cash_after = cash - capital_required
                if available_cash_after < min_cash_required:
                    return False, f"Insufficient cash reserve after position"
            
            # 5. Options-specific risk checks
            validation_result = self._validate_option_specific_risks(opportunity)
            if not validation_result[0]:
                return validation_result
            
            logger.info("Position risk validation passed", 
                       symbol=opportunity['symbol'],
                       strategy=opportunity['strategy'])
            
            return True, "Position approved"
            
        except Exception as e:
            logger.error("Risk validation failed", error=str(e))
            return False, f"Risk validation error: {str(e)}"
    
    def _validate_option_specific_risks(self, opportunity: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate option-specific risk parameters.
        
        Args:
            opportunity: Position opportunity
            
        Returns:
            Tuple of (is_valid, reason)
        """
        try:
            # 1. Delta range validation
            delta = abs(opportunity.get('delta', 0))
            strategy = opportunity['strategy']
            
            if strategy == 'sell_put':
                delta_range = self.config.put_delta_range
            else:
                delta_range = self.config.call_delta_range
            
            if not (delta_range[0] <= delta <= delta_range[1]):
                return False, f"Delta {delta:.3f} outside range {delta_range}"
            
            # 2. Premium threshold validation
            premium = opportunity['premium']
            
            if strategy == 'sell_put':
                min_premium = self.config.min_put_premium
            else:
                min_premium = self.config.min_call_premium
            
            if premium < min_premium:
                return False, f"Premium {premium} below minimum {min_premium}"
            
            # 3. Days to expiration validation - must be less than or equal to target
            dte = opportunity['dte']
            
            if strategy == 'sell_put':
                max_dte = self.config.put_target_dte
            else:
                max_dte = self.config.call_target_dte
            
            if dte > max_dte:
                return False, f"DTE {dte} exceeds maximum {max_dte} days"
            
            # 4. Strike price reasonableness (not too far OTM or ITM)
            if 'current_stock_price' in opportunity:
                current_price = opportunity['current_stock_price']
                strike_price = opportunity['strike_price']
                
                if strategy == 'sell_put':
                    # Put strike should be below current price (OTM)
                    if strike_price >= current_price:
                        return False, "Put strike at or above current stock price"
                    
                    # Not more than 20% below current price
                    if strike_price < current_price * 0.8:
                        return False, "Put strike too far out of the money"
                        
                else:  # sell_call
                    # Call strike should be above current price (OTM)
                    if strike_price <= current_price:
                        return False, "Call strike at or below current stock price"
                    
                    # Not more than 20% above current price
                    if strike_price > current_price * 1.2:
                        return False, "Call strike too far out of the money"
            
            return True, "Option parameters validated"
            
        except Exception as e:
            logger.error("Option validation failed", error=str(e))
            return False, f"Option validation error: {str(e)}"
    
    def calculate_portfolio_risk_metrics(self, account_info: Dict[str, Any], 
                                       positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate comprehensive portfolio risk metrics.
        
        Args:
            account_info: Account information
            positions: Current positions
            
        Returns:
            Risk metrics dictionary
        """
        try:
            portfolio_value = float(account_info['portfolio_value'])
            cash = float(account_info['cash'])
            
            # Separate positions by type
            stock_positions = [p for p in positions if p['asset_class'] == 'us_equity']
            option_positions = [p for p in positions if p['asset_class'] == 'us_option']
            
            # Calculate allocations
            total_stock_value = sum(float(p['market_value']) for p in stock_positions)
            total_option_value = sum(abs(float(p['market_value'])) for p in option_positions)
            
            stock_allocation = total_stock_value / portfolio_value if portfolio_value > 0 else 0
            cash_allocation = cash / portfolio_value if portfolio_value > 0 else 0
            
            # Count positions by underlying
            underlying_exposure = {}
            for pos in positions:
                symbol = pos['symbol']
                if pos['asset_class'] == 'us_option':
                    # Extract underlying from option symbol (simplified)
                    underlying = symbol.split()[0] if ' ' in symbol else symbol
                else:
                    underlying = symbol
                
                if underlying not in underlying_exposure:
                    underlying_exposure[underlying] = 0
                underlying_exposure[underlying] += abs(float(pos['market_value']))
            
            # Find largest exposure
            max_exposure = 0
            max_exposure_symbol = ""
            if underlying_exposure:
                max_exposure_symbol = max(underlying_exposure, key=underlying_exposure.get)
                max_exposure = underlying_exposure[max_exposure_symbol] / portfolio_value if portfolio_value > 0 else 0
            
            # Calculate P&L metrics
            total_unrealized_pl = sum(float(p['unrealized_pl']) for p in positions)
            unrealized_pl_percent = total_unrealized_pl / portfolio_value if portfolio_value > 0 else 0
            
            # Risk warnings
            warnings = []
            
            if cash_allocation < self.config.min_cash_reserve:
                warnings.append(f"Cash reserve {cash_allocation:.1%} below minimum {self.config.min_cash_reserve:.1%}")
            
            if max_exposure > self.config.max_position_size * 2:  # 2x position limit for concentration
                warnings.append(f"High concentration in {max_exposure_symbol}: {max_exposure:.1%}")
            
            if len(option_positions) >= self.config.max_total_positions * 0.9:  # 90% of limit
                warnings.append(f"Approaching position limit: {len(option_positions)}/{self.config.max_total_positions}")
            
            return {
                'portfolio_value': portfolio_value,
                'cash_allocation': cash_allocation,
                'stock_allocation': stock_allocation,
                'total_positions': len(positions),
                'option_positions': len(option_positions),
                'stock_positions': len(stock_positions),
                'max_exposure_symbol': max_exposure_symbol,
                'max_exposure_percent': max_exposure,
                'unrealized_pl': total_unrealized_pl,
                'unrealized_pl_percent': unrealized_pl_percent,
                'underlying_exposures': underlying_exposure,
                'risk_warnings': warnings,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error("Failed to calculate risk metrics", error=str(e))
            return {'error': str(e)}
    
    def should_reduce_positions(self, risk_metrics: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Determine if positions should be reduced due to risk.
        
        Args:
            risk_metrics: Portfolio risk metrics
            
        Returns:
            Tuple of (should_reduce, reasons)
        """
        reasons = []
        
        # Check cash allocation
        if risk_metrics['cash_allocation'] < self.config.min_cash_reserve:
            reasons.append("Low cash reserves")
        
        # Check concentration
        if risk_metrics['max_exposure_percent'] > self.config.max_position_size * 2:
            reasons.append(f"High concentration in {risk_metrics['max_exposure_symbol']}")
        
        # Check overall P&L
        if risk_metrics['unrealized_pl_percent'] < -0.1:  # 10% portfolio loss
            reasons.append("Significant unrealized losses")
        
        # Check position count
        if risk_metrics['option_positions'] >= self.config.max_total_positions:
            reasons.append("Maximum positions reached")
        
        should_reduce = len(reasons) > 0
        
        if should_reduce:
            logger.warning("Risk reduction recommended", reasons=reasons)
        
        return should_reduce, reasons
    
    def get_emergency_stop_conditions(self) -> Dict[str, Any]:
        """Get conditions that would trigger an emergency stop.
        
        Returns:
            Emergency stop conditions
        """
        return {
            'max_daily_loss_percent': 0.05,  # 5% daily loss
            'max_portfolio_loss_percent': 0.15,  # 15% portfolio loss
            'min_buying_power_threshold': 1000,  # Minimum buying power
            'max_margin_usage_percent': 0.8,  # 80% margin usage
        }
    
    def check_emergency_conditions(self, account_info: Dict[str, Any], 
                                 risk_metrics: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Check if emergency stop conditions are met.
        
        Args:
            account_info: Account information
            risk_metrics: Risk metrics
            
        Returns:
            Tuple of (emergency_stop, reasons)
        """
        emergency_conditions = self.get_emergency_stop_conditions()
        reasons = []
        
        # Check portfolio loss
        if risk_metrics['unrealized_pl_percent'] < -emergency_conditions['max_portfolio_loss_percent']:
            reasons.append(f"Portfolio loss exceeds {emergency_conditions['max_portfolio_loss_percent']:.1%}")
        
        # Check buying power
        buying_power = float(account_info['buying_power'])
        if buying_power < emergency_conditions['min_buying_power_threshold']:
            reasons.append(f"Buying power below ${emergency_conditions['min_buying_power_threshold']}")
        
        emergency_stop = len(reasons) > 0
        
        if emergency_stop:
            logger.critical("Emergency stop conditions met", reasons=reasons)
        
        return emergency_stop, reasons