"""Analysis and visualization tools for backtest results."""

from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
import structlog

from .backtest_engine import BacktestResult

logger = structlog.get_logger(__name__)


class BacktestAnalyzer:
    """Analyzer for backtest results with visualization capabilities."""
    
    def __init__(self, result: BacktestResult):
        """Initialize analyzer with backtest result.
        
        Args:
            result: BacktestResult to analyze
        """
        self.result = result
        
        # Set up plotting style (with fallback for older seaborn versions)
        try:
            plt.style.use('seaborn-v0_8')
        except OSError:
            try:
                plt.style.use('seaborn')
            except OSError:
                # Fallback to default style
                plt.style.use('default')
        sns.set_palette("husl")
    
    def plot_portfolio_performance(self, figsize: Tuple[int, int] = (15, 10)) -> plt.Figure:
        """Plot portfolio performance over time.
        
        Args:
            figsize: Figure size
            
        Returns:
            Matplotlib figure
        """
        fig, axes = plt.subplots(2, 2, figsize=figsize)
        fig.suptitle('Portfolio Performance Analysis', fontsize=16)
        
        portfolio_df = self.result.portfolio_history
        
        # 1. Portfolio Value Over Time
        axes[0, 0].plot(portfolio_df.index, portfolio_df['total_value'], 
                       linewidth=2, label='Total Value')
        axes[0, 0].axhline(y=self.result.initial_capital, color='gray', 
                          linestyle='--', alpha=0.7, label='Initial Capital')
        axes[0, 0].set_title('Portfolio Value Over Time')
        axes[0, 0].set_ylabel('Portfolio Value ($)')
        axes[0, 0].legend()
        axes[0, 0].grid(True, alpha=0.3)
        
        # 2. Drawdown
        axes[0, 1].fill_between(portfolio_df.index, portfolio_df['drawdown'], 0, 
                               alpha=0.7, color='red', label='Drawdown')
        axes[0, 1].axhline(y=self.result.max_drawdown, color='darkred', 
                          linestyle='--', label=f'Max DD: {self.result.max_drawdown:.1%}')
        axes[0, 1].set_title('Portfolio Drawdown')
        axes[0, 1].set_ylabel('Drawdown (%)')
        axes[0, 1].legend()
        axes[0, 1].grid(True, alpha=0.3)
        
        # 3. Portfolio Composition
        axes[1, 0].stackplot(portfolio_df.index, 
                            portfolio_df['cash'],
                            portfolio_df['stock_value'],
                            portfolio_df['option_value'],
                            labels=['Cash', 'Stocks', 'Options'],
                            alpha=0.7)
        axes[1, 0].set_title('Portfolio Composition')
        axes[1, 0].set_ylabel('Value ($)')
        axes[1, 0].legend()
        axes[1, 0].grid(True, alpha=0.3)
        
        # 4. Rolling Returns
        portfolio_df['rolling_30d_return'] = portfolio_df['daily_return'].rolling(30).mean() * 30
        axes[1, 1].plot(portfolio_df.index, portfolio_df['rolling_30d_return'], 
                       linewidth=2, label='30-Day Rolling Return')
        axes[1, 1].axhline(y=0, color='gray', linestyle='-', alpha=0.5)
        axes[1, 1].set_title('30-Day Rolling Returns')
        axes[1, 1].set_ylabel('Return (%)')
        axes[1, 1].legend()
        axes[1, 1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        return fig
    
    def plot_trade_analysis(self, figsize: Tuple[int, int] = (15, 8)) -> plt.Figure:
        """Plot trade analysis.
        
        Args:
            figsize: Figure size
            
        Returns:
            Matplotlib figure
        """
        fig, axes = plt.subplots(2, 3, figsize=figsize)
        fig.suptitle('Trade Analysis', fontsize=16)
        
        trade_df = self.result.trade_history
        
        if trade_df.empty:
            fig.text(0.5, 0.5, 'No trades to analyze', ha='center', va='center', fontsize=20)
            return fig
        
        # 1. Trade Distribution by Type
        trade_counts = trade_df['type'].value_counts()
        axes[0, 0].pie(trade_counts.values, labels=trade_counts.index, autopct='%1.1f%%')
        axes[0, 0].set_title('Trade Distribution')
        
        # 2. P&L Distribution
        if 'realized_pnl' in trade_df.columns:
            pnl_trades = trade_df.dropna(subset=['realized_pnl'])
            if not pnl_trades.empty:
                axes[0, 1].hist(pnl_trades['realized_pnl'], bins=20, alpha=0.7, edgecolor='black')
                axes[0, 1].axvline(x=0, color='red', linestyle='--', alpha=0.7)
                axes[0, 1].set_title('P&L Distribution')
                axes[0, 1].set_xlabel('Realized P&L ($)')
                axes[0, 1].set_ylabel('Frequency')
        
        # 3. Monthly Trade Volume
        trade_df['month'] = pd.to_datetime(trade_df['date']).dt.to_period('M')
        monthly_trades = trade_df.groupby('month').size()
        axes[0, 2].bar(range(len(monthly_trades)), monthly_trades.values)
        axes[0, 2].set_title('Monthly Trade Volume')
        axes[0, 2].set_xlabel('Month')
        axes[0, 2].set_ylabel('Number of Trades')
        
        # 4. Cumulative Premium Collected
        opening_trades = trade_df[trade_df['action'] == 'open'].copy()
        if not opening_trades.empty:
            opening_trades = opening_trades.sort_values('date')
            opening_trades['cumulative_premium'] = opening_trades['amount'].cumsum()
            axes[1, 0].plot(opening_trades['date'], opening_trades['cumulative_premium'], 
                           linewidth=2, marker='o', markersize=4)
            axes[1, 0].set_title('Cumulative Premium Collected')
            axes[1, 0].set_ylabel('Premium ($)')
        
        # 5. Win/Loss Analysis
        if 'realized_pnl' in trade_df.columns:
            pnl_trades = trade_df.dropna(subset=['realized_pnl'])
            if not pnl_trades.empty:
                wins = pnl_trades[pnl_trades['realized_pnl'] > 0]
                losses = pnl_trades[pnl_trades['realized_pnl'] <= 0]
                
                categories = ['Wins', 'Losses']
                values = [len(wins), len(losses)]
                colors = ['green', 'red']
                
                axes[1, 1].bar(categories, values, color=colors, alpha=0.7)
                axes[1, 1].set_title(f'Win/Loss Ratio\nWin Rate: {self.result.win_rate:.1%}')
                axes[1, 1].set_ylabel('Number of Trades')
        
        # 6. Trade Size Distribution
        axes[1, 2].hist(trade_df['quantity'], bins=10, alpha=0.7, edgecolor='black')
        axes[1, 2].set_title('Trade Size Distribution')
        axes[1, 2].set_xlabel('Contracts/Shares')
        axes[1, 2].set_ylabel('Frequency')
        
        plt.tight_layout()
        return fig
    
    def plot_wheel_metrics(self, figsize: Tuple[int, int] = (12, 8)) -> plt.Figure:
        """Plot wheel strategy specific metrics.
        
        Args:
            figsize: Figure size
            
        Returns:
            Matplotlib figure
        """
        fig, axes = plt.subplots(2, 2, figsize=figsize)
        fig.suptitle('Wheel Strategy Metrics', fontsize=16)
        
        trade_df = self.result.trade_history
        
        if trade_df.empty:
            fig.text(0.5, 0.5, 'No trades to analyze', ha='center', va='center', fontsize=20)
            return fig
        
        # 1. Assignment Analysis
        assignments = trade_df[trade_df['action'] == 'assignment']
        assignment_by_type = assignments['type'].value_counts()
        
        if not assignment_by_type.empty:
            axes[0, 0].pie(assignment_by_type.values, labels=assignment_by_type.index, 
                          autopct='%1.1f%%', startangle=90)
            axes[0, 0].set_title(f'Assignments by Type\n({len(assignments)} total)')
        else:
            axes[0, 0].text(0.5, 0.5, 'No Assignments', ha='center', va='center')
            axes[0, 0].set_title('Assignments by Type')
        
        # 2. Premium vs Time
        opening_trades = trade_df[trade_df['action'] == 'open']
        if not opening_trades.empty:
            axes[0, 1].scatter(opening_trades['date'], opening_trades['amount'], 
                              c=opening_trades['type'].map({'PUT': 'blue', 'CALL': 'orange'}),
                              alpha=0.7, s=50)
            axes[0, 1].set_title('Premium Collection Over Time')
            axes[0, 1].set_ylabel('Premium Collected ($)')
        
        # 3. Days to Expiration Analysis
        if 'dte' in opening_trades.columns:
            put_trades = opening_trades[opening_trades['type'] == 'PUT']
            call_trades = opening_trades[opening_trades['type'] == 'CALL']
            
            if not put_trades.empty:
                axes[1, 0].hist([put_trades.get('dte', []), call_trades.get('dte', [])], 
                               bins=15, label=['PUTs', 'CALLs'], alpha=0.7)
                axes[1, 0].set_title('Days to Expiration Distribution')
                axes[1, 0].set_xlabel('Days to Expiration')
                axes[1, 0].set_ylabel('Frequency')
                axes[1, 0].legend()
        
        # 4. Strategy Performance Comparison
        put_pnl = trade_df[trade_df['type'] == 'PUT']['realized_pnl'].sum() if 'realized_pnl' in trade_df.columns else 0
        call_pnl = trade_df[trade_df['type'] == 'CALL']['realized_pnl'].sum() if 'realized_pnl' in trade_df.columns else 0
        
        strategies = ['PUT Selling', 'CALL Selling']
        pnl_values = [put_pnl, call_pnl]
        colors = ['green' if pnl >= 0 else 'red' for pnl in pnl_values]
        
        bars = axes[1, 1].bar(strategies, pnl_values, color=colors, alpha=0.7)
        axes[1, 1].set_title('Strategy P&L Comparison')
        axes[1, 1].set_ylabel('Realized P&L ($)')
        axes[1, 1].axhline(y=0, color='black', linestyle='-', alpha=0.5)
        
        # Add value labels on bars
        for bar, value in zip(bars, pnl_values):
            height = bar.get_height()
            axes[1, 1].text(bar.get_x() + bar.get_width()/2., height,
                           f'${value:,.0f}', ha='center', 
                           va='bottom' if height >= 0 else 'top')
        
        plt.tight_layout()
        return fig
    
    def generate_performance_report(self) -> str:
        """Generate detailed performance report.
        
        Returns:
            Formatted performance report
        """
        report = self.result.summary()
        
        # Add additional analysis
        portfolio_df = self.result.portfolio_history
        trade_df = self.result.trade_history
        
        # Risk metrics
        if not portfolio_df.empty and 'daily_return' in portfolio_df.columns:
            daily_returns = portfolio_df['daily_return'].dropna()
            
            if len(daily_returns) > 0:
                volatility = daily_returns.std() * np.sqrt(252)
                downside_returns = daily_returns[daily_returns < 0]
                downside_volatility = downside_returns.std() * np.sqrt(252) if len(downside_returns) > 0 else 0
                
                # Calmar ratio
                calmar_ratio = abs(self.result.annualized_return / self.result.max_drawdown) if self.result.max_drawdown != 0 else 0
                
                # Sortino ratio
                sortino_ratio = self.result.annualized_return / downside_volatility if downside_volatility != 0 else 0
                
                report += f"""
RISK METRICS
============
Volatility: {volatility:.2%}
Downside Volatility: {downside_volatility:.2%}
Calmar Ratio: {calmar_ratio:.2f}
Sortino Ratio: {sortino_ratio:.2f}
"""
        
        # Trade analysis
        if not trade_df.empty:
            avg_trade = trade_df['amount'].mean() if 'amount' in trade_df else 0
            
            if 'realized_pnl' in trade_df.columns:
                pnl_trades = trade_df.dropna(subset=['realized_pnl'])
                if not pnl_trades.empty:
                    avg_win = pnl_trades[pnl_trades['realized_pnl'] > 0]['realized_pnl'].mean()
                    avg_loss = pnl_trades[pnl_trades['realized_pnl'] <= 0]['realized_pnl'].mean()
                    profit_factor = abs(avg_win / avg_loss) if avg_loss < 0 else 0
                    
                    report += f"""
TRADE ANALYSIS
==============
Average Trade Size: ${avg_trade:,.2f}
Average Win: ${avg_win:,.2f}
Average Loss: ${avg_loss:,.2f}
Profit Factor: {profit_factor:.2f}
"""
        
        # Monthly returns
        if not portfolio_df.empty:
            portfolio_df_copy = portfolio_df.copy()
            portfolio_df_copy['month'] = portfolio_df_copy.index.to_period('M')
            monthly_returns = portfolio_df_copy.groupby('month')['total_value'].last().pct_change().dropna()
            
            if len(monthly_returns) > 0:
                best_month = monthly_returns.max()
                worst_month = monthly_returns.min()
                avg_monthly = monthly_returns.mean()
                
                report += f"""
MONTHLY PERFORMANCE
===================
Best Month: {best_month:.2%}
Worst Month: {worst_month:.2%}
Average Monthly: {avg_monthly:.2%}
Positive Months: {len(monthly_returns[monthly_returns > 0])}/{len(monthly_returns)} ({len(monthly_returns[monthly_returns > 0])/len(monthly_returns):.1%})
"""
        
        return report
    
    def compare_to_benchmark(self, benchmark_symbol: str = 'SPY') -> Dict:
        """Compare performance to benchmark (if data available).
        
        Args:
            benchmark_symbol: Benchmark symbol to compare against
            
        Returns:
            Dict with comparison metrics
        """
        # This would require fetching benchmark data
        # For now, return placeholder
        return {
            'benchmark_symbol': benchmark_symbol,
            'strategy_return': self.result.total_return,
            'strategy_volatility': None,  # Would calculate from daily returns
            'benchmark_return': None,     # Would fetch benchmark data
            'benchmark_volatility': None,
            'excess_return': None,
            'information_ratio': None,
            'beta': None,
            'alpha': None
        }
    
    def export_results(self, filepath: str, format: str = 'csv'):
        """Export backtest results to file.
        
        Args:
            filepath: Output file path
            format: Export format ('csv', 'excel', 'json')
        """
        if format.lower() == 'csv':
            # Export portfolio history
            portfolio_path = filepath.replace('.csv', '_portfolio.csv')
            self.result.portfolio_history.to_csv(portfolio_path)
            
            # Export trade history
            trade_path = filepath.replace('.csv', '_trades.csv')
            self.result.trade_history.to_csv(trade_path, index=False)
            
            logger.info("Results exported to CSV", 
                       portfolio=portfolio_path,
                       trades=trade_path)
        
        elif format.lower() == 'excel':
            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                self.result.portfolio_history.to_excel(writer, sheet_name='Portfolio')
                self.result.trade_history.to_excel(writer, sheet_name='Trades', index=False)
                
                # Add summary sheet
                summary_data = {
                    'Metric': ['Initial Capital', 'Final Capital', 'Total Return', 
                              'Annualized Return', 'Max Drawdown', 'Sharpe Ratio',
                              'Total Trades', 'Win Rate', 'Premium Collected'],
                    'Value': [self.result.initial_capital, self.result.final_capital,
                             f"{self.result.total_return:.2%}", f"{self.result.annualized_return:.2%}",
                             f"{self.result.max_drawdown:.2%}", f"{self.result.sharpe_ratio:.2f}",
                             self.result.total_trades, f"{self.result.win_rate:.1%}",
                             f"${self.result.premium_collected:,.2f}"]
                }
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            logger.info("Results exported to Excel", filepath=filepath)
        
        elif format.lower() == 'json':
            import json
            
            # Convert DataFrames to dict for JSON serialization
            export_data = {
                'summary': {
                    'start_date': self.result.start_date.isoformat(),
                    'end_date': self.result.end_date.isoformat(),
                    'initial_capital': self.result.initial_capital,
                    'final_capital': self.result.final_capital,
                    'total_return': self.result.total_return,
                    'annualized_return': self.result.annualized_return,
                    'max_drawdown': self.result.max_drawdown,
                    'sharpe_ratio': self.result.sharpe_ratio,
                    'win_rate': self.result.win_rate,
                    'total_trades': self.result.total_trades,
                    'premium_collected': self.result.premium_collected
                },
                'portfolio_history': self.result.portfolio_history.to_dict('records'),
                'trade_history': self.result.trade_history.to_dict('records')
            }
            
            with open(filepath, 'w') as f:
                json.dump(export_data, f, indent=2, default=str)
            
            logger.info("Results exported to JSON", filepath=filepath)