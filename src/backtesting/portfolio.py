"""Portfolio management for backtesting."""

from typing import Dict, List, Optional
from datetime import datetime
import structlog

logger = structlog.get_logger(__name__)


class BacktestPortfolio:
    """Portfolio manager for backtesting."""
    
    def __init__(self, initial_cash: float):
        """Initialize portfolio with starting cash.
        
        Args:
            initial_cash: Starting cash amount
        """
        self.initial_cash = initial_cash
        self.cash = initial_cash
        
        # Position tracking
        self.stock_positions: List[Dict] = []
        self.option_positions: List[Dict] = []
        
        # Performance tracking
        self.realized_pnl = 0.0
        self.total_premium_collected = 0.0
        self.total_commissions = 0.0
        
    @property
    def stock_value(self) -> float:
        """Calculate total value of stock positions."""
        return sum(pos['market_value'] for pos in self.stock_positions)
    
    @property
    def option_value(self) -> float:
        """Calculate total value of option positions."""
        return sum(pos['market_value'] for pos in self.option_positions)
    
    @property
    def total_value(self) -> float:
        """Calculate total portfolio value."""
        return self.cash + self.stock_value + self.option_value
    
    @property
    def buying_power(self) -> float:
        """Calculate available buying power."""
        # Simplified - in reality this would consider margin requirements
        return self.cash * 2  # Assume 2:1 buying power
    
    def get_position(self, symbol: str, position_type: str = 'stock') -> Optional[Dict]:
        """Get position by symbol and type.
        
        Args:
            symbol: Symbol to search for
            position_type: 'stock' or 'option'
            
        Returns:
            Position dict or None
        """
        if position_type == 'stock':
            for pos in self.stock_positions:
                if pos['symbol'] == symbol:
                    return pos
        else:
            for pos in self.option_positions:
                if pos['symbol'] == symbol:
                    return pos
        
        return None
    
    def get_positions_by_underlying(self, underlying: str) -> Dict[str, List[Dict]]:
        """Get all positions for an underlying symbol.
        
        Args:
            underlying: Underlying symbol
            
        Returns:
            Dict with 'stock' and 'options' lists
        """
        result = {'stock': [], 'options': []}
        
        # Find stock positions
        for pos in self.stock_positions:
            if pos['symbol'] == underlying:
                result['stock'].append(pos)
        
        # Find option positions
        for pos in self.option_positions:
            if pos.get('underlying') == underlying:
                result['options'].append(pos)
        
        return result
    
    def add_stock_position(self, position: Dict):
        """Add or update stock position.
        
        Args:
            position: Stock position dict
        """
        # Check if position already exists
        existing = self.get_position(position['symbol'], 'stock')
        
        if existing:
            # Update existing position (average cost)
            old_quantity = existing['quantity']
            old_cost = existing['cost_basis']
            new_quantity = position['quantity']
            new_cost = position['cost_basis']
            
            total_quantity = old_quantity + new_quantity
            total_cost = old_cost + new_cost
            
            existing['quantity'] = total_quantity
            existing['cost_basis'] = total_cost
            existing['entry_price'] = total_cost / total_quantity if total_quantity > 0 else 0
            existing['market_value'] = total_quantity * existing['current_price']
        else:
            self.stock_positions.append(position)
    
    def remove_stock_position(self, symbol: str, quantity: int) -> bool:
        """Remove shares from stock position.
        
        Args:
            symbol: Stock symbol
            quantity: Number of shares to remove
            
        Returns:
            True if successful
        """
        position = self.get_position(symbol, 'stock')
        if not position:
            return False
        
        if position['quantity'] <= quantity:
            # Remove entire position
            self.stock_positions.remove(position)
        else:
            # Reduce position
            position['quantity'] -= quantity
            position['cost_basis'] = position['entry_price'] * position['quantity']
            position['market_value'] = position['quantity'] * position['current_price']
        
        return True
    
    def add_option_position(self, position: Dict):
        """Add option position.
        
        Args:
            position: Option position dict
        """
        self.option_positions.append(position)
    
    def remove_option_position(self, symbol: str) -> bool:
        """Remove option position by symbol.
        
        Args:
            symbol: Option symbol
            
        Returns:
            True if successful
        """
        position = self.get_position(symbol, 'option')
        if position:
            self.option_positions.remove(position)
            return True
        return False
    
    def update_cash(self, amount: float, description: str = ""):
        """Update cash balance.
        
        Args:
            amount: Amount to add/subtract
            description: Description of transaction
        """
        self.cash += amount
        
        if amount > 0:
            self.total_premium_collected += amount
        
        logger.debug("Cash updated", 
                    amount=amount, 
                    new_balance=self.cash,
                    description=description)
    
    def get_portfolio_summary(self) -> Dict:
        """Get portfolio summary.
        
        Returns:
            Dict with portfolio metrics
        """
        return {
            'cash': self.cash,
            'stock_value': self.stock_value,
            'option_value': self.option_value,
            'total_value': self.total_value,
            'total_return': (self.total_value - self.initial_cash) / self.initial_cash,
            'stock_positions': len(self.stock_positions),
            'option_positions': len(self.option_positions),
            'realized_pnl': self.realized_pnl,
            'premium_collected': self.total_premium_collected,
            'commissions_paid': self.total_commissions
        }
    
    def get_risk_metrics(self) -> Dict:
        """Calculate risk metrics.
        
        Returns:
            Dict with risk metrics
        """
        total_value = self.total_value
        
        # Concentration risk
        if self.stock_positions:
            largest_position = max(pos['market_value'] for pos in self.stock_positions)
            concentration = largest_position / total_value if total_value > 0 else 0
        else:
            concentration = 0
        
        # Cash percentage
        cash_percentage = self.cash / total_value if total_value > 0 else 1
        
        # Option exposure
        total_option_value = abs(self.option_value)
        option_exposure = total_option_value / total_value if total_value > 0 else 0
        
        return {
            'concentration_risk': concentration,
            'cash_percentage': cash_percentage,
            'option_exposure': option_exposure,
            'leverage': self.buying_power / total_value if total_value > 0 else 0
        }
    
    def validate_position_limits(self, config) -> List[str]:
        """Validate portfolio against position limits.
        
        Args:
            config: Configuration object
            
        Returns:
            List of validation warnings
        """
        warnings = []
        total_value = self.total_value
        
        # Check cash reserve
        cash_percentage = self.cash / total_value if total_value > 0 else 1
        if cash_percentage < config.min_cash_reserve:
            warnings.append(f"Cash reserve below minimum: {cash_percentage:.1%} < {config.min_cash_reserve:.1%}")
        
        # Check position sizes
        for pos in self.stock_positions:
            position_size = pos['market_value'] / total_value if total_value > 0 else 0
            if position_size > config.max_position_size:
                warnings.append(f"Position {pos['symbol']} exceeds size limit: {position_size:.1%}")
        
        # Check total positions
        if len(self.option_positions) > config.max_total_positions:
            warnings.append(f"Total positions exceed limit: {len(self.option_positions)} > {config.max_total_positions}")
        
        return warnings