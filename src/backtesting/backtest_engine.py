"""Main backtesting engine for options wheel strategies."""

from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta, date
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
import structlog
import time

from .historical_data import HistoricalDataManager
from .portfolio import BacktestPortfolio
from .trade_simulator import TradeSimulator
from ..strategy.put_seller import PutSeller
from ..strategy.call_seller import CallSeller
from ..strategy.wheel_state_manager import WheelStateManager, WheelPhase
from ..api.market_data import MarketDataManager
from ..risk.risk_manager import RiskManager
from ..risk.gap_detector import GapDetector
from ..utils.config import Config
from ..utils.logging_events import log_backtest_event, log_performance_metric

logger = structlog.get_logger(__name__)


@dataclass
class BacktestConfig:
    """Configuration for backtesting."""
    start_date: datetime
    end_date: datetime
    initial_capital: float = 100000.0
    symbols: List[str] = field(default_factory=lambda: ['AAPL', 'MSFT', 'GOOGL'])
    commission_per_contract: float = 1.00
    slippage_bps: int = 5  # Basis points of slippage
    
    # Strategy parameters (can override config.yaml)
    put_target_dte: Optional[int] = None
    call_target_dte: Optional[int] = None
    put_delta_range: Optional[List[float]] = None
    call_delta_range: Optional[List[float]] = None


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    
    # Wheel-specific metrics
    total_trades: int
    put_trades: int
    call_trades: int
    assignments: int
    assignment_rate: float
    premium_collected: float
    
    # Daily portfolio values
    portfolio_history: pd.DataFrame
    trade_history: pd.DataFrame
    
    # At-risk capital metrics
    max_at_risk_capital: float = 0.0
    avg_at_risk_capital: float = 0.0
    peak_at_risk_percentage: float = 0.0
    
    def summary(self) -> str:
        """Get formatted summary of results."""
        return f"""
BACKTEST RESULTS
================
Period: {self.start_date.date()} to {self.end_date.date()}
Initial Capital: ${self.initial_capital:,.2f}
Final Capital: ${self.final_capital:,.2f}
Total Return: {self.total_return:.2%}
Annualized Return: {self.annualized_return:.2%}
Max Drawdown: {self.max_drawdown:.2%}
Sharpe Ratio: {self.sharpe_ratio:.2f}

WHEEL STRATEGY METRICS
======================
Total Trades: {self.total_trades}
Put Trades: {self.put_trades}
Call Trades: {self.call_trades}
Assignments: {self.assignments}
Assignment Rate: {self.assignment_rate:.1%}
Total Premium Collected: ${self.premium_collected:,.2f}
Win Rate: {self.win_rate:.1%}
"""


