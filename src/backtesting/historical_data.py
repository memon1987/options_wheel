"""Historical data fetching and management for backtesting."""

from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import structlog
from dataclasses import dataclass

from alpaca.data import StockHistoricalDataClient, OptionHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, OptionBarsRequest, OptionChainRequest
from alpaca.data.timeframe import TimeFrame

from ..utils.config import Config
from ..utils.option_symbols import option_symbol_generator

logger = structlog.get_logger(__name__)


@dataclass
class HistoricalOptionData:
    """Container for historical option data."""
    symbol: str
    strike: float
    expiration: datetime
    option_type: str  # 'PUT' or 'CALL'
    bars: pd.DataFrame
    greeks: Optional[pd.DataFrame] = None


class HistoricalDataManager:
    """Manages historical data fetching for backtesting."""
    
    def __init__(self, config: Config):
        """Initialize historical data manager.
        
        Args:
            config: Configuration instance
        """
        self.config = config
        self.stock_client = StockHistoricalDataClient(
            api_key=config.alpaca_api_key,
            secret_key=config.alpaca_secret_key
        )
        self.option_client = OptionHistoricalDataClient(
            api_key=config.alpaca_api_key,
            secret_key=config.alpaca_secret_key
        )
        
        # Cache for data
        self._stock_cache = {}
        self._option_cache = {}
        
    def get_stock_data(
        self, 
        symbol: str, 
        start_date: datetime, 
        end_date: datetime,
        timeframe: TimeFrame = TimeFrame.Day
    ) -> pd.DataFrame:
        """Get historical stock data.
        
        Args:
            symbol: Stock symbol
            start_date: Start date for data
            end_date: End date for data
            timeframe: Data timeframe
            
        Returns:
            DataFrame with OHLCV data
        """
        cache_key = f"{symbol}_{start_date}_{end_date}_{timeframe}"
        
        if cache_key in self._stock_cache:
            logger.debug("Using cached stock data", symbol=symbol)
            return self._stock_cache[cache_key]
        
        try:
            logger.info("Fetching stock data", symbol=symbol, start=start_date, end=end_date)

            # Note: No need for feed parameter or delay buffer in backtesting
            # Backtests query historical data (old dates), not recent SIP data
            # SIP feed is default and provides best quality historical data for free
            request = StockBarsRequest(
                symbol_or_symbols=[symbol],
                timeframe=timeframe,
                start=start_date,
                end=end_date
            )

            bars = self.stock_client.get_stock_bars(request)
            df = bars.df
            
            if df.empty:
                logger.warning("No stock data found", symbol=symbol)
                return pd.DataFrame()
            
            # Reset index to make symbol a column
            df = df.reset_index()
            df = df[df['symbol'] == symbol].copy()
            df.set_index('timestamp', inplace=True)
            
            # Calculate additional metrics
            df['returns'] = df['close'].pct_change()
            df['volatility'] = df['returns'].rolling(window=20).std() * np.sqrt(252)
            df['sma_20'] = df['close'].rolling(window=20).mean()
            df['sma_50'] = df['close'].rolling(window=50).mean()
            
            self._stock_cache[cache_key] = df
            logger.info("Stock data cached", symbol=symbol, rows=len(df))
            
            return df
            
        except Exception as e:
            logger.error("Failed to fetch stock data", symbol=symbol, error=str(e))
            return pd.DataFrame()
    
    def get_option_chain_historical_bars(
        self,
        underlying: str,
        date: datetime,
        underlying_price: float,
        max_dte: int = 45
    ) -> Dict[str, List[Dict]]:
        """Get historical option chain using OptionBarsRequest for accurate pricing.
        
        This method generates likely option symbols and fetches actual historical
        pricing data using the OptionBarsRequest endpoint.
        
        Args:
            underlying: Underlying stock symbol
            date: Date to get option chain for
            underlying_price: Current stock price for strike generation
            max_dte: Maximum days to expiration
            
        Returns:
            Dict with 'puts' and 'calls' lists containing real historical data
        """
        try:
            logger.info("Fetching historical option chain with bars", 
                       underlying=underlying, date=date.date())
            
            # Generate universe of likely option symbols
            option_universe = option_symbol_generator.generate_option_universe(
                underlying, date, underlying_price, max_dte
            )
            
            puts = []
            calls = []
            
            # Fetch historical data for each option in batches
            batch_size = 20  # Process options in batches to avoid API limits
            
            for i in range(0, len(option_universe), batch_size):
                batch = option_universe[i:i + batch_size]
                symbols = [opt['symbol'] for opt in batch]
                
                try:
                    # Request historical bars for this batch
                    bars_request = OptionBarsRequest(
                        symbol_or_symbols=symbols,
                        timeframe=TimeFrame.Day,
                        start=date,
                        end=date + timedelta(days=1)
                    )
                    
                    bars_response = self.option_client.get_option_bars(bars_request)
                    
                    if hasattr(bars_response, 'df') and not bars_response.df.empty:
                        df = bars_response.df
                        
                        # Process each symbol that returned data
                        for symbol in symbols:
                            if symbol in df.index.get_level_values(0):
                                symbol_data = df.loc[symbol]
                                
                                # Get corresponding option metadata
                                opt_meta = next((opt for opt in batch if opt['symbol'] == symbol), None)
                                if not opt_meta:
                                    continue
                                
                                # Extract pricing data (use close price, fallback to open)
                                if not symbol_data.empty:
                                    row = symbol_data.iloc[-1]  # Get last available data
                                    
                                    # Calculate bid/ask from close price (approximate)
                                    close_price = row['close']
                                    spread = max(0.05, close_price * 0.02)  # 2% spread, min $0.05
                                    
                                    option_data = {
                                        'symbol': symbol,
                                        'underlying': underlying,
                                        'strike_price': opt_meta['strike_price'],
                                        'expiration_date': opt_meta['expiration_date'],
                                        'option_type': opt_meta['option_type'],
                                        'last_price': close_price,
                                        'bid': max(0.01, close_price - spread/2),
                                        'ask': close_price + spread/2,
                                        'volume': row['volume'],
                                        'open_interest': 0,  # Not available
                                        'date': date,
                                        'delta': self._estimate_delta(opt_meta, underlying_price, close_price),
                                        'implied_volatility': self._estimate_iv(opt_meta, underlying_price, close_price),
                                        'high': row['high'],
                                        'low': row['low'],
                                        'open': row['open']
                                    }
                                    
                                    if opt_meta['option_type'] == 'PUT':
                                        puts.append(option_data)
                                    else:
                                        calls.append(option_data)
                
                except Exception as e:
                    logger.debug("Batch request failed", symbols=symbols, error=str(e))
                    continue
            
            logger.info("Historical option chain with bars completed", 
                       underlying=underlying, puts=len(puts), calls=len(calls))
            
            return {'puts': puts, 'calls': calls}
            
        except Exception as e:
            logger.error("Failed to get historical option chain with bars", 
                        underlying=underlying, error=str(e))
            return {'puts': [], 'calls': []}
    
    def _estimate_delta(self, option_meta: Dict, underlying_price: float, option_price: float) -> float:
        """Estimate option delta from price and strike relationship."""
        try:
            strike = option_meta['strike_price']
            option_type = option_meta['option_type']
            dte = option_meta['dte']
            
            # Simple delta estimation
            moneyness = underlying_price / strike
            
            if option_type == 'PUT':
                if moneyness > 1.1:  # Deep OTM
                    return -0.05
                elif moneyness > 1.05:  # OTM
                    return -0.15
                elif moneyness > 0.95:  # ATM
                    return -0.50
                elif moneyness > 0.90:  # ITM
                    return -0.75
                else:  # Deep ITM
                    return -0.95
            else:  # CALL
                if moneyness < 0.9:  # Deep OTM
                    return 0.05
                elif moneyness < 0.95:  # OTM
                    return 0.15
                elif moneyness < 1.05:  # ATM
                    return 0.50
                elif moneyness < 1.1:  # ITM
                    return 0.75
                else:  # Deep ITM
                    return 0.95
                    
        except Exception:
            return 0.0
    
    def _estimate_iv(self, option_meta: Dict, underlying_price: float, option_price: float) -> float:
        """Estimate implied volatility from option price."""
        try:
            # Simple IV estimation based on option price relative to intrinsic value
            strike = option_meta['strike_price']
            option_type = option_meta['option_type']
            
            if option_type == 'PUT':
                intrinsic = max(0, strike - underlying_price)
            else:
                intrinsic = max(0, underlying_price - strike)
            
            time_value = max(0, option_price - intrinsic)
            
            # Rough IV estimation: higher time value suggests higher IV
            if time_value < 0.5:
                return 0.20
            elif time_value < 2.0:
                return 0.30
            elif time_value < 5.0:
                return 0.40
            else:
                return 0.50
                
        except Exception:
            return 0.25  # Default IV

    def get_option_chain_historical(
        self,
        underlying: str,
        date: datetime,
        expiration_date: Optional[datetime] = None
    ) -> Dict[str, List[Dict]]:
        """Get historical option chain for a specific date.
        
        Args:
            underlying: Underlying stock symbol
            date: Date to get option chain for
            expiration_date: Specific expiration to filter for
            
        Returns:
            Dict with 'puts' and 'calls' lists
        """
        try:
            logger.info("Fetching option chain", underlying=underlying, date=date)
            
            # Get option chain for the date
            request = OptionChainRequest(
                underlying_symbol=underlying,
                timeframe=TimeFrame.Day,
                start=date,
                end=date + timedelta(days=1)
            )
            
            chain = self.option_client.get_option_chain(request)
            
            puts = []
            calls = []
            
            # The API returns a dictionary with symbol as key and OptionsSnapshot as value
            for symbol, contract in chain.items():
                # Parse the option symbol to get strike, expiration, and type
                parsed = self._parse_option_symbol(symbol)
                if not parsed:
                    continue
                
                # Get data from OptionsSnapshot object
                latest_quote = contract.latest_quote
                latest_trade = contract.latest_trade
                greeks = contract.greeks
                
                option_data = {
                    'symbol': symbol,
                    'underlying': underlying,
                    'strike_price': parsed['strike'],
                    'expiration_date': parsed['expiration'],
                    'option_type': parsed['type'],
                    'last_price': latest_trade.price if latest_trade else 0,
                    'bid': latest_quote.bid_price if latest_quote else 0,
                    'ask': latest_quote.ask_price if latest_quote else 0,
                    'volume': (latest_quote.bid_size + latest_quote.ask_size) if latest_quote else 0,
                    'open_interest': 0,  # Not available in this data structure
                    'date': date,
                    'delta': greeks.delta if greeks else 0,
                    'implied_volatility': contract.implied_volatility or 0
                }
                
                # Filter by expiration if specified
                if expiration_date and parsed['expiration'].date() != expiration_date.date():
                    continue
                
                if parsed['type'].upper() == 'PUT':
                    puts.append(option_data)
                else:
                    calls.append(option_data)
            
            logger.info("Option chain fetched", 
                       underlying=underlying, 
                       puts=len(puts), 
                       calls=len(calls))
            
            return {'puts': puts, 'calls': calls}
            
        except Exception as e:
            logger.error("Failed to fetch option chain", 
                        underlying=underlying, 
                        error=str(e))
            return {'puts': [], 'calls': []}
    
    def get_option_data(
        self,
        option_symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[HistoricalOptionData]:
        """Get historical data for a specific option.
        
        Args:
            option_symbol: Option symbol
            start_date: Start date
            end_date: End date
            
        Returns:
            HistoricalOptionData or None
        """
        cache_key = f"{option_symbol}_{start_date}_{end_date}"
        
        if cache_key in self._option_cache:
            return self._option_cache[cache_key]
        
        try:
            logger.info("Fetching option data", symbol=option_symbol)
            
            request = OptionBarsRequest(
                symbol_or_symbols=[option_symbol],
                timeframe=TimeFrame.Day,
                start=start_date,
                end=end_date
            )
            
            bars = self.option_client.get_option_bars(request)
            df = bars.df
            
            if df.empty:
                logger.warning("No option data found", symbol=option_symbol)
                return None
            
            # Parse option symbol to get details
            parsed = self._parse_option_symbol(option_symbol)
            if not parsed:
                logger.error("Failed to parse option symbol", symbol=option_symbol)
                return None
            
            option_data = HistoricalOptionData(
                symbol=option_symbol,
                strike=parsed['strike'],
                expiration=parsed['expiration'],
                option_type=parsed['type'],
                bars=df
            )
            
            self._option_cache[cache_key] = option_data
            return option_data
            
        except Exception as e:
            logger.error("Failed to fetch option data", 
                        symbol=option_symbol, 
                        error=str(e))
            return None
    
    def _parse_option_symbol(self, option_symbol: str) -> Optional[Dict]:
        """Parse option symbol to extract details.
        
        Args:
            option_symbol: Option symbol string
            
        Returns:
            Dict with parsed details or None
        """
        try:
            # Example: AAPL240315C00150000
            # Format: [SYMBOL][YYMMDD][C/P][STRIKE*1000]
            
            if len(option_symbol) < 15:
                return None
            
            # Find where the date starts (6 digits)
            underlying = ""
            date_part = ""
            option_type = ""
            strike_part = ""
            
            # Parse backwards from known structure
            strike_part = option_symbol[-8:]  # Last 8 digits are strike * 1000
            option_type = option_symbol[-9]   # P or C
            date_part = option_symbol[-15:-9] # YYMMDD
            underlying = option_symbol[:-15]   # Everything before
            
            # Parse strike (divide by 1000)
            strike = float(strike_part) / 1000
            
            # Parse expiration date
            exp_year = 2000 + int(date_part[:2])
            exp_month = int(date_part[2:4])
            exp_day = int(date_part[4:6])
            expiration = datetime(exp_year, exp_month, exp_day)
            
            return {
                'underlying': underlying,
                'strike': strike,
                'expiration': expiration,
                'type': 'PUT' if option_type == 'P' else 'CALL'
            }
            
        except Exception as e:
            logger.error("Failed to parse option symbol", 
                        symbol=option_symbol, 
                        error=str(e))
            return None
    
    def calculate_option_greeks(
        self,
        underlying_price: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float = 0.05,
        option_type: str = 'PUT'
    ) -> Dict[str, float]:
        """Calculate Black-Scholes option Greeks.
        
        Args:
            underlying_price: Current stock price
            strike: Strike price
            time_to_expiry: Time to expiry in years
            volatility: Implied volatility
            risk_free_rate: Risk-free rate
            option_type: 'PUT' or 'CALL'
            
        Returns:
            Dict with Greeks (delta, gamma, theta, vega)
        """
        try:
            import scipy.stats as stats
            import math
            
            if time_to_expiry <= 0:
                return {'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0}
            
            # Black-Scholes calculations
            d1 = (math.log(underlying_price / strike) + 
                  (risk_free_rate + 0.5 * volatility**2) * time_to_expiry) / \
                 (volatility * math.sqrt(time_to_expiry))
            
            d2 = d1 - volatility * math.sqrt(time_to_expiry)
            
            # Standard normal CDF and PDF
            N_d1 = stats.norm.cdf(d1)
            N_d2 = stats.norm.cdf(d2)
            n_d1 = stats.norm.pdf(d1)
            
            if option_type.upper() == 'PUT':
                delta = N_d1 - 1
                theta = (-underlying_price * n_d1 * volatility / (2 * math.sqrt(time_to_expiry)) +
                        risk_free_rate * strike * math.exp(-risk_free_rate * time_to_expiry) * (1 - N_d2))
            else:  # CALL
                delta = N_d1
                theta = (-underlying_price * n_d1 * volatility / (2 * math.sqrt(time_to_expiry)) -
                        risk_free_rate * strike * math.exp(-risk_free_rate * time_to_expiry) * N_d2)
            
            gamma = n_d1 / (underlying_price * volatility * math.sqrt(time_to_expiry))
            vega = underlying_price * n_d1 * math.sqrt(time_to_expiry) / 100  # Per 1% vol change
            
            return {
                'delta': delta,
                'gamma': gamma,
                'theta': theta / 365,  # Per day
                'vega': vega
            }
            
        except Exception as e:
            logger.error("Failed to calculate Greeks", error=str(e))
            return {'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0}
    
    def get_available_expirations(
        self,
        underlying: str,
        date: datetime,
        min_dte: int = 1,
        max_dte: int = 45
    ) -> List[datetime]:
        """Get available option expiration dates for a stock on a given date.
        
        Args:
            underlying: Stock symbol
            date: Date to check
            min_dte: Minimum days to expiration
            max_dte: Maximum days to expiration
            
        Returns:
            List of available expiration dates
        """
        try:
            chain = self.get_option_chain_historical(underlying, date)
            
            expirations = set()
            for option in chain['puts'] + chain['calls']:
                exp_date = option['expiration_date']
                if isinstance(exp_date, str):
                    exp_date = datetime.fromisoformat(exp_date.replace('Z', ''))
                
                dte = (exp_date - date).days
                if min_dte <= dte <= max_dte:
                    expirations.add(exp_date)
            
            return sorted(list(expirations))
            
        except Exception as e:
            logger.error("Failed to get expirations", 
                        underlying=underlying, 
                        error=str(e))
            return []