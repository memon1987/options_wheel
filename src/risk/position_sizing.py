"""Position sizing utilities for options wheel strategy."""

from typing import Dict, Any, Optional, Tuple
import structlog
import math

from ..utils.config import Config

logger = structlog.get_logger(__name__)


class PositionSizer:
    """Calculate appropriate position sizes for wheel strategy."""
    
    def __init__(self, config: Config):
        """Initialize position sizer.
        
        Args:
            config: Configuration instance
        """
        self.config = config
        
    def calculate_put_position_size(self, 
                                  put_option: Dict[str, Any], 
                                  account_info: Dict[str, Any],
                                  stock_volatility: Optional[float] = None) -> Dict[str, Any]:
        """Calculate position size for put selling.
        
        Args:
            put_option: Put option details
            account_info: Account information
            stock_volatility: Annual volatility of underlying stock
            
        Returns:
            Position sizing details
        """
        try:
            portfolio_value = float(account_info['portfolio_value'])
            buying_power = float(account_info['buying_power'])
            cash = float(account_info['cash'])
            
            strike_price = put_option['strike_price']
            premium = put_option['mid_price']
            
            # Base position size from configuration
            base_position_size = self.config.max_position_size
            
            # Adjust for volatility if provided
            if stock_volatility is not None:
                volatility_adjustment = self._get_volatility_adjustment(stock_volatility)
                adjusted_position_size = base_position_size * volatility_adjustment
            else:
                adjusted_position_size = base_position_size
            
            # Calculate maximum position value
            max_position_value = portfolio_value * adjusted_position_size
            
            # Calculate capital required per contract
            capital_per_contract = strike_price * 100
            
            # Calculate constraints
            max_contracts_by_portfolio = int(max_position_value // capital_per_contract)
            max_contracts_by_buying_power = int(buying_power // capital_per_contract)
            max_contracts_by_cash = int(cash // capital_per_contract)
            
            # Take the most conservative limit
            theoretical_max_contracts = min(
                max_contracts_by_portfolio,
                max_contracts_by_buying_power,
                max_contracts_by_cash,
                10  # Absolute maximum
            )
            
            # Apply Kelly Criterion if we have enough data
            if premium > 0 and strike_price > 0:
                kelly_contracts = self._calculate_kelly_sizing(put_option, portfolio_value)
                recommended_contracts = min(theoretical_max_contracts, kelly_contracts)
            else:
                recommended_contracts = theoretical_max_contracts
            
            # Conservative minimum
            recommended_contracts = max(1, recommended_contracts) if theoretical_max_contracts > 0 else 0
            
            # Calculate final metrics
            if recommended_contracts > 0:
                total_capital_required = recommended_contracts * capital_per_contract
                total_premium_income = recommended_contracts * premium * 100
                portfolio_allocation = total_capital_required / portfolio_value
                max_loss = total_capital_required - total_premium_income  # If stock goes to 0
                max_return_percent = (total_premium_income / total_capital_required) * 100
                
                # Calculate annual return estimate
                dte = put_option.get('dte', 30)
                if dte > 0:
                    annualized_return = (total_premium_income / total_capital_required) * (365 / dte) * 100
                else:
                    annualized_return = 0
            else:
                total_capital_required = 0
                total_premium_income = 0
                portfolio_allocation = 0
                max_loss = 0
                max_return_percent = 0
                annualized_return = 0
            
            return {
                'recommended_contracts': recommended_contracts,
                'capital_required': total_capital_required,
                'premium_income': total_premium_income,
                'portfolio_allocation': portfolio_allocation,
                'max_loss': max_loss,
                'max_return_percent': max_return_percent,
                'annualized_return_estimate': annualized_return,
                'position_sizing_factors': {
                    'base_allocation': base_position_size,
                    'volatility_adjustment': volatility_adjustment if stock_volatility else 1.0,
                    'final_allocation': adjusted_position_size,
                    'constraints': {
                        'by_portfolio': max_contracts_by_portfolio,
                        'by_buying_power': max_contracts_by_buying_power,
                        'by_cash': max_contracts_by_cash
                    }
                }
            }
            
        except Exception as e:
            logger.error("Failed to calculate put position size", error=str(e))
            return {'recommended_contracts': 0, 'error': str(e)}
    
    def calculate_call_position_size(self, 
                                   call_option: Dict[str, Any], 
                                   shares_owned: int,
                                   stock_position: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate position size for covered call selling.
        
        Args:
            call_option: Call option details
            shares_owned: Number of shares owned
            stock_position: Stock position details
            
        Returns:
            Position sizing details
        """
        try:
            # For covered calls, position size is limited by shares owned
            max_contracts = shares_owned // 100
            
            if max_contracts <= 0:
                return {
                    'recommended_contracts': 0,
                    'reason': 'insufficient_shares',
                    'shares_needed': 100 - (shares_owned % 100)
                }
            
            # Conservative approach - sell calls on all round lots initially
            # Can be adjusted based on market conditions
            recommended_contracts = max_contracts
            
            strike_price = call_option['strike_price']
            premium = call_option['mid_price']
            
            # Calculate metrics
            premium_income = recommended_contracts * premium * 100
            shares_covered = recommended_contracts * 100
            
            # Calculate potential outcomes
            stock_cost_basis_per_share = float(stock_position['cost_basis']) / shares_owned
            
            if strike_price > stock_cost_basis_per_share:
                # If called away above cost basis - capital gain
                capital_gain_per_share = strike_price - stock_cost_basis_per_share
                total_capital_gain = capital_gain_per_share * shares_covered
                total_return_if_called = premium_income + total_capital_gain
            else:
                # If called away below cost basis - capital loss
                capital_loss_per_share = stock_cost_basis_per_share - strike_price
                total_capital_loss = capital_loss_per_share * shares_covered
                total_return_if_called = premium_income - total_capital_loss
            
            # Calculate return percentages
            total_stock_investment = stock_cost_basis_per_share * shares_covered
            if total_stock_investment > 0:
                return_percent_if_called = (total_return_if_called / total_stock_investment) * 100
                premium_return_percent = (premium_income / total_stock_investment) * 100
            else:
                return_percent_if_called = 0
                premium_return_percent = 0
            
            # Annual return estimate
            dte = call_option.get('dte', 30)
            if dte > 0:
                annualized_premium_return = premium_return_percent * (365 / dte)
            else:
                annualized_premium_return = 0
            
            return {
                'recommended_contracts': recommended_contracts,
                'shares_covered': shares_covered,
                'premium_income': premium_income,
                'total_return_if_called': total_return_if_called,
                'return_percent_if_called': return_percent_if_called,
                'premium_return_percent': premium_return_percent,
                'annualized_premium_return': annualized_premium_return,
                'assignment_outcomes': {
                    'strike_price': strike_price,
                    'cost_basis_per_share': stock_cost_basis_per_share,
                    'profit_loss_if_called': total_return_if_called - premium_income  # Capital gain/loss component
                }
            }
            
        except Exception as e:
            logger.error("Failed to calculate call position size", error=str(e))
            return {'recommended_contracts': 0, 'error': str(e)}
    
    def _get_volatility_adjustment(self, volatility: float) -> float:
        """Calculate position size adjustment based on volatility.
        
        Args:
            volatility: Annual volatility (e.g., 0.3 for 30%)
            
        Returns:
            Adjustment factor (0.5 to 1.5)
        """
        # Base volatility assumption (25%)
        base_volatility = 0.25
        
        # Scale position size inversely with volatility
        if volatility <= 0:
            return 1.0
        
        # Higher volatility = smaller position size
        adjustment = base_volatility / volatility
        
        # Cap the adjustment between 0.5 and 1.5
        adjustment = max(0.5, min(1.5, adjustment))
        
        return adjustment
    
    def _calculate_kelly_sizing(self, option: Dict[str, Any], portfolio_value: float) -> int:
        """Calculate Kelly optimal position size.
        
        Args:
            option: Option details
            portfolio_value: Total portfolio value
            
        Returns:
            Optimal number of contracts
        """
        try:
            # Simplified Kelly criterion for options
            # This assumes some probability estimates - in practice, these would be
            # derived from historical data or more sophisticated models
            
            premium = option['mid_price']
            strike = option['strike_price']
            
            # Rough probability estimates (these should be calibrated with real data)
            # Assume 70% probability of profit for 0.20 delta options
            prob_profit = 0.70
            prob_loss = 1 - prob_profit
            
            # Win/loss amounts per contract
            max_win = premium * 100  # Premium collected
            max_loss = (strike * 100) - (premium * 100)  # Strike minus premium
            
            if max_loss <= 0:
                return 1  # Conservative fallback
            
            # Kelly formula: f = (bp - q) / b
            # where b = odds received, p = probability of win, q = probability of loss
            b = max_win / max_loss  # Reward to risk ratio
            
            if b <= 0:
                return 1
            
            kelly_fraction = (b * prob_profit - prob_loss) / b
            
            # Be very conservative with Kelly - use 25% of Kelly recommendation
            conservative_kelly_fraction = max(0, kelly_fraction * 0.25)
            
            # Convert to number of contracts
            capital_per_contract = strike * 100
            kelly_capital = portfolio_value * conservative_kelly_fraction
            kelly_contracts = int(kelly_capital // capital_per_contract)
            
            return max(1, kelly_contracts)
            
        except Exception as e:
            logger.error("Kelly sizing calculation failed", error=str(e))
            return 1  # Conservative fallback
    
    def validate_position_size(self, 
                             position_size_info: Dict[str, Any], 
                             account_info: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate calculated position size against account constraints.
        
        Args:
            position_size_info: Position sizing information
            account_info: Account information
            
        Returns:
            Tuple of (is_valid, reason)
        """
        try:
            if position_size_info['recommended_contracts'] <= 0:
                return False, "No contracts recommended"
            
            # Check portfolio allocation
            allocation = position_size_info.get('portfolio_allocation', 0)
            if allocation > self.config.max_position_size:
                return False, f"Allocation {allocation:.1%} exceeds limit {self.config.max_position_size:.1%}"
            
            # Check buying power
            capital_required = position_size_info.get('capital_required', 0)
            buying_power = float(account_info['buying_power'])
            
            if capital_required > buying_power:
                return False, f"Capital required ${capital_required:,.2f} exceeds buying power ${buying_power:,.2f}"
            
            # Check cash reserves
            portfolio_value = float(account_info['portfolio_value'])
            cash = float(account_info['cash'])
            min_cash_required = portfolio_value * self.config.min_cash_reserve
            
            cash_after_position = cash - capital_required
            if cash_after_position < min_cash_required:
                return False, f"Insufficient cash reserves after position"
            
            return True, "Position size validated"
            
        except Exception as e:
            logger.error("Position size validation failed", error=str(e))
            return False, f"Validation error: {str(e)}"