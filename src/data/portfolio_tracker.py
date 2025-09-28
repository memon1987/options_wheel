"""Portfolio tracking and performance analytics for options wheel strategy."""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import pandas as pd
import structlog
import json

from ..api.alpaca_client import AlpacaClient
from ..utils.config import Config

logger = structlog.get_logger(__name__)


class PortfolioTracker:
    """Track portfolio performance and wheel strategy metrics."""
    
    def __init__(self, alpaca_client: AlpacaClient, config: Config):
        """Initialize portfolio tracker.
        
        Args:
            alpaca_client: Alpaca API client
            config: Configuration instance
        """
        self.alpaca = alpaca_client
        self.config = config
        self._performance_history = []
        
    def get_current_portfolio_snapshot(self) -> Dict[str, Any]:
        """Get comprehensive current portfolio snapshot.
        
        Returns:
            Portfolio snapshot with all key metrics
        """
        try:
            # Get account and position data
            account_info = self.alpaca.get_account()
            positions = self.alpaca.get_positions()
            
            # Separate positions by type
            stock_positions = [p for p in positions if p['asset_class'] == 'us_equity']
            option_positions = [p for p in positions if p['asset_class'] == 'us_option']
            
            # Calculate position values
            total_stock_value = sum(float(p['market_value']) for p in stock_positions)
            total_option_value = sum(float(p['market_value']) for p in option_positions)
            total_position_value = total_stock_value + total_option_value
            
            # Calculate P&L
            total_unrealized_pl = sum(float(p['unrealized_pl']) for p in positions)
            
            # Group positions by underlying symbol
            underlying_positions = self._group_positions_by_underlying(positions)
            
            # Calculate wheel-specific metrics
            wheel_metrics = self._calculate_wheel_metrics(underlying_positions)
            
            snapshot = {
                'timestamp': datetime.now().isoformat(),
                'account': {
                    'portfolio_value': float(account_info['portfolio_value']),
                    'cash': float(account_info['cash']),
                    'buying_power': float(account_info['buying_power']),
                    'equity': float(account_info['equity'])
                },
                'positions': {
                    'total_count': len(positions),
                    'stock_positions': len(stock_positions),
                    'option_positions': len(option_positions),
                    'total_value': total_position_value,
                    'stock_value': total_stock_value,
                    'option_value': total_option_value
                },
                'performance': {
                    'total_unrealized_pl': total_unrealized_pl,
                    'unrealized_pl_percent': total_unrealized_pl / float(account_info['portfolio_value']) * 100 if float(account_info['portfolio_value']) > 0 else 0
                },
                'underlying_positions': underlying_positions,
                'wheel_metrics': wheel_metrics
            }
            
            # Store snapshot for historical tracking
            self._performance_history.append(snapshot)
            
            # Keep only last 100 snapshots in memory
            if len(self._performance_history) > 100:
                self._performance_history = self._performance_history[-100:]
            
            return snapshot
            
        except Exception as e:
            logger.error("Failed to get portfolio snapshot", error=str(e))
            return {'error': str(e)}
    
    def _group_positions_by_underlying(self, positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Group positions by underlying symbol.
        
        Args:
            positions: List of all positions
            
        Returns:
            Dictionary grouped by underlying symbol
        """
        underlying_positions = {}
        
        for position in positions:
            symbol = position['symbol']
            
            if position['asset_class'] == 'us_equity':
                underlying = symbol
            else:
                # Extract underlying from option symbol (simplified)
                # In practice, this would need proper option symbol parsing
                underlying = symbol.split()[0] if ' ' in symbol else symbol.split('_')[0]
            
            if underlying not in underlying_positions:
                underlying_positions[underlying] = {
                    'underlying_symbol': underlying,
                    'stock_position': None,
                    'option_positions': [],
                    'total_value': 0,
                    'total_pl': 0,
                    'wheel_stage': 'none'  # none, cash_secured_puts, assigned_stock, covered_calls
                }
            
            if position['asset_class'] == 'us_equity':
                underlying_positions[underlying]['stock_position'] = position
            else:
                underlying_positions[underlying]['option_positions'].append(position)
            
            underlying_positions[underlying]['total_value'] += float(position['market_value'])
            underlying_positions[underlying]['total_pl'] += float(position['unrealized_pl'])
        
        # Determine wheel stage for each underlying
        for underlying, data in underlying_positions.items():
            data['wheel_stage'] = self._determine_wheel_stage(data)
        
        return underlying_positions
    
    def _determine_wheel_stage(self, underlying_data: Dict[str, Any]) -> str:
        """Determine the current wheel strategy stage for an underlying.
        
        Args:
            underlying_data: Position data for one underlying
            
        Returns:
            Wheel stage identifier
        """
        has_stock = underlying_data['stock_position'] is not None
        has_options = len(underlying_data['option_positions']) > 0
        
        if not has_stock and not has_options:
            return 'none'
        
        if has_stock and not has_options:
            return 'assigned_stock'
        
        if not has_stock and has_options:
            # Check if we have short puts (cash secured puts)
            for option in underlying_data['option_positions']:
                qty = float(option['qty'])
                if qty < 0:  # Short position
                    # This would need proper option type detection
                    return 'cash_secured_puts'  # Assuming puts for now
            return 'other_options'
        
        if has_stock and has_options:
            return 'covered_calls'
        
        return 'complex'
    
    def _calculate_wheel_metrics(self, underlying_positions: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate wheel strategy specific metrics.
        
        Args:
            underlying_positions: Positions grouped by underlying
            
        Returns:
            Wheel strategy metrics
        """
        metrics = {
            'active_wheels': 0,
            'cash_secured_puts': 0,
            'assigned_stocks': 0,
            'covered_calls': 0,
            'total_premium_collected': 0,  # This would need historical data
            'average_annual_return': 0,    # This would need historical data
            'assignment_rate': 0,          # This would need historical data
            'win_rate': 0                  # This would need historical data
        }
        
        for underlying, data in underlying_positions.items():
            stage = data['wheel_stage']
            
            if stage in ['cash_secured_puts', 'assigned_stock', 'covered_calls']:
                metrics['active_wheels'] += 1
            
            if stage == 'cash_secured_puts':
                metrics['cash_secured_puts'] += 1
            elif stage == 'assigned_stock':
                metrics['assigned_stocks'] += 1
            elif stage == 'covered_calls':
                metrics['covered_calls'] += 1
        
        return metrics
    
    def calculate_performance_metrics(self, days_back: int = 30) -> Dict[str, Any]:
        """Calculate performance metrics over specified period.
        
        Args:
            days_back: Number of days to calculate metrics for
            
        Returns:
            Performance metrics
        """
        try:
            if len(self._performance_history) < 2:
                return {'error': 'Insufficient history for performance calculation'}
            
            # Get recent snapshots
            cutoff_date = datetime.now() - timedelta(days=days_back)
            recent_snapshots = [
                snapshot for snapshot in self._performance_history
                if datetime.fromisoformat(snapshot['timestamp']) >= cutoff_date
            ]
            
            if len(recent_snapshots) < 2:
                return {'error': f'Insufficient data for {days_back} day analysis'}
            
            # Calculate metrics
            first_snapshot = recent_snapshots[0]
            last_snapshot = recent_snapshots[-1]
            
            initial_value = first_snapshot['account']['portfolio_value']
            final_value = last_snapshot['account']['portfolio_value']
            
            total_return = final_value - initial_value
            total_return_percent = (total_return / initial_value * 100) if initial_value > 0 else 0
            
            # Annualized return
            actual_days = (datetime.fromisoformat(last_snapshot['timestamp']) - 
                          datetime.fromisoformat(first_snapshot['timestamp'])).days
            if actual_days > 0:
                annualized_return = (total_return_percent / actual_days) * 365
            else:
                annualized_return = 0
            
            # Calculate volatility (if we have enough data points)
            if len(recent_snapshots) >= 10:
                values = [s['account']['portfolio_value'] for s in recent_snapshots]
                returns = [((values[i] - values[i-1]) / values[i-1]) for i in range(1, len(values)) if values[i-1] > 0]
                
                if returns:
                    import numpy as np
                    volatility = np.std(returns) * np.sqrt(365) * 100  # Annualized volatility
                    sharpe_ratio = annualized_return / volatility if volatility > 0 else 0
                else:
                    volatility = 0
                    sharpe_ratio = 0
            else:
                volatility = 0
                sharpe_ratio = 0
            
            # Max drawdown calculation
            max_value = initial_value
            max_drawdown = 0
            for snapshot in recent_snapshots:
                current_value = snapshot['account']['portfolio_value']
                max_value = max(max_value, current_value)
                drawdown = (max_value - current_value) / max_value * 100 if max_value > 0 else 0
                max_drawdown = max(max_drawdown, drawdown)
            
            return {
                'period_days': actual_days,
                'initial_value': initial_value,
                'final_value': final_value,
                'total_return': total_return,
                'total_return_percent': total_return_percent,
                'annualized_return_percent': annualized_return,
                'volatility_percent': volatility,
                'sharpe_ratio': sharpe_ratio,
                'max_drawdown_percent': max_drawdown,
                'data_points': len(recent_snapshots)
            }
            
        except Exception as e:
            logger.error("Failed to calculate performance metrics", error=str(e))
            return {'error': str(e)}
    
    def generate_performance_report(self) -> Dict[str, Any]:
        """Generate comprehensive performance report.
        
        Returns:
            Detailed performance report
        """
        try:
            current_snapshot = self.get_current_portfolio_snapshot()
            performance_30d = self.calculate_performance_metrics(30)
            
            # Get recent orders for activity summary
            recent_orders = self.alpaca.get_orders('filled')[-10:]  # Last 10 filled orders
            
            report = {
                'report_date': datetime.now().isoformat(),
                'current_portfolio': current_snapshot,
                'performance_30d': performance_30d,
                'recent_activity': {
                    'recent_orders': recent_orders,
                    'total_trades': len(recent_orders)
                },
                'risk_summary': self._calculate_risk_summary(current_snapshot),
                'recommendations': self._generate_recommendations(current_snapshot, performance_30d)
            }
            
            return report
            
        except Exception as e:
            logger.error("Failed to generate performance report", error=str(e))
            return {'error': str(e)}
    
    def _calculate_risk_summary(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate risk summary metrics.
        
        Args:
            snapshot: Current portfolio snapshot
            
        Returns:
            Risk summary
        """
        try:
            portfolio_value = snapshot['account']['portfolio_value']
            cash_percent = (snapshot['account']['cash'] / portfolio_value * 100) if portfolio_value > 0 else 0
            
            # Concentration analysis
            underlying_positions = snapshot.get('underlying_positions', {})
            max_position_value = 0
            max_position_symbol = ""
            
            for symbol, data in underlying_positions.items():
                position_value = abs(data['total_value'])
                if position_value > max_position_value:
                    max_position_value = position_value
                    max_position_symbol = symbol
            
            max_concentration = (max_position_value / portfolio_value * 100) if portfolio_value > 0 else 0
            
            return {
                'cash_percentage': cash_percent,
                'max_concentration': max_concentration,
                'max_concentration_symbol': max_position_symbol,
                'total_positions': len(underlying_positions),
                'risk_level': 'Low' if max_concentration < 15 else 'Medium' if max_concentration < 25 else 'High'
            }
            
        except Exception as e:
            logger.error("Failed to calculate risk summary", error=str(e))
            return {'error': str(e)}
    
    def _generate_recommendations(self, snapshot: Dict[str, Any], performance: Dict[str, Any]) -> List[str]:
        """Generate trading recommendations based on current state.
        
        Args:
            snapshot: Current portfolio snapshot
            performance: Recent performance metrics
            
        Returns:
            List of recommendations
        """
        recommendations = []
        
        try:
            # Cash level recommendations
            cash_percent = (snapshot['account']['cash'] / snapshot['account']['portfolio_value'] * 100)
            if cash_percent < self.config.min_cash_reserve * 100:
                recommendations.append(f"Consider increasing cash reserves (currently {cash_percent:.1f}%)")
            elif cash_percent > 50:
                recommendations.append("High cash levels - consider deploying capital in wheel strategies")
            
            # Position count recommendations
            wheel_metrics = snapshot.get('wheel_metrics', {})
            active_wheels = wheel_metrics.get('active_wheels', 0)
            
            if active_wheels < 3:
                recommendations.append("Consider adding more wheel positions for diversification")
            elif active_wheels > self.config.max_total_positions * 0.8:
                recommendations.append("Approaching maximum position limit")
            
            # Performance-based recommendations
            if 'total_return_percent' in performance:
                if performance['total_return_percent'] < -5:
                    recommendations.append("Recent negative performance - consider reducing position sizes")
                elif performance['total_return_percent'] > 10:
                    recommendations.append("Strong recent performance - consider taking some profits")
            
            # Assignment recommendations
            assigned_stocks = wheel_metrics.get('assigned_stocks', 0)
            if assigned_stocks > 0:
                recommendations.append(f"Review {assigned_stocks} assigned stock position(s) for covered call opportunities")
            
        except Exception as e:
            logger.error("Failed to generate recommendations", error=str(e))
            recommendations.append("Unable to generate recommendations due to data error")
        
        return recommendations
    
    def export_performance_data(self, filename: Optional[str] = None) -> str:
        """Export performance history to JSON file.
        
        Args:
            filename: Optional filename, defaults to timestamp-based name
            
        Returns:
            Filename of exported data
        """
        try:
            if filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"wheel_performance_{timestamp}.json"
            
            export_data = {
                'export_timestamp': datetime.now().isoformat(),
                'performance_history': self._performance_history,
                'config_snapshot': {
                    'max_positions': self.config.max_total_positions,
                    'max_position_size': self.config.max_position_size,
                    'stock_symbols': self.config.stock_symbols
                }
            }
            
            with open(filename, 'w') as f:
                json.dump(export_data, f, indent=2, default=str)
            
            logger.info("Performance data exported", filename=filename)
            return filename
            
        except Exception as e:
            logger.error("Failed to export performance data", error=str(e))
            return ""