class BacktestEngine:
    """Main backtesting engine for wheel strategies."""
    
    def __init__(self, config: Config, backtest_config: BacktestConfig):
        """Initialize backtesting engine.
        
        Args:
            config: Main configuration
            backtest_config: Backtesting-specific configuration
        """
        self.config = config
        self.backtest_config = backtest_config
        
        # Override strategy parameters if specified
        self._override_config()
        
        # Initialize components
        self.data_manager = HistoricalDataManager(config)
        self.portfolio = BacktestPortfolio(backtest_config.initial_capital)
        self.trade_simulator = TradeSimulator(
            commission_per_contract=backtest_config.commission_per_contract,
            slippage_bps=backtest_config.slippage_bps
        )
        
        # Strategy components
        self.risk_manager = RiskManager(config)

        # Create a temporary alpaca client for gap detection
        from ..api.alpaca_client import AlpacaClient
        temp_alpaca = AlpacaClient(config)
        self.gap_detector = GapDetector(config, temp_alpaca)

        # Initialize wheel state manager for proper strategy logic
        self.wheel_state = WheelStateManager()

        # We'll create mock market data manager and strategy classes
        self.put_seller = None
        self.call_seller = None

        # Results tracking
        self.daily_history = []
        self.trade_history = []
        
    def _override_config(self):
        """Override config parameters with backtest-specific values."""
        if self.backtest_config.put_target_dte is not None:
            self.config._config['strategy']['put_target_dte'] = self.backtest_config.put_target_dte
        if self.backtest_config.call_target_dte is not None:
            self.config._config['strategy']['call_target_dte'] = self.backtest_config.call_target_dte
        if self.backtest_config.put_delta_range is not None:
            self.config._config['strategy']['put_delta_range'] = self.backtest_config.put_delta_range
        if self.backtest_config.call_delta_range is not None:
            self.config._config['strategy']['call_delta_range'] = self.backtest_config.call_delta_range
    
    def run_backtest(self) -> BacktestResult:
        """Run the complete backtest.

        Returns:
            BacktestResult with all metrics and data
        """
        # Generate unique backtest ID
        backtest_id = f"bt_{int(time.time())}_{self.backtest_config.start_date.strftime('%Y%m%d')}"
        backtest_start_time = time.time()

        logger.info("Starting backtest",
                   start=self.backtest_config.start_date,
                   end=self.backtest_config.end_date,
                   symbols=self.backtest_config.symbols)

        # Enhanced logging for backtest start
        log_backtest_event(
            logger,
            event_type="backtest_started",
            backtest_id=backtest_id,
            start_date=self.backtest_config.start_date.isoformat(),
            end_date=self.backtest_config.end_date.isoformat(),
            initial_capital=self.backtest_config.initial_capital,
            symbols=",".join(self.backtest_config.symbols),
            symbol_count=len(self.backtest_config.symbols),
            put_target_dte=self.config.put_target_dte,
            call_target_dte=self.config.call_target_dte,
            gap_detection_enabled=self.config.enable_gap_detection
        )

        # Fetch all historical data first
        self._load_historical_data()
        
        # Run day-by-day simulation
        current_date = self.backtest_config.start_date
        trading_days = 0
        
        while current_date <= self.backtest_config.end_date:
            if self._is_trading_day(current_date):
                self._process_trading_day(current_date)
                trading_days += 1
                
                if trading_days % 50 == 0:
                    logger.info("Backtest progress", 
                               date=current_date.date(),
                               portfolio_value=self.portfolio.total_value)
            
            current_date += timedelta(days=1)
        
        # Calculate final results
        result = self._calculate_results()

        # Calculate backtest duration
        backtest_duration = time.time() - backtest_start_time

        logger.info("Backtest completed",
                   final_value=result.final_capital,
                   total_return=result.total_return,
                   trades=result.total_trades)

        # Enhanced logging for backtest completion
        log_backtest_event(
            logger,
            event_type="backtest_completed",
            backtest_id=backtest_id,
            start_date=self.backtest_config.start_date.isoformat(),
            end_date=self.backtest_config.end_date.isoformat(),
            duration_seconds=backtest_duration,

            # Capital metrics
            initial_capital=result.initial_capital,
            final_capital=result.final_capital,
            total_return=result.total_return,
            annualized_return=result.annualized_return,

            # Risk metrics
            max_drawdown=result.max_drawdown,
            sharpe_ratio=result.sharpe_ratio,
            max_at_risk_capital=result.max_at_risk_capital,
            avg_at_risk_capital=result.avg_at_risk_capital,
            peak_at_risk_percentage=result.peak_at_risk_percentage,

            # Trading metrics
            total_trades=result.total_trades,
            put_trades=result.put_trades,
            call_trades=result.call_trades,
            assignments=result.assignments,
            assignment_rate=result.assignment_rate,
            win_rate=result.win_rate,
            premium_collected=result.premium_collected,

            # Configuration
            symbols=",".join(self.backtest_config.symbols),
            symbol_count=len(self.backtest_config.symbols),
            trading_days=trading_days,

            # Success indicator
            success=True
        )

        # Log performance metric for backtest execution time
        log_performance_metric(
            logger,
            metric_name="backtest_execution_time",
            metric_value=backtest_duration,
            metric_unit="seconds",
            backtest_id=backtest_id,
            trading_days=trading_days,
            total_trades=result.total_trades,
            days_per_second=trading_days / backtest_duration if backtest_duration > 0 else 0
        )

        return result
    
    def _load_historical_data(self):
        """Pre-load historical stock data and initialize caches for all symbols."""
        logger.info("Loading historical data with caching")

        self.stock_data = {}
        # Initialize caches for option data
        self._option_chain_cache = {}
        self._option_price_cache = {}

        for symbol in self.backtest_config.symbols:
            df = self.data_manager.get_stock_data(
                symbol,
                self.backtest_config.start_date - timedelta(days=100),  # Extra buffer
                self.backtest_config.end_date
            )

            if not df.empty:
                self.stock_data[symbol] = df
                logger.info("Loaded stock data",
                           symbol=symbol,
                           rows=len(df))

                # Pre-load some option chain data for key dates to improve performance
                self._preload_option_chains(symbol)
            else:
                logger.warning("No data available", symbol=symbol)

    def _preload_option_chains(self, symbol: str):
        """Pre-load option chain data for key trading dates."""
        try:
            # Pre-load option chains for weekly intervals to speed up backtesting
            current_date = self.backtest_config.start_date
            preload_count = 0
            max_preload = 10  # Limit preloading to avoid excessive API calls

            while current_date <= self.backtest_config.end_date and preload_count < max_preload:
                if self._is_trading_day(current_date):
                    # This will cache the option chain
                    self._get_cached_option_chain(symbol, current_date)
                    preload_count += 1

                current_date += timedelta(days=7)  # Weekly intervals

            logger.info("Pre-loaded option chains", symbol=symbol, count=preload_count)

        except Exception as e:
            logger.warning("Failed to preload option chains", symbol=symbol, error=str(e))

    def _get_option_market_data(self, underlying: str, strike: float,
                               expiration: datetime, option_type: str,
                               date: datetime) -> Optional[Dict]:
        """Get current market data for a specific option."""
        try:
            # First try to get from cached option chain
            chain_data = self._get_cached_option_chain(underlying, date)
            if chain_data:
                option_list = chain_data['puts'] if option_type == 'PUT' else chain_data['calls']

                # Find exact match
                for option in option_list:
                    if (abs(option['strike_price'] - strike) < 0.01 and
                        option['expiration_date'].date() == expiration.date()):
                        return {
                            'bid': option['bid'],
                            'ask': option['ask'],
                            'mid_price': (option['bid'] + option['ask']) / 2,
                            'volume': option.get('volume', 0),
                            'last_price': option.get('last_price', option['bid'])
                        }

            # If not found, estimate based on current stock price and Greeks
            stock_price_row = self._get_stock_price_for_date(underlying, date)
            if stock_price_row is not None:
                current_price = stock_price_row['close']
                time_to_expiry = max(0, (expiration - date).days / 365.0)

                if time_to_expiry <= 0:
                    # At expiration - intrinsic value only
                    if option_type == 'PUT':
                        intrinsic = max(0, strike - current_price)
                    else:
                        intrinsic = max(0, current_price - strike)

                    return {
                        'bid': max(0.01, intrinsic - 0.05),
                        'ask': intrinsic + 0.05,
                        'mid_price': intrinsic,
                        'volume': 10,
                        'last_price': intrinsic
                    }

                # Use Black-Scholes for estimation
                volatility = stock_price_row.get('volatility', 0.25)
                if pd.isna(volatility) or volatility == 0:
                    volatility = 0.25

                greeks = self.data_manager.calculate_option_greeks(
                    current_price, strike, time_to_expiry, volatility, 0.05, option_type
                )

                # Estimate option price
                intrinsic = max(0, strike - current_price) if option_type == 'PUT' else max(0, current_price - strike)
                time_value = abs(greeks['delta']) * current_price * volatility * np.sqrt(time_to_expiry)
                estimated_price = intrinsic + time_value

                # Add realistic bid/ask spread
                spread = max(0.05, estimated_price * 0.08)  # 8% spread or $0.05 minimum

                return {
                    'bid': max(0.01, estimated_price - spread/2),
                    'ask': estimated_price + spread/2,
                    'mid_price': estimated_price,
                    'volume': 25,  # Estimated volume
                    'last_price': estimated_price
                }

            return None

        except Exception as e:
            logger.debug("Could not get option market data",
                        underlying=underlying, strike=strike, error=str(e))
            return None
    
    def _is_trading_day(self, date: datetime) -> bool:
        """Check if date is a trading day."""
        # Simple check - weekdays only (could be enhanced with market holidays)
        return date.weekday() < 5
    
    def _process_trading_day(self, date: datetime):
        """Process all activities for a single trading day.
        
        Args:
            date: The trading date to process
        """
        logger.debug("Processing trading day", date=date.date())
        
        # 1. Update portfolio with current market prices
        self._update_portfolio_values(date)

        # 2. Check for overnight gaps and handle gap-related closures
        self._check_gap_risk(date)

        # 3. Check for expirations and assignments
        self._process_expirations(date)

        # 4. Check for early closures (profit targets, stop losses)
        self._check_early_closures(date)

        # 5. Look for new opportunities (with gap filtering)
        self._find_new_opportunities(date)
        
        # 5. Record daily portfolio state
        self._record_daily_state(date)
    
    def _update_portfolio_values(self, date: datetime):
        """Update portfolio with current market values."""
        # Update stock positions
        for position in self.portfolio.stock_positions:
            symbol = position['symbol']
            stock_price_row = self._get_stock_price_for_date(symbol, date)
            if stock_price_row is not None:
                current_price = stock_price_row['close']
                position['current_price'] = current_price
                position['market_value'] = position['quantity'] * current_price
        
        # Update option positions with real historical pricing
        for position in self.portfolio.option_positions:
            # Use actual historical option data for precise valuation
            historical_value = self._get_historical_option_value(position, date)
            position['current_price'] = historical_value
            position['market_value'] = position['quantity'] * historical_value * 100
    
    def _get_historical_option_value(self, position: Dict, date: datetime) -> float:
        """Get actual historical option value using real market data."""
        try:
            underlying = position['underlying']
            strike = position['strike']
            expiration = position['expiration']
            option_type = position['type']
            option_symbol = position.get('symbol', None)

            # Get current stock price
            if underlying not in self.stock_data:
                return 0.0

            stock_price_row = self._get_stock_price_for_date(underlying, date)
            if stock_price_row is None:
                return 0.0

            current_price = stock_price_row['close']
            time_to_expiry = (expiration - date).days / 365.0

            if time_to_expiry <= 0:
                # Expired - calculate intrinsic value
                if option_type == 'PUT':
                    return max(0, strike - current_price)
                else:  # CALL
                    return max(0, current_price - strike)

            # Try to get actual historical option data first
            if option_symbol:
                historical_option = self._get_historical_option_price(option_symbol, date)
                if historical_option:
                    return historical_option['mid_price']

            # Fallback: Use option chain data to find closest match
            chain_data = self._get_cached_option_chain(underlying, date)
            if chain_data:
                option_list = chain_data['puts'] if option_type == 'PUT' else chain_data['calls']

                # Find exact match by strike and expiration
                for option in option_list:
                    if (abs(option['strike_price'] - strike) < 0.01 and
                        option['expiration_date'].date() == expiration.date()):
                        return (option['bid'] + option['ask']) / 2  # Use mid-price

            # Final fallback: Enhanced Black-Scholes with real volatility
            volatility = stock_price_row.get('volatility', 0.25)
            if pd.isna(volatility) or volatility == 0:
                volatility = 0.25

            greeks = self.data_manager.calculate_option_greeks(
                current_price, strike, time_to_expiry, volatility, 0.05, option_type
            )

            # Enhanced option pricing with volatility smile
            intrinsic = max(0, strike - current_price) if option_type == 'PUT' else max(0, current_price - strike)

            # More accurate time value calculation
            moneyness = current_price / strike
            vol_adjustment = 1.0
            if option_type == 'PUT' and moneyness > 0.95:  # ATM/ITM puts have higher vol
                vol_adjustment = 1.2
            elif option_type == 'CALL' and moneyness < 1.05:  # ATM/ITM calls have higher vol
                vol_adjustment = 1.2

            adjusted_vol = volatility * vol_adjustment
            time_value = abs(greeks['delta']) * current_price * adjusted_vol * np.sqrt(time_to_expiry)

            return intrinsic + time_value

        except Exception as e:
            logger.error("Failed to get historical option value", error=str(e))
            return 0.0
    
    def _process_expirations(self, date: datetime):
        """Process option expirations and assignments."""
        expired_positions = []
        
        for position in self.portfolio.option_positions:
            if position['expiration'].date() == date.date():
                expired_positions.append(position)
        
        for position in expired_positions:
            self._handle_expiration(position, date)
            self.portfolio.option_positions.remove(position)
    
    def _handle_expiration(self, position: Dict, date: datetime):
        """Handle option expiration - assignment or expiration."""
        underlying = position['underlying']
        strike = position['strike']
        option_type = position['type']
        quantity = position['quantity']  # Negative for short positions
        
        # Get final stock price
        if underlying not in self.stock_data or date not in self.stock_data[underlying].index:
            logger.warning("No stock data for expiration", underlying=underlying, date=date)
            return
        
        final_price = self.stock_data[underlying].loc[date, 'close']
        
        # Determine if option is ITM
        if option_type == 'PUT' and quantity < 0:  # Short put
            if final_price < strike:
                # Assignment - we buy stock at strike price
                self._handle_put_assignment(position, date)
            # Else option expires worthless (good for us)
            
        elif option_type == 'CALL' and quantity < 0:  # Short call (covered)
            if final_price > strike:
                # Assignment - our stock gets called away
                self._handle_call_assignment(position, date)
            # Else option expires worthless (good for us)
    
    def _handle_put_assignment(self, position: Dict, date: datetime):
        """Handle put assignment - buy stock at strike."""
        underlying = position['underlying']
        strike = position['strike']
        contracts = abs(position['quantity'])
        shares = contracts * 100
        
        # Add stock position
        stock_position = {
            'symbol': underlying,
            'quantity': shares,
            'entry_price': strike,
            'entry_date': date,
            'current_price': strike,
            'market_value': shares * strike,
            'cost_basis': shares * strike
        }

        self.portfolio.stock_positions.append(stock_position)

        # Update wheel state for put assignment
        self.wheel_state.handle_put_assignment(
            underlying, shares, strike, date
        )
        
        # Deduct cash
        cash_required = shares * strike
        self.portfolio.cash -= cash_required
        
        # Record trade
        self.trade_history.append({
            'date': date,
            'action': 'assignment',
            'symbol': underlying,
            'type': 'PUT',
            'quantity': contracts,
            'price': strike,
            'amount': -cash_required,
            'description': f'Put assignment: bought {shares} shares at ${strike}'
        })
        
        logger.info("Put assigned", 
                   symbol=underlying, 
                   shares=shares, 
                   strike=strike)
    
    def _handle_call_assignment(self, position: Dict, date: datetime):
        """Handle call assignment - sell stock at strike."""
        underlying = position['underlying']
        strike = position['strike']
        contracts = abs(position['quantity'])
        shares = contracts * 100
        
        # Find and remove corresponding stock position
        stock_position = None
        for pos in self.portfolio.stock_positions:
            if pos['symbol'] == underlying and pos['quantity'] >= shares:
                stock_position = pos
                break
        
        if stock_position:
            # Reduce or remove stock position
            if stock_position['quantity'] == shares:
                self.portfolio.stock_positions.remove(stock_position)
            else:
                stock_position['quantity'] -= shares
                stock_position['market_value'] = stock_position['quantity'] * stock_position['current_price']
            
            # Add cash from sale
            cash_received = shares * strike
            self.portfolio.cash += cash_received
            
            # Calculate realized P&L
            cost_basis = shares * stock_position['entry_price']
            realized_pnl = cash_received - cost_basis
            
            # Record trade
            self.trade_history.append({
                'date': date,
                'action': 'assignment',
                'symbol': underlying,
                'type': 'CALL',
                'quantity': contracts,
                'price': strike,
                'amount': cash_received,
                'realized_pnl': realized_pnl,
                'description': f'Call assignment: sold {shares} shares at ${strike}'
            })
            
            # Update wheel state for call assignment
            wheel_result = self.wheel_state.handle_call_assignment(
                underlying, shares, strike, date
            )

            logger.info("Call assigned with wheel state update",
                       symbol=underlying,
                       shares=shares,
                       strike=strike,
                       realized_pnl=realized_pnl,
                       wheel_cycle_completed=wheel_result.get('wheel_cycle_completed', False))

    def _check_gap_risk(self, date: datetime):
        """Check for overnight gaps and close positions if necessary."""
        if not self.config.enable_gap_detection:
            return

        positions_to_close = []

        for position in self.portfolio.option_positions:
            underlying = position.get('underlying')
            if not underlying:
                continue

            # Get current and previous prices
            current_price_row = self._get_stock_price_for_date(underlying, date)
            if current_price_row is None:
                continue

            # Get previous trading day
            previous_date = date - timedelta(days=1)
            while previous_date.weekday() >= 5:  # Skip weekends
                previous_date -= timedelta(days=1)

            previous_price_row = self._get_stock_price_for_date(underlying, previous_date)
            if previous_price_row is None:
                continue

            current_price = current_price_row['close']
            previous_close = previous_price_row['close']

            # Check if position should be closed due to gap
            if self.gap_detector.should_close_position_due_to_gap(
                position, current_price, previous_close
            ):
                positions_to_close.append(position)

        # Close positions that exceed gap thresholds
        for position in positions_to_close:
            self._close_position(position, date, 'gap_risk')

    def _check_early_closures(self, date: datetime):
        """Check for positions to close early (profit targets, stop losses)."""
        positions_to_close = []
        
        for position in self.portfolio.option_positions:
            should_close = self._should_close_position(position, date)
            if should_close:
                positions_to_close.append(position)
        
        for position in positions_to_close:
            self._close_position(position, date, 'early_close')
    
    def _should_close_position(self, position: Dict, date: datetime) -> bool:
        """Determine if position should be closed early."""
        try:
            entry_price = position['entry_price']
            current_price = position['current_price']
            option_type = position['type']
            quantity = position['quantity']
            
            if quantity >= 0:  # Long position (shouldn't happen in wheel)
                return False
            
            # For short positions, profit is when option price decreases
            unrealized_pnl = (entry_price - current_price) * abs(quantity) * 100
            position_value = entry_price * abs(quantity) * 100
            
            if position_value > 0:
                profit_pct = unrealized_pnl / position_value
                
                # Profit target
                if profit_pct >= self.config.profit_target_percent:
                    return True
                
                # Stop loss (only for calls in our strategy)
                if option_type == 'CALL' and self.config.use_call_stop_loss:
                    loss_pct = -profit_pct
                    threshold = self.config.call_stop_loss_percent * self.config.stop_loss_multiplier
                    if loss_pct >= threshold:
                        return True
            
            return False
            
        except Exception as e:
            logger.error("Failed to check position closure", error=str(e))
            return False
    
    def _close_position(self, position: Dict, date: datetime, reason: str):
        """Close an option position with realistic fill simulation."""
        try:
            quantity = abs(position['quantity'])
            underlying = position['underlying']
            option_type = position['type']
            strike = position['strike']
            expiration = position['expiration']

            # Get current market data for realistic closing
            current_market_data = self._get_option_market_data(
                underlying, strike, expiration, option_type, date
            )

            if current_market_data:
                # Use real market data for closing
                bid_price = current_market_data['bid']
                ask_price = current_market_data['ask']
                mid_price = current_market_data['mid_price']
                volume = current_market_data.get('volume', 50)
                spread_pct = ((ask_price - bid_price) / mid_price) if mid_price > 0 else 0

                # For buying back short positions, we typically pay closer to ask
                if spread_pct < 0.05:  # Tight market
                    fill_price = ask_price - (ask_price - mid_price) * 0.7  # 70% toward mid from ask
                elif spread_pct < 0.10:  # Normal market
                    fill_price = ask_price - (ask_price - mid_price) * 0.5  # 50% toward mid from ask
                else:  # Wide market
                    fill_price = ask_price - (ask_price - mid_price) * 0.3  # 30% toward mid from ask

                fill_price = round(max(0.01, fill_price), 2)  # Minimum $0.01, round to penny
            else:
                # Fallback to estimated current price if no market data
                fill_price = position['current_price']
                bid_price = ask_price = mid_price = fill_price
                volume = 50
                spread_pct = 0.10

            # Calculate cost with realistic fill
            cost = quantity * fill_price * 100
            commission = self.backtest_config.commission_per_contract * quantity

            # Realistic slippage based on liquidity
            if volume < 20:
                slippage_factor = 0.0030  # 0.3% for low volume
            elif volume < 100:
                slippage_factor = 0.0015  # 0.15% for medium volume
            else:
                slippage_factor = 0.0008  # 0.08% for high volume

            slippage = cost * slippage_factor
            total_cost = cost + commission + slippage

            # Update cash
            self.portfolio.cash -= total_cost

            # Calculate P&L
            entry_value = position['entry_price'] * quantity * 100
            realized_pnl = entry_value - total_cost

            # Calculate holding period and other metrics
            entry_date = position.get('entry_date', date)
            holding_days = (date - entry_date).days if entry_date else 0

            # Record detailed trade closure
            self.trade_history.append({
                'date': date,
                'action': 'close',
                'symbol': underlying,
                'option_symbol': position.get('symbol', ''),
                'type': option_type,
                'quantity': quantity,
                'strike': strike,
                'expiration': expiration.isoformat() if hasattr(expiration, 'isoformat') else str(expiration),
                'holding_days': holding_days,

                # Entry details
                'entry_price': position['entry_price'],
                'entry_date': entry_date.isoformat() if hasattr(entry_date, 'isoformat') else str(entry_date),
                'entry_bid': position.get('entry_bid', position['entry_price']),
                'entry_ask': position.get('entry_ask', position['entry_price']),
                'entry_volume': position.get('entry_volume', 0),

                # Exit details
                'exit_bid': bid_price,
                'exit_ask': ask_price,
                'exit_mid': mid_price,
                'fill_price': fill_price,
                'exit_volume': volume,
                'spread_pct': spread_pct,

                # Financial details
                'cost': cost,
                'commission': commission,
                'slippage': slippage,
                'total_cost': total_cost,
                'realized_pnl': realized_pnl,
                'return_pct': (realized_pnl / entry_value) if entry_value > 0 else 0,

                # Trade metadata
                'reason': reason,
                'quality_score': position.get('quality_score', 0),
                'description': f'Closed {option_type} {strike} @ ${fill_price:.2f} ({reason})',
                'amount': -total_cost  # For backward compatibility
            })

            # Remove position
            self.portfolio.option_positions.remove(position)

            # Update wheel state for position closure
            self.wheel_state.remove_position(
                underlying, option_type.lower(), quantity, reason
            )

            logger.info("Position closed with realistic fill",
                       symbol=underlying,
                       type=option_type,
                       strike=strike,
                       entry_price=position['entry_price'],
                       exit_price=fill_price,
                       holding_days=holding_days,
                       realized_pnl=realized_pnl,
                       reason=reason)

        except Exception as e:
            logger.error("Failed to close position", error=str(e))
    
    def _find_new_opportunities(self, date: datetime):
        """Look for new trading opportunities using proper wheel strategy logic."""
        # Check if we can open new positions
        if not self._can_open_new_positions():
            return

        # Prioritize covered calls over puts (proper wheel strategy)
        # 1. First, look for call opportunities on stocks we own
        self._scan_call_opportunities(date)

        # 2. Only then look for put opportunities (will be blocked if holding stock)
        self._scan_put_opportunities(date)
    
    def _can_open_new_positions(self) -> bool:
        """Check if we can open new positions."""
        total_positions = len(self.portfolio.option_positions)
        if total_positions >= self.config.max_total_positions:
            return False
        
        # Check available buying power
        available_cash = self.portfolio.cash * (1 - self.config.min_cash_reserve)
        return available_cash > 10000  # Minimum cash needed for new position
    
    def _scan_put_opportunities(self, date: datetime):
        """Scan for put selling opportunities using proper wheel strategy logic."""
        logger.debug("Scanning for put opportunities with wheel state logic", date=date.date(), symbols=self.backtest_config.symbols)

        # Filter symbols by gap risk before scanning
        filtered_symbols = self.gap_detector.filter_stocks_by_gap_risk(
            self.backtest_config.symbols, date
        )

        for symbol in filtered_symbols:
            logger.debug("Checking symbol for put opportunities", symbol=symbol)

            # Check wheel state - only sell puts if not holding stock
            if not self.wheel_state.can_sell_puts(symbol):
                logger.debug("Skipping put opportunity - wheel state blocks puts",
                           symbol=symbol,
                           wheel_phase=self.wheel_state.get_wheel_phase(symbol).value)
                continue

            # Skip if we already have option positions in this stock
            if self._has_position(symbol):
                logger.debug("Skipping symbol - already has position", symbol=symbol)
                continue
            
            # Get current stock price
            # Convert date to match the stock data index format (timezone-aware timestamps)
            stock_price_row = self._get_stock_price_for_date(symbol, date)
            if stock_price_row is None:
                logger.debug("Skipping symbol - no stock data for date", symbol=symbol, date=date)
                continue
            
            current_price = stock_price_row['close']
            logger.debug("Found stock price", symbol=symbol, price=current_price)
            
            # Find suitable put options
            put_opportunity = self._find_suitable_put(symbol, current_price, date)
            
            if put_opportunity:
                logger.info("Executing put trade", symbol=symbol)
                self._execute_put_trade(put_opportunity, date)
            else:
                logger.debug("No suitable put opportunity found", symbol=symbol)
    
    def _scan_call_opportunities(self, date: datetime):
        """Scan for covered call opportunities using proper wheel strategy logic."""
        for stock_pos in self.portfolio.stock_positions:
            symbol = stock_pos['symbol']
            shares = stock_pos['quantity']

            # Need at least 100 shares for covered calls
            if shares < 100:
                continue

            # Check wheel state - only sell calls if we can (have sufficient stock)
            if not self.wheel_state.can_sell_calls(symbol):
                logger.debug("Skipping call opportunity - wheel state blocks calls",
                           symbol=symbol,
                           wheel_phase=self.wheel_state.get_wheel_phase(symbol).value)
                continue

            # Skip if we already have call positions on this stock
            if self._has_call_position(symbol):
                continue

            current_price = stock_pos['current_price']

            # Find suitable call option
            call_opportunity = self._find_suitable_call(symbol, current_price, date)

            if call_opportunity:
                self._execute_call_trade(call_opportunity, date)
    
    def _find_suitable_put(self, symbol: str, current_price: float, date: datetime) -> Optional[Dict]:
        """Find suitable put option to sell using actual historical market data with liquidity filtering."""
        try:
            # Get actual historical options chain using cached data for performance
            options_chain = self._get_cached_option_chain(symbol, date)
            if not options_chain or not options_chain.get('puts'):
                logger.debug("No options chain or puts found", symbol=symbol, date=date.date())
                return None

            logger.debug("Options chain retrieved", symbol=symbol, puts_count=len(options_chain['puts']))

            # Strategy filtering criteria
            put_dte = self.backtest_config.put_target_dte or self.config.put_target_dte
            put_delta_range = self.backtest_config.put_delta_range or self.config.put_delta_range
            min_delta = put_delta_range[0]
            max_delta = put_delta_range[1]
            min_premium = self.config.min_put_premium
            min_volume = getattr(self.config, 'min_option_volume', 10)  # Liquidity filter
            max_bid_ask_spread = getattr(self.config, 'max_bid_ask_spread_pct', 0.15)  # 15% max spread

            suitable_puts = []
            for put in options_chain['puts']:
                # Calculate DTE
                dte = (put['expiration_date'].date() - date.date()).days

                # Extract option data with real bid/ask spreads
                delta = abs(put.get('delta', 0))
                bid_price = put['bid']
                ask_price = put['ask']
                strike_price = put['strike_price']
                volume = put.get('volume', 0)
                last_price = put.get('last_price', (bid_price + ask_price) / 2)

                # Calculate bid-ask spread percentage
                mid_price = (bid_price + ask_price) / 2
                spread_pct = ((ask_price - bid_price) / mid_price) if mid_price > 0 else 1.0

                # Comprehensive filtering with liquidity requirements
                if (dte <= put_dte and dte > 0 and
                    min_delta <= delta <= max_delta and
                    bid_price >= min_premium and
                    strike_price < current_price and  # OTM puts only
                    volume >= min_volume and  # Liquidity filter
                    spread_pct <= max_bid_ask_spread and  # Tight spreads only
                    bid_price > 0.05):  # Minimum meaningful premium

                    # Calculate a quality score based on multiple factors
                    volume_score = min(1.0, volume / 100)  # Higher volume = better
                    spread_score = max(0, 1 - (spread_pct / max_bid_ask_spread))  # Tighter spreads = better
                    premium_score = min(1.0, bid_price / 5.0)  # Higher premium = better (capped at $5)
                    delta_score = 1 - abs(delta - 0.15) / 0.10  # Prefer delta around 0.15

                    quality_score = (volume_score * 0.2 +
                                   spread_score * 0.3 +
                                   premium_score * 0.3 +
                                   max(0, delta_score) * 0.2)

                    suitable_puts.append({
                        'put': put,
                        'delta': delta,
                        'dte': dte,
                        'premium': bid_price,
                        'mid_price': mid_price,
                        'strike': strike_price,
                        'volume': volume,
                        'spread_pct': spread_pct,
                        'quality_score': quality_score,
                        'bid': bid_price,
                        'ask': ask_price
                    })

            logger.debug("Filtering complete", symbol=symbol, suitable_puts=len(suitable_puts),
                        target_dte=put_dte, min_delta=min_delta, max_delta=max_delta,
                        min_premium=min_premium, min_volume=min_volume)

            if not suitable_puts:
                logger.debug("No suitable puts after filtering", symbol=symbol)
                return None

            # Sort by quality score (descending) for best overall option
            suitable_puts.sort(key=lambda x: x['quality_score'], reverse=True)
            best_put = suitable_puts[0]

            logger.info("Selected put for trading",
                       symbol=symbol,
                       option_symbol=best_put['put']['symbol'],
                       premium=best_put['premium'],
                       mid_price=best_put['mid_price'],
                       delta=best_put['delta'],
                       dte=best_put['dte'],
                       volume=best_put['volume'],
                       spread_pct=f"{best_put['spread_pct']:.1%}",
                       quality_score=f"{best_put['quality_score']:.2f}")

            # Check maximum exposure per ticker before returning the opportunity
            current_exposure = self._calculate_current_exposure(symbol)
            new_exposure = best_put['strike'] * 100 * 1  # 1 contract
            total_exposure = current_exposure + new_exposure

            if total_exposure > self.config.max_exposure_per_ticker:
                logger.debug("Put opportunity rejected due to exposure limit",
                           symbol=symbol, current_exposure=current_exposure,
                           new_exposure=new_exposure, total_exposure=total_exposure,
                           limit=self.config.max_exposure_per_ticker)
                return None

            return {
                'symbol': best_put['put']['symbol'],
                'underlying': symbol,
                'option_symbol': best_put['put']['symbol'],
                'strike': best_put['strike'],
                'expiration': best_put['put']['expiration_date'],
                'premium': best_put['premium'],  # Use actual bid price
                'mid_price': best_put['mid_price'],
                'bid': best_put['bid'],
                'ask': best_put['ask'],
                'delta': best_put['delta'],
                'dte': best_put['dte'],
                'volume': best_put['volume'],
                'quality_score': best_put['quality_score'],
                'quantity': 1  # Start with 1 contract
            }

        except Exception as e:
            logger.error("Failed to find suitable put", symbol=symbol, error=str(e))
            return None
    
    def _find_suitable_call(self, symbol: str, current_price: float, date: datetime) -> Optional[Dict]:
        """Find suitable call option to sell."""
        try:
            # Target strike range (OTM calls)
            min_strike = current_price * 1.05  # 5% OTM
            max_strike = current_price * 1.15  # 15% OTM
            
            # Target DTE
            target_dte = self.config.call_target_dte
            expiration_date = date + timedelta(days=target_dte)
            
            # Estimate option parameters
            strike = min_strike + (max_strike - min_strike) * 0.5  # Middle of range
            time_to_expiry = target_dte / 365.0
            
            # Get volatility
            stock_df = self.stock_data[symbol]
            volatility = stock_df.loc[date, 'volatility'] if 'volatility' in stock_df.columns else 0.25
            
            # Calculate Greeks
            greeks = self.data_manager.calculate_option_greeks(
                current_price, strike, time_to_expiry, volatility, 0.05, 'CALL'
            )
            
            # Check delta range
            delta = abs(greeks['delta'])
            if not (self.config.call_delta_range[0] <= delta <= self.config.call_delta_range[1]):
                return None
            
            # Estimate premium
            intrinsic = max(0, current_price - strike)
            time_value = delta * current_price * volatility * np.sqrt(time_to_expiry) * 0.4
            estimated_premium = intrinsic + time_value
            
            if estimated_premium < self.config.min_call_premium:
                return None
            
            return {
                'symbol': f"{symbol}_CALL",
                'underlying': symbol,
                'strike': strike,
                'expiration': expiration_date,
                'type': 'CALL',
                'premium': estimated_premium,
                'delta': greeks['delta'],
                'quantity': 1,  # One contract
                'capital_required': 0  # Covered call
            }
            
        except Exception as e:
            logger.error("Failed to find suitable call", symbol=symbol, error=str(e))
            return None
    
    def _execute_put_trade(self, opportunity: Dict, date: datetime):
        """Execute a put selling trade with realistic fill simulation."""
        try:
            # Check execution gap before proceeding
            symbol = opportunity['underlying']
            execution_check = self._check_execution_gap(symbol, date)

            if not execution_check['can_execute']:
                logger.info("Put trade skipped due to execution gap",
                           symbol=symbol,
                           reason=execution_check['reason'],
                           gap_percent=execution_check.get('current_gap_percent', 0))

                # Record skipped trade
                self.trade_history.append({
                    'date': date,
                    'action': 'skipped',
                    'symbol': symbol,
                    'type': 'PUT',
                    'reason': execution_check['reason'],
                    'gap_percent': execution_check.get('current_gap_percent', 0),
                    'description': f'Trade skipped: {execution_check["reason"]}'
                })
                return

            quantity = opportunity['quantity']

            # Use realistic fill price based on actual market conditions
            bid_price = opportunity['bid']
            ask_price = opportunity['ask']
            mid_price = opportunity['mid_price']
            spread_pct = ((ask_price - bid_price) / mid_price) if mid_price > 0 else 0

            # Simulate realistic fill: slightly worse than mid, better than bid
            # For selling, we typically get filled closer to bid in tight markets
            if spread_pct < 0.05:  # Tight market (< 5% spread)
                fill_price = bid_price + (mid_price - bid_price) * 0.7  # 70% toward mid
            elif spread_pct < 0.10:  # Normal market (5-10% spread)
                fill_price = bid_price + (mid_price - bid_price) * 0.5  # 50% toward mid
            else:  # Wide market (>10% spread)
                fill_price = bid_price + (mid_price - bid_price) * 0.3  # 30% toward mid

            # Round to nearest penny
            fill_price = round(fill_price, 2)

            # Calculate proceeds with realistic fill
            proceeds = quantity * fill_price * 100
            commission = self.backtest_config.commission_per_contract * quantity

            # Add realistic slippage based on volume and spread
            volume = opportunity.get('volume', 50)
            if volume < 20:  # Low volume
                slippage_factor = 0.0020  # 0.2%
            elif volume < 100:  # Medium volume
                slippage_factor = 0.0010  # 0.1%
            else:  # High volume
                slippage_factor = 0.0005  # 0.05%

            slippage = proceeds * slippage_factor
            net_proceeds = proceeds - commission - slippage

            # Update cash
            self.portfolio.cash += net_proceeds

            # Create position with detailed market data
            position = {
                'symbol': opportunity['symbol'],
                'underlying': opportunity['underlying'],
                'strike': opportunity['strike'],
                'expiration': opportunity['expiration'],
                'type': 'PUT',
                'quantity': -quantity,  # Negative for short position
                'entry_price': fill_price,  # Use actual fill price
                'entry_date': date,
                'current_price': fill_price,
                'market_value': -quantity * fill_price * 100,
                # Store original market data for analysis
                'entry_bid': bid_price,
                'entry_ask': ask_price,
                'entry_mid': mid_price,
                'entry_volume': volume,
                'quality_score': opportunity.get('quality_score', 0)
            }

            self.portfolio.option_positions.append(position)

            # Register with wheel state manager
            self.wheel_state.add_put_position(
                opportunity['underlying'], quantity, fill_price, date
            )

            # Record detailed trade with all market data
            self.trade_history.append({
                'date': date,
                'action': 'open',
                'symbol': opportunity['underlying'],
                'option_symbol': opportunity['symbol'],
                'type': 'PUT',
                'quantity': quantity,
                'strike': opportunity['strike'],
                'expiration': opportunity['expiration'].isoformat(),
                'dte': opportunity.get('dte', 0),
                'delta': opportunity.get('delta', 0),

                # Pricing details
                'bid': bid_price,
                'ask': ask_price,
                'mid_price': mid_price,
                'fill_price': fill_price,
                'spread_pct': spread_pct,

                # Execution details
                'proceeds': proceeds,
                'commission': commission,
                'slippage': slippage,
                'net_proceeds': net_proceeds,

                # Market data
                'volume': volume,
                'quality_score': opportunity.get('quality_score', 0),

                'description': f'Sold {quantity} PUT {opportunity["strike"]} @ ${fill_price:.2f}',
                'amount': net_proceeds  # For backward compatibility
            })

            logger.info("Put trade executed with realistic fill",
                       symbol=opportunity['underlying'],
                       strike=opportunity['strike'],
                       bid=bid_price,
                       ask=ask_price,
                       fill=fill_price,
                       volume=volume,
                       net_proceeds=net_proceeds)

        except Exception as e:
            logger.error("Failed to execute put trade", error=str(e))
    
    def _execute_call_trade(self, opportunity: Dict, date: datetime):
        """Execute a covered call trade."""
        try:
            # Check execution gap before proceeding
            symbol = opportunity['underlying']
            execution_check = self._check_execution_gap(symbol, date)

            if not execution_check['can_execute']:
                logger.info("Call trade skipped due to execution gap",
                           symbol=symbol,
                           reason=execution_check['reason'],
                           gap_percent=execution_check.get('current_gap_percent', 0))

                # Record skipped trade
                self.trade_history.append({
                    'date': date,
                    'action': 'skipped',
                    'symbol': symbol,
                    'type': 'CALL',
                    'reason': execution_check['reason'],
                    'gap_percent': execution_check.get('current_gap_percent', 0),
                    'description': f'Trade skipped: {execution_check["reason"]}'
                })
                return

            quantity = opportunity['quantity']
            premium = opportunity['premium']
            
            # Calculate proceeds
            proceeds = quantity * premium * 100
            commission = self.backtest_config.commission_per_contract * quantity
            net_proceeds = proceeds - commission
            
            # Add slippage
            slippage = proceeds * (self.backtest_config.slippage_bps / 10000)
            net_proceeds -= slippage
            
            # Update cash
            self.portfolio.cash += net_proceeds
            
            # Create position
            position = {
                'symbol': opportunity['symbol'],
                'underlying': opportunity['underlying'],
                'strike': opportunity['strike'],
                'expiration': opportunity['expiration'],
                'type': 'CALL',
                'quantity': -quantity,  # Negative for short position
                'entry_price': premium,
                'entry_date': date,
                'current_price': premium,
                'market_value': -quantity * premium * 100  # Negative value for short positions
            }
            
            self.portfolio.option_positions.append(position)

            # Register with wheel state manager
            self.wheel_state.add_call_position(
                opportunity['underlying'], quantity, premium, date
            )

            # Record trade
            self.trade_history.append({
                'date': date,
                'action': 'open',
                'symbol': opportunity['underlying'],
                'type': 'CALL',
                'quantity': quantity,
                'price': premium,
                'amount': net_proceeds,
                'description': f'Sold {quantity} CALL contracts at ${premium:.2f}'
            })
            
            logger.info("Call trade executed", 
                       symbol=opportunity['underlying'],
                       strike=opportunity['strike'],
                       premium=premium,
                       proceeds=net_proceeds)
            
        except Exception as e:
            logger.error("Failed to execute call trade", error=str(e))
    
    def _get_stock_price_for_date(self, symbol: str, date_param) -> Optional[pd.Series]:
        """Get stock price data for a specific date, handling timezone-aware index."""
        if symbol not in self.stock_data:
            return None
        
        stock_df = self.stock_data[symbol]
        
        # Ensure date_param is a date object, not datetime
        if hasattr(date_param, 'date'):
            actual_date = date_param.date()
        else:
            actual_date = date_param
        
        # Try to find a matching date in the index
        # Stock data index contains timezone-aware timestamps like "2025-03-03 05:00:00+00:00"
        # We need to find the row where the date matches our target date
        matching_rows = stock_df[stock_df.index.date == actual_date]
        
        if matching_rows.empty:
            return None
        
        # Return the first matching row (should only be one for daily data)
        return matching_rows.iloc[0]
    
    def _has_position(self, symbol: str) -> bool:
        """Check if we have any positions in a symbol."""
        # Check option positions
        for pos in self.portfolio.option_positions:
            if pos['underlying'] == symbol:
                return True
        
        # Check stock positions
        for pos in self.portfolio.stock_positions:
            if pos['symbol'] == symbol:
                return True
        
        return False
    
    def _has_call_position(self, symbol: str) -> bool:
        """Check if we have call positions on a symbol."""
        for pos in self.portfolio.option_positions:
            if pos['underlying'] == symbol and pos['type'] == 'CALL':
                return True
        return False
    
    def _calculate_at_risk_capital(self) -> float:
        """Calculate total at-risk capital (cash secured for puts + stock positions)."""
        at_risk_capital = 0.0
        
        # Add stock positions value (capital tied up in assigned shares)
        for pos in self.portfolio.stock_positions:
            at_risk_capital += pos['market_value']
        
        # Add cash secured for active short put positions
        for pos in self.portfolio.option_positions:
            if pos['type'] == 'PUT' and pos['quantity'] < 0:  # Short put position
                # Cash secured = strike price * 100 * number of contracts
                cash_secured = pos['strike'] * 100 * abs(pos['quantity'])
                at_risk_capital += cash_secured
        
        return at_risk_capital
    
    def _calculate_current_exposure(self, symbol: str) -> float:
        """Calculate current exposure for a ticker (total assignment value)."""
        current_exposure = 0.0
        
        # Add exposure from existing stock positions
        for pos in self.portfolio.stock_positions:
            if pos.get('underlying', pos.get('symbol')) == symbol:
                current_exposure += abs(pos['market_value'])
        
        # Add exposure from existing short put positions (potential assignment value)
        for pos in self.portfolio.option_positions:
            if pos.get('underlying') == symbol and pos.get('type') == 'PUT' and pos.get('quantity', 0) < 0:
                # For puts: exposure = strike * 100 * number of contracts
                strike = pos.get('strike', 0)
                contracts = abs(pos.get('quantity', 0))
                current_exposure += strike * 100 * contracts
        
        return current_exposure

    def _get_historical_option_price(self, option_symbol: str, date: datetime) -> Optional[Dict]:
        """Get historical option price data for a specific option symbol."""
        try:
            # Check if we have cached option data
            cache_key = f"{option_symbol}_{date.date()}"
            if hasattr(self, '_option_price_cache') and cache_key in self._option_price_cache:
                return self._option_price_cache[cache_key]

            # Fetch historical option data for this specific symbol
            option_data = self.data_manager.get_option_data(
                option_symbol,
                date,
                date + timedelta(days=1)
            )

            if option_data and not option_data.bars.empty:
                # Get the closest date data
                bars_df = option_data.bars
                if date in bars_df.index:
                    row = bars_df.loc[date]
                    price_data = {
                        'mid_price': (row['high'] + row['low']) / 2,
                        'bid': row['low'],
                        'ask': row['high'],
                        'volume': row['volume'],
                        'last_price': row['close']
                    }

                    # Cache the result
                    if not hasattr(self, '_option_price_cache'):
                        self._option_price_cache = {}
                    self._option_price_cache[cache_key] = price_data

                    return price_data

            return None

        except Exception as e:
            logger.debug("Could not fetch historical option price",
                        symbol=option_symbol, date=date, error=str(e))
            return None

    def _get_cached_option_chain(self, underlying: str, date: datetime) -> Optional[Dict]:
        """Get cached option chain data or fetch if not available."""
        try:
            # Check cache first
            cache_key = f"{underlying}_{date.date()}"
            if hasattr(self, '_option_chain_cache') and cache_key in self._option_chain_cache:
                return self._option_chain_cache[cache_key]

            # Get current stock price for chain generation
            stock_price_row = self._get_stock_price_for_date(underlying, date)
            if stock_price_row is None:
                return None

            current_price = stock_price_row['close']

            # Fetch option chain using historical bars (more accurate)
            chain_data = self.data_manager.get_option_chain_historical_bars(
                underlying, date, current_price, 45
            )

            if chain_data and (chain_data['puts'] or chain_data['calls']):
                # Cache the result
                if not hasattr(self, '_option_chain_cache'):
                    self._option_chain_cache = {}
                self._option_chain_cache[cache_key] = chain_data

                logger.debug("Cached option chain",
                           underlying=underlying,
                           puts=len(chain_data['puts']),
                           calls=len(chain_data['calls']))

                return chain_data

            return None

        except Exception as e:
            logger.debug("Could not fetch option chain",
                        underlying=underlying, date=date, error=str(e))
            return None

    def _check_execution_gap(self, symbol: str, date: datetime) -> Dict:
        """Check if trade execution should proceed based on overnight gap.

        Args:
            symbol: Stock symbol to check
            date: Trading date

        Returns:
            Dict with execution decision
        """
        if not self.config.enable_gap_detection:
            return {'can_execute': True, 'reason': 'gap_detection_disabled'}

        try:
            # Get current day's open price
            current_price_row = self._get_stock_price_for_date(symbol, date)
            if current_price_row is None:
                return {'can_execute': False, 'reason': 'no_current_price_data'}

            # Get previous trading day's close
            previous_date = date - timedelta(days=1)
            while previous_date.weekday() >= 5:  # Skip weekends
                previous_date -= timedelta(days=1)

            previous_price_row = self._get_stock_price_for_date(symbol, previous_date)
            if previous_price_row is None:
                return {'can_execute': False, 'reason': 'no_previous_price_data'}

            # Calculate overnight gap using open vs previous close
            current_open = current_price_row['open']
            previous_close = previous_price_row['close']
            gap_percent = ((current_open - previous_close) / previous_close) * 100

            # Check against execution threshold
            if abs(gap_percent) > self.config.execution_gap_threshold:
                return {
                    'can_execute': False,
                    'reason': 'execution_gap_exceeded',
                    'current_gap_percent': gap_percent,
                    'threshold': self.config.execution_gap_threshold,
                    'previous_close': previous_close,
                    'current_open': current_open
                }

            return {
                'can_execute': True,
                'reason': 'gap_within_limits',
                'current_gap_percent': gap_percent,
                'threshold': self.config.execution_gap_threshold,
                'previous_close': previous_close,
                'current_open': current_open
            }

        except Exception as e:
            logger.error("Failed to check execution gap", symbol=symbol, error=str(e))
            return {
                'can_execute': False,
                'reason': 'gap_check_error',
                'error': str(e)
            }

    def _record_daily_state(self, date: datetime):
        """Record daily portfolio state."""
        total_value = self.portfolio.total_value
        at_risk_capital = self._calculate_at_risk_capital()
        
        self.daily_history.append({
            'date': date,
            'cash': self.portfolio.cash,
            'stock_value': sum(pos['market_value'] for pos in self.portfolio.stock_positions),
            'option_value': sum(pos['market_value'] for pos in self.portfolio.option_positions),
            'total_value': total_value,
            'positions': len(self.portfolio.option_positions) + len(self.portfolio.stock_positions),
            'at_risk_capital': at_risk_capital
        })
    
    def _calculate_results(self) -> BacktestResult:
        """Calculate final backtest results."""
        # Create DataFrames
        portfolio_df = pd.DataFrame(self.daily_history)
        portfolio_df.set_index('date', inplace=True)
        
        trade_df = pd.DataFrame(self.trade_history)
        
        # Basic metrics
        initial_capital = self.backtest_config.initial_capital
        final_capital = self.portfolio.total_value
        total_return = (final_capital - initial_capital) / initial_capital
        
        # Time period
        days = (self.backtest_config.end_date - self.backtest_config.start_date).days
        years = days / 365.25
        
        # Handle edge case for single day or very short periods
        if years <= 0 or days <= 1:
            annualized_return = 0  # Can't annualize for same-day periods
        else:
            annualized_return = (final_capital / initial_capital) ** (1 / years) - 1
        
        # Drawdown calculation
        portfolio_df['cummax'] = portfolio_df['total_value'].cummax()
        portfolio_df['drawdown'] = (portfolio_df['total_value'] - portfolio_df['cummax']) / portfolio_df['cummax']
        max_drawdown = portfolio_df['drawdown'].min()
        
        # Sharpe ratio
        portfolio_df['daily_return'] = portfolio_df['total_value'].pct_change()
        daily_returns = portfolio_df['daily_return'].dropna()
        if len(daily_returns) > 0 and daily_returns.std() > 0:
            sharpe_ratio = (daily_returns.mean() * 252) / (daily_returns.std() * np.sqrt(252))
        else:
            sharpe_ratio = 0.0
        
        # Trade statistics
        total_trades = len(trade_df)
        
        # Handle empty trade history
        if total_trades == 0 or 'type' not in trade_df.columns:
            put_trades = 0
            call_trades = 0
            assignments = 0
            assignment_rate = 0.0
            premium_collected = 0.0
        else:
            put_trades = len(trade_df[trade_df['type'] == 'PUT'])
            call_trades = len(trade_df[trade_df['type'] == 'CALL'])
            assignments = len(trade_df[trade_df['action'] == 'assignment'])
            assignment_rate = assignments / max(1, put_trades + call_trades)
            
            # Premium collected
            opening_trades = trade_df[trade_df['action'] == 'open']
            premium_collected = opening_trades['amount'].sum()
        
        # Win rate
        if total_trades == 0 or 'action' not in trade_df.columns:
            win_rate = 0.0
        else:
            closed_trades = trade_df[trade_df['action'] == 'close']
            if len(closed_trades) > 0 and 'realized_pnl' in closed_trades.columns:
                winning_trades = len(closed_trades[closed_trades['realized_pnl'] > 0])
                win_rate = winning_trades / len(closed_trades)
            else:
                win_rate = 0.0
        
        # At-risk capital metrics
        if 'at_risk_capital' in portfolio_df.columns:
            at_risk_values = portfolio_df['at_risk_capital']
            max_at_risk_capital = at_risk_values.max()
            avg_at_risk_capital = at_risk_values.mean()
            # Peak percentage of total capital at risk
            portfolio_values = portfolio_df['total_value']
            at_risk_percentages = at_risk_values / portfolio_values
            peak_at_risk_percentage = at_risk_percentages.max()
        else:
            max_at_risk_capital = 0.0
            avg_at_risk_capital = 0.0
            peak_at_risk_percentage = 0.0
        
        # Create enhanced backtest result with detailed trade analysis
        result = BacktestResult(
            start_date=self.backtest_config.start_date,
            end_date=self.backtest_config.end_date,
            initial_capital=initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            annualized_return=annualized_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            win_rate=win_rate,
            total_trades=total_trades,
            put_trades=put_trades,
            call_trades=call_trades,
            assignments=assignments,
            assignment_rate=assignment_rate,
            premium_collected=premium_collected,
            portfolio_history=portfolio_df,
            trade_history=trade_df,
            max_at_risk_capital=max_at_risk_capital,
            avg_at_risk_capital=avg_at_risk_capital,
            peak_at_risk_percentage=peak_at_risk_percentage
        )

        # Add enhanced trade analysis
        if not trade_df.empty:
            result.detailed_metrics = self._calculate_summary_metrics(trade_df)
            result.trade_analysis = self._perform_trade_analysis(trade_df)

        return result

    def _perform_trade_analysis(self, trade_df: pd.DataFrame) -> Dict:
        """Perform detailed trade analysis for insights."""
        try:
            analysis = {}

            # Analyze by underlying symbol
            if 'symbol' in trade_df.columns:
                symbol_performance = {}
                for symbol in trade_df['symbol'].unique():
                    symbol_trades = trade_df[trade_df['symbol'] == symbol]
                    completed = symbol_trades[symbol_trades['action'].isin(['close', 'assignment'])]

                    if not completed.empty and 'realized_pnl' in completed.columns:
                        pnls = completed['realized_pnl'].dropna()
                        if not pnls.empty:
                            symbol_performance[symbol] = {
                                'total_trades': len(symbol_trades),
                                'completed_trades': len(completed),
                                'total_pnl': pnls.sum(),
                                'win_rate': (pnls > 0).mean(),
                                'avg_pnl': pnls.mean()
                            }

                analysis['by_symbol'] = symbol_performance

            # Analyze execution quality
            if 'spread_pct' in trade_df.columns:
                spreads = trade_df['spread_pct'].dropna()
                if not spreads.empty:
                    analysis['execution_quality'] = {
                        'avg_spread_pct': spreads.mean(),
                        'median_spread_pct': spreads.median(),
                        'tight_spreads_pct': (spreads < 0.05).mean()  # % of trades with <5% spread
                    }

            # Analyze volume and liquidity impact
            if 'volume' in trade_df.columns:
                volumes = trade_df['volume'].dropna()
                if not volumes.empty:
                    analysis['liquidity_analysis'] = {
                        'avg_volume': volumes.mean(),
                        'median_volume': volumes.median(),
                        'high_volume_trades_pct': (volumes >= 100).mean()  # % of trades with >=100 volume
                    }

            # Time-based analysis
            if 'date' in trade_df.columns:
                trade_df['month'] = pd.to_datetime(trade_df['date']).dt.to_period('M')
                monthly_trades = trade_df.groupby('month').size()
                analysis['temporal'] = {
                    'avg_trades_per_month': monthly_trades.mean(),
                    'most_active_month': str(monthly_trades.idxmax()) if not monthly_trades.empty else None
                }

            return analysis

        except Exception as e:
            logger.error("Failed to perform trade analysis", error=str(e))
            return {}