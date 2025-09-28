"""Trade simulation with realistic costs and slippage."""

from typing import Dict, List, Optional
from datetime import datetime
import structlog

logger = structlog.get_logger(__name__)


class TradeSimulator:
    """Simulates trade execution with realistic costs."""
    
    def __init__(
        self, 
        commission_per_contract: float = 1.00,
        commission_per_share: float = 0.0,
        slippage_bps: int = 5
    ):
        """Initialize trade simulator.
        
        Args:
            commission_per_contract: Commission per options contract
            commission_per_share: Commission per stock share
            slippage_bps: Slippage in basis points
        """
        self.commission_per_contract = commission_per_contract
        self.commission_per_share = commission_per_share
        self.slippage_bps = slippage_bps
        
    def simulate_option_trade(
        self,
        action: str,  # 'buy' or 'sell'
        contracts: int,
        price: float,
        option_type: str = 'PUT'
    ) -> Dict:
        """Simulate option trade execution.
        
        Args:
            action: 'buy' or 'sell'
            contracts: Number of contracts
            price: Price per contract
            option_type: 'PUT' or 'CALL'
            
        Returns:
            Dict with execution results
        """
        # Calculate base value
        base_value = contracts * price * 100
        
        # Calculate commission
        commission = contracts * self.commission_per_contract
        
        # Calculate slippage
        slippage = base_value * (self.slippage_bps / 10000)
        
        # Apply costs based on action
        if action.lower() == 'sell':
            # When selling, we receive less due to slippage and pay commission
            net_proceeds = base_value - slippage - commission
            cost_impact = slippage + commission
        else:
            # When buying, we pay more due to slippage and pay commission
            total_cost = base_value + slippage + commission
            net_proceeds = -total_cost
            cost_impact = slippage + commission
        
        return {
            'action': action,
            'contracts': contracts,
            'price': price,
            'base_value': base_value,
            'commission': commission,
            'slippage': slippage,
            'cost_impact': cost_impact,
            'net_proceeds': net_proceeds,
            'effective_price': (base_value + cost_impact) / (contracts * 100) if action == 'buy' else (base_value - cost_impact) / (contracts * 100)
        }
    
    def simulate_stock_trade(
        self,
        action: str,  # 'buy' or 'sell'
        shares: int,
        price: float
    ) -> Dict:
        """Simulate stock trade execution.
        
        Args:
            action: 'buy' or 'sell'
            shares: Number of shares
            price: Price per share
            
        Returns:
            Dict with execution results
        """
        # Calculate base value
        base_value = shares * price
        
        # Calculate commission
        commission = shares * self.commission_per_share
        
        # Calculate slippage
        slippage = base_value * (self.slippage_bps / 10000)
        
        # Apply costs based on action
        if action.lower() == 'sell':
            # When selling, we receive less due to slippage and pay commission
            net_proceeds = base_value - slippage - commission
            cost_impact = slippage + commission
        else:
            # When buying, we pay more due to slippage and pay commission
            total_cost = base_value + slippage + commission
            net_proceeds = -total_cost
            cost_impact = slippage + commission
        
        return {
            'action': action,
            'shares': shares,
            'price': price,
            'base_value': base_value,
            'commission': commission,
            'slippage': slippage,
            'cost_impact': cost_impact,
            'net_proceeds': net_proceeds,
            'effective_price': (base_value + cost_impact) / shares if action == 'buy' else (base_value - cost_impact) / shares
        }
    
    def simulate_assignment(
        self,
        option_type: str,  # 'PUT' or 'CALL'
        contracts: int,
        strike: float
    ) -> Dict:
        """Simulate option assignment.
        
        Args:
            option_type: 'PUT' or 'CALL'
            contracts: Number of contracts assigned
            strike: Strike price
            
        Returns:
            Dict with assignment results
        """
        shares = contracts * 100
        
        if option_type.upper() == 'PUT':
            # Put assignment - we buy shares at strike
            action = 'buy'
            base_value = shares * strike
            commission = shares * self.commission_per_share
            # No slippage on assignment (executed at strike)
            total_cost = base_value + commission
            net_cash_flow = -total_cost
        else:
            # Call assignment - we sell shares at strike
            action = 'sell'
            base_value = shares * strike
            commission = shares * self.commission_per_share
            # No slippage on assignment (executed at strike)
            net_proceeds = base_value - commission
            net_cash_flow = net_proceeds
        
        return {
            'action': 'assignment',
            'option_type': option_type,
            'contracts': contracts,
            'shares': shares,
            'strike': strike,
            'base_value': base_value,
            'commission': commission,
            'slippage': 0,  # No slippage on assignment
            'net_cash_flow': net_cash_flow
        }
    
    def calculate_break_even(
        self,
        option_type: str,
        strike: float,
        premium_received: float,
        contracts: int = 1
    ) -> float:
        """Calculate break-even price for option position.
        
        Args:
            option_type: 'PUT' or 'CALL'
            strike: Strike price
            premium_received: Premium received per contract
            contracts: Number of contracts
            
        Returns:
            Break-even price
        """
        if option_type.upper() == 'PUT':
            # For short puts: break-even = strike - premium
            break_even = strike - premium_received
        else:
            # For short calls: break-even = strike + premium
            break_even = strike + premium_received
        
        return break_even
    
    def estimate_option_pnl(
        self,
        position: Dict,
        current_underlying_price: float,
        time_decay_factor: float = 0.8
    ) -> Dict:
        """Estimate current P&L for option position.
        
        Args:
            position: Option position dict
            current_underlying_price: Current stock price
            time_decay_factor: Factor for time decay (0-1)
            
        Returns:
            Dict with P&L estimates
        """
        entry_price = position['entry_price']
        strike = position['strike']
        option_type = position['type']
        quantity = position['quantity']  # Negative for short positions
        
        # Estimate current option value
        if option_type.upper() == 'PUT':
            intrinsic_value = max(0, strike - current_underlying_price)
        else:
            intrinsic_value = max(0, current_underlying_price - strike)
        
        # Estimate time value (simplified)
        time_value = entry_price * time_decay_factor
        estimated_current_price = intrinsic_value + time_value
        
        # Calculate P&L
        if quantity < 0:  # Short position
            # We sold at entry_price, current value is estimated_current_price
            pnl_per_contract = entry_price - estimated_current_price
            total_pnl = pnl_per_contract * abs(quantity) * 100
        else:  # Long position
            pnl_per_contract = estimated_current_price - entry_price
            total_pnl = pnl_per_contract * quantity * 100
        
        return {
            'entry_price': entry_price,
            'estimated_current_price': estimated_current_price,
            'intrinsic_value': intrinsic_value,
            'time_value': time_value,
            'pnl_per_contract': pnl_per_contract,
            'total_pnl': total_pnl,
            'pnl_percentage': pnl_per_contract / entry_price if entry_price > 0 else 0
        }
    
    def should_exercise_option(
        self,
        option_type: str,
        strike: float,
        current_price: float,
        time_to_expiry: float,
        early_exercise_threshold: float = 0.05
    ) -> bool:
        """Determine if option should be exercised early.
        
        Args:
            option_type: 'PUT' or 'CALL'
            strike: Strike price
            current_price: Current underlying price
            time_to_expiry: Time to expiry in years
            early_exercise_threshold: Threshold for early exercise
            
        Returns:
            True if should exercise early
        """
        if time_to_expiry <= 0:
            return True  # At expiration
        
        if option_type.upper() == 'PUT':
            intrinsic_value = max(0, strike - current_price)
            # Early exercise if deeply ITM and close to expiration
            if intrinsic_value > 0 and time_to_expiry < 0.1:  # Less than ~36 days
                if current_price < strike * (1 - early_exercise_threshold):
                    return True
        else:
            intrinsic_value = max(0, current_price - strike)
            # Early exercise if deeply ITM and close to expiration
            if intrinsic_value > 0 and time_to_expiry < 0.1:
                if current_price > strike * (1 + early_exercise_threshold):
                    return True
        
        return False