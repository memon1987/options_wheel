"""Main backtesting engine for options wheel strategies."""

from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta, date
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
import structlog

from .historical_data import HistoricalDataManager
from .portfolio import BacktestPortfolio
from .trade_simulator import TradeSimulator
from ..strategy.put_seller import PutSeller
from ..strategy.call_seller import CallSeller
from ..api.market_data import MarketDataManager
from ..risk.risk_manager import RiskManager
from ..risk.gap_detector import GapDetector
from ..utils.config import Config

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
        logger.info("Starting backtest", 
                   start=self.backtest_config.start_date,
                   end=self.backtest_config.end_date,
                   symbols=self.backtest_config.symbols)
        
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
        
        logger.info("Backtest completed", 
                   final_value=result.final_capital,
                   total_return=result.total_return,
                   trades=result.total_trades)
        
        return result
    
    def _load_historical_data(self):
        """Pre-load historical stock data for all symbols."""
        logger.info("Loading historical data")
        
        self.stock_data = {}
        
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
            else:
                logger.warning("No data available", symbol=symbol)
    
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
        
        # Update option positions (simplified - would need option pricing model)
        for position in self.portfolio.option_positions:
            # For backtesting, we'll use simplified option pricing
            # In production, this would use historical option data or Black-Scholes
            estimated_value = self._estimate_option_value(position, date)
            position['current_price'] = estimated_value
            position['market_value'] = position['quantity'] * estimated_value * 100
    
    def _estimate_option_value(self, position: Dict, date: datetime) -> float:
        """Estimate option value for backtesting purposes."""
        try:
            underlying = position['underlying']
            strike = position['strike']
            expiration = position['expiration']
            option_type = position['type']
            
            # Get current stock price
            if underlying not in self.stock_data:
                return 0.0
            
            stock_df = self.stock_data[underlying]
            if date not in stock_df.index:
                return 0.0
            
            current_price = stock_df.loc[date, 'close']
            time_to_expiry = (expiration - date).days / 365.0
            
            if time_to_expiry <= 0:
                # Expired - calculate intrinsic value
                if option_type == 'PUT':
                    return max(0, strike - current_price)
                else:  # CALL
                    return max(0, current_price - strike)
            
            # Use implied volatility from historical data or estimate
            volatility = stock_df.loc[date, 'volatility'] if 'volatility' in stock_df.columns else 0.25
            
            # Calculate Greeks and estimate price using Black-Scholes
            greeks = self.data_manager.calculate_option_greeks(
                current_price, strike, time_to_expiry, volatility, 0.05, option_type
            )
            
            # Simplified option pricing (could be enhanced)
            intrinsic = max(0, strike - current_price) if option_type == 'PUT' else max(0, current_price - strike)
            time_value = abs(greeks['delta']) * current_price * 0.1 * time_to_expiry  # Simplified
            
            return intrinsic + time_value
            
        except Exception as e:
            logger.error("Failed to estimate option value", error=str(e))
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
            
            logger.info("Call assigned", 
                       symbol=underlying, 
                       shares=shares, 
                       strike=strike,
                       realized_pnl=realized_pnl)

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
        """Close an option position."""
        try:
            # Simulate buying back the short position
            quantity = abs(position['quantity'])
            price = position['current_price']
            
            # Calculate cost to close
            cost = quantity * price * 100
            commission = self.backtest_config.commission_per_contract * quantity
            total_cost = cost + commission
            
            # Add slippage
            slippage = cost * (self.backtest_config.slippage_bps / 10000)
            total_cost += slippage
            
            # Update cash
            self.portfolio.cash -= total_cost
            
            # Calculate P&L
            entry_value = position['entry_price'] * quantity * 100
            realized_pnl = entry_value - total_cost
            
            # Record trade
            self.trade_history.append({
                'date': date,
                'action': 'close',
                'symbol': position['underlying'],
                'type': position['type'],
                'quantity': quantity,
                'price': price,
                'amount': -total_cost,
                'realized_pnl': realized_pnl,
                'reason': reason,
                'description': f'Closed {position["type"]} position: {reason}'
            })
            
            # Remove position
            self.portfolio.option_positions.remove(position)
            
            logger.info("Position closed", 
                       symbol=position['underlying'],
                       type=position['type'],
                       reason=reason,
                       pnl=realized_pnl)
            
        except Exception as e:
            logger.error("Failed to close position", error=str(e))
    
    def _find_new_opportunities(self, date: datetime):
        """Look for new trading opportunities."""
        # Check if we can open new positions
        if not self._can_open_new_positions():
            return
        
        # Look for put opportunities on stocks we don't own
        self._scan_put_opportunities(date)
        
        # Look for call opportunities on stocks we own
        self._scan_call_opportunities(date)
    
    def _can_open_new_positions(self) -> bool:
        """Check if we can open new positions."""
        total_positions = len(self.portfolio.option_positions)
        if total_positions >= self.config.max_total_positions:
            return False
        
        # Check available buying power
        available_cash = self.portfolio.cash * (1 - self.config.min_cash_reserve)
        return available_cash > 10000  # Minimum cash needed for new position
    
    def _scan_put_opportunities(self, date: datetime):
        """Scan for put selling opportunities."""
        logger.debug("Scanning for put opportunities", date=date.date(), symbols=self.backtest_config.symbols)

        # Filter symbols by gap risk before scanning
        filtered_symbols = self.gap_detector.filter_stocks_by_gap_risk(
            self.backtest_config.symbols, date
        )

        for symbol in filtered_symbols:
            logger.debug("Checking symbol", symbol=symbol)

            # Skip if we already have positions in this stock
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
        """Scan for covered call opportunities."""
        for stock_pos in self.portfolio.stock_positions:
            symbol = stock_pos['symbol']
            shares = stock_pos['quantity']
            
            # Need at least 100 shares for covered calls
            if shares < 100:
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
        """Find suitable put option to sell using actual options chain data."""
        try:
            # Get actual historical options chain using bars data
            put_dte = self.backtest_config.put_target_dte or self.config.put_target_dte
            options_chain = self.data_manager.get_option_chain_historical_bars(
                symbol, date, current_price, put_dte
            )
            if not options_chain or not options_chain.get('puts'):
                logger.debug("No options chain or puts found", symbol=symbol, date=date.date())
                return None
            
            logger.debug("Options chain retrieved", symbol=symbol, puts_count=len(options_chain['puts']))
            
            # Filter puts based on strategy criteria  
            target_dte = put_dte
            put_delta_range = self.backtest_config.put_delta_range or self.config.put_delta_range
            min_delta = put_delta_range[0]
            max_delta = put_delta_range[1]
            min_premium = self.config.min_put_premium
            
            suitable_puts = []
            for put in options_chain['puts']:
                # Calculate DTE
                dte = (put['expiration_date'].date() - date.date()).days
                
                # Check filtering criteria
                delta = abs(put['delta']) if put['delta'] else 0
                bid_price = put['bid']
                strike_price = put['strike_price']
                
                # Filter conditions
                if (dte <= target_dte and dte > 0 and
                    min_delta <= delta <= max_delta and
                    bid_price >= min_premium and
                    strike_price < current_price):  # OTM puts only
                    
                    suitable_puts.append({
                        'put': put,
                        'delta': delta,
                        'dte': dte,
                        'premium': bid_price,
                        'strike': strike_price
                    })
            
            logger.debug("Filtering complete", symbol=symbol, suitable_puts=len(suitable_puts), 
                        target_dte=target_dte, min_delta=min_delta, max_delta=max_delta, 
                        min_premium=min_premium)
            
            if not suitable_puts:
                logger.debug("No suitable puts after filtering", symbol=symbol)
                return None
            
            # Sort by premium (descending) and take the best
            suitable_puts.sort(key=lambda x: x['premium'], reverse=True)
            best_put = suitable_puts[0]
            
            logger.info("Selected put for trading", symbol=symbol, option_symbol=best_put['put']['symbol'],
                       premium=best_put['premium'], delta=best_put['delta'], dte=best_put['dte'])
            
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
                'symbol': symbol,
                'underlying': symbol,
                'option_symbol': best_put['put']['symbol'],
                'strike': best_put['strike'],
                'expiration': best_put['put']['expiration_date'],
                'premium': best_put['premium'],
                'delta': best_put['delta'],
                'dte': best_put['dte'],
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
        """Execute a put selling trade."""
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
            premium = opportunity['premium']
            
            # Calculate proceeds (we receive premium)
            proceeds = quantity * premium * 100
            commission = self.backtest_config.commission_per_contract * quantity
            net_proceeds = proceeds - commission
            
            # Add slippage (reduces our proceeds)
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
                'type': 'PUT',
                'quantity': -quantity,  # Negative for short position
                'entry_price': premium,
                'entry_date': date,
                'current_price': premium,
                'market_value': -quantity * premium * 100  # Negative value for short positions
            }
            
            self.portfolio.option_positions.append(position)
            
            # Record trade
            self.trade_history.append({
                'date': date,
                'action': 'open',
                'symbol': opportunity['underlying'],
                'type': 'PUT',
                'quantity': quantity,
                'price': premium,
                'amount': net_proceeds,
                'description': f'Sold {quantity} PUT contracts at ${premium:.2f}'
            })
            
            logger.info("Put trade executed", 
                       symbol=opportunity['underlying'],
                       strike=opportunity['strike'],
                       premium=premium,
                       proceeds=net_proceeds)
            
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
            if abs(gap_percent) > self.config.max_execution_gap_percent:
                return {
                    'can_execute': False,
                    'reason': 'execution_gap_exceeded',
                    'current_gap_percent': gap_percent,
                    'threshold': self.config.max_execution_gap_percent,
                    'previous_close': previous_close,
                    'current_open': current_open
                }

            return {
                'can_execute': True,
                'reason': 'gap_within_limits',
                'current_gap_percent': gap_percent,
                'threshold': self.config.max_execution_gap_percent,
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
        
        return BacktestResult(
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