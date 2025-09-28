"""Core options wheel strategy engine."""

from typing import Dict, List, Any, Optional
from datetime import datetime
import structlog

from ..api.alpaca_client import AlpacaClient
from ..api.market_data import MarketDataManager
from ..risk.gap_detector import GapDetector
from ..utils.config import Config
from .put_seller import PutSeller
from .call_seller import CallSeller

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

        logger.info("Wheel engine initialized")
    
    def run_strategy_cycle(self) -> Dict[str, Any]:
        """Run one complete cycle of the wheel strategy.
        
        Returns:
            Summary of actions taken
        """
        logger.info("Starting strategy cycle")
        
        cycle_summary = {
            'timestamp': datetime.now().isoformat(),
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
            
            logger.info("Strategy cycle completed", 
                       actions_taken=len(cycle_summary['actions']),
                       new_positions=cycle_summary['new_positions'],
                       closed_positions=cycle_summary['closed_positions'])
            
        except Exception as e:
            error_msg = f"Strategy cycle failed: {str(e)}"
            logger.error(error_msg)
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
                action = self.call_seller.evaluate_covered_call_opportunity(stock_pos)
                if action:
                    actions.append(action)
        
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
        """Find new options trading opportunities.
        
        Returns:
            List of actions for new opportunities
        """
        actions = []
        
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

            logger.info("Evaluating new opportunities",
                       suitable_stocks=len(suitable_stocks),
                       gap_filtered_stocks=len(gap_filtered_stocks))

            # For each gap-filtered stock, look for put selling opportunities
            for stock in gap_filtered_stocks[:5]:  # Limit to top 5 stocks
                symbol = stock['symbol']

                # Check if we already have positions in this stock
                if self._has_existing_position(symbol):
                    continue

                # Check execution gap before proceeding
                execution_check = self.gap_detector.can_execute_trade(symbol, datetime.now())
                if not execution_check['can_execute']:
                    logger.info("Trade execution blocked by gap check",
                               symbol=symbol,
                               reason=execution_check['reason'],
                               gap_percent=execution_check.get('current_gap_percent', 0))
                    continue

                # Look for put selling opportunity
                put_opportunity = self.put_seller.find_put_opportunity(symbol)
                if put_opportunity:
                    # Add gap check result to the opportunity
                    put_opportunity['gap_check'] = execution_check
                    actions.append(put_opportunity)

                    # Only one new position per cycle to be conservative
                    break
            
        except Exception as e:
            logger.error("Failed to find new opportunities", error=str(e))
        
        return actions
    
    def _has_existing_position(self, underlying_symbol: str) -> bool:
        """Check if we already have positions in a given underlying stock.
        
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
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error("Failed to get strategy status", error=str(e))
            return {'error': str(e)}