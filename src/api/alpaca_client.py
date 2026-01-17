"""Alpaca API client wrapper for options wheel strategy."""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import pandas as pd
import structlog
from functools import wraps

from alpaca.trading.client import TradingClient
from alpaca.data import OptionHistoricalDataClient, StockHistoricalDataClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, AssetClass
from alpaca.data.requests import StockLatestQuoteRequest, OptionChainRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    retry_if_exception,
    before_sleep_log,
    RetryError
)
import requests.exceptions

from ..utils.config import Config

logger = structlog.get_logger(__name__)


def is_rate_limit_error(exception: Exception) -> bool:
    """Check if exception is a rate limit error (HTTP 429)."""
    error_str = str(exception).lower()
    return '429' in error_str or 'rate limit' in error_str or 'too many requests' in error_str


def is_retryable_error(exception: Exception) -> bool:
    """Check if exception is retryable (network issues, timeouts, rate limits)."""
    error_str = str(exception).lower()
    retryable_patterns = [
        'timeout', 'connection', 'network', '429', 'rate limit',
        'too many requests', 'service unavailable', '503', '502', '504'
    ]
    return any(pattern in error_str for pattern in retryable_patterns)


def api_retry(func):
    """Decorator to add retry logic with exponential backoff for API calls.

    Retries on:
    - Network timeouts and connection errors
    - Rate limit errors (429)
    - Service unavailable (503, 502, 504)

    Does NOT retry on:
    - Authentication errors
    - Invalid request errors
    - Business logic errors (insufficient funds, invalid symbol)
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            retry=retry_if_exception_type((
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                ConnectionError,
                TimeoutError
            )) | retry_if_exception(is_retryable_error),
            before_sleep=before_sleep_log(logger, log_level=20),  # INFO level
            reraise=True
        )
        def inner():
            return func(*args, **kwargs)

        try:
            return inner()
        except RetryError as e:
            # Log final failure after all retries exhausted
            logger.error("API call failed after all retries",
                        event_category="error",
                        event_type="api_retry_exhausted",
                        function=func.__name__,
                        error=str(e.last_attempt.exception()) if e.last_attempt else str(e))
            raise e.last_attempt.exception() if e.last_attempt else e

    return wrapper


class AlpacaClient:
    """Wrapper for Alpaca API clients with options trading support."""
    
    def __init__(self, config: Config):
        """Initialize Alpaca client.
        
        Args:
            config: Configuration instance
        """
        self.config = config
        
        # Initialize clients
        self.trading_client = TradingClient(
            api_key=config.alpaca_api_key,
            secret_key=config.alpaca_secret_key,
            paper=config.paper_trading
        )
        
        self.stock_data_client = StockHistoricalDataClient(
            api_key=config.alpaca_api_key,
            secret_key=config.alpaca_secret_key
        )
        
        self.option_data_client = OptionHistoricalDataClient(
            api_key=config.alpaca_api_key,
            secret_key=config.alpaca_secret_key
        )
        
        logger.info("Alpaca client initialized",
                   event_category="system",
                   event_type="client_initialized",
                   paper_trading=config.paper_trading)
    
    # Account Information
    @api_retry
    def get_account(self) -> Dict[str, Any]:
        """Get account information."""
        try:
            account = self.trading_client.get_account()
            return {
                'buying_power': float(account.buying_power),
                'cash': float(account.cash),
                'portfolio_value': float(account.portfolio_value),
                'equity': float(account.equity),
                'options_buying_power': float(account.options_buying_power) if hasattr(account, 'options_buying_power') else 0.0,
                'options_approved_level': getattr(account, 'options_approved_level', 0)
            }
        except Exception as e:
            logger.error("Failed to get account info",
                        event_category="error",
                        event_type="account_info_error",
                        error=str(e))
            raise
    
    @api_retry
    def get_positions(self) -> List[Dict[str, Any]]:
        """Get all current positions."""
        try:
            positions = self.trading_client.get_all_positions()
            return [
                {
                    'symbol': pos.symbol,
                    'qty': float(pos.qty),
                    'side': pos.side,
                    'market_value': float(pos.market_value),
                    'cost_basis': float(pos.cost_basis),
                    'unrealized_pl': float(pos.unrealized_pl),
                    'asset_class': pos.asset_class
                }
                for pos in positions
            ]
        except Exception as e:
            logger.error("Failed to get positions",
                        event_category="error",
                        event_type="positions_error",
                        error=str(e))
            raise

    def get_option_positions(self) -> List[Dict[str, Any]]:
        """Get all current option positions.

        Filters positions to only return US options (excluding stock positions).
        Used for idempotency checks to prevent duplicate option trades.

        Returns:
            List of option position dictionaries
        """
        try:
            positions = self.get_positions()
            option_positions = [
                p for p in positions
                if p.get('asset_class') == AssetClass.US_OPTION
            ]
            logger.debug("Retrieved option positions",
                        event_category="system",
                        event_type="option_positions_retrieved",
                        count=len(option_positions))
            return option_positions
        except Exception as e:
            logger.error("Failed to get option positions",
                        event_category="error",
                        event_type="option_positions_error",
                        error=str(e))
            raise

    # Market Data
    @api_retry
    def get_stock_quote(self, symbol: str) -> Dict[str, Any]:
        """Get latest stock quote using IEX feed for real-time data.

        IEX provides real-time quotes for free (no 15-min delay like SIP).
        While IEX only covers ~3% of market volume, it's sufficient for
        current price quotes in options wheel strategy.

        Args:
            symbol: Stock symbol

        Returns:
            Latest quote data
        """
        try:
            request = StockLatestQuoteRequest(
                symbol_or_symbols=[symbol],
                feed='iex'  # Real-time quotes from IEX exchange (FREE)
            )
            quotes = self.stock_data_client.get_stock_latest_quote(request)
            quote = quotes[symbol]

            return {
                'symbol': symbol,
                'bid': float(quote.bid_price),
                'ask': float(quote.ask_price),
                'bid_size': int(quote.bid_size),
                'ask_size': int(quote.ask_size),
                'timestamp': quote.timestamp
            }
        except Exception as e:
            logger.error("Failed to get stock quote",
                        event_category="error",
                        event_type="stock_quote_error",
                        symbol=symbol,
                        error=str(e))
            raise
    
    @api_retry
    def get_stock_bars(self, symbol: str, days: int = 30) -> pd.DataFrame:
        """Get historical stock bars using SIP feed with 15-min delay buffer.

        Uses SIP (Securities Information Processor) feed for best data quality:
        - 100% market coverage (all 16 exchanges)
        - NBBO (National Best Bid Offer) prices
        - Free with 15-minute delay

        The 20-minute buffer ensures we never query recent data that would
        require a paid subscription. This is perfect for wheel strategy which
        uses daily bars for gap analysis and doesn't need real-time bars.

        Args:
            symbol: Stock symbol
            days: Number of days of history

        Returns:
            DataFrame with OHLCV data
        """
        try:
            # Account for 15-min SIP delay with 20-min buffer for safety
            end_date = datetime.now() - timedelta(minutes=20)
            start_date = end_date - timedelta(days=days)

            request = StockBarsRequest(
                symbol_or_symbols=[symbol],
                timeframe=TimeFrame.Day,
                start=start_date,
                end=end_date
                # No feed parameter = defaults to SIP (best quality, 15-min delayed)
            )

            bars = self.stock_data_client.get_stock_bars(request)

            # Convert to DataFrame
            data = []
            for bar in bars[symbol]:
                data.append({
                    'timestamp': bar.timestamp,
                    'open': float(bar.open),
                    'high': float(bar.high),
                    'low': float(bar.low),
                    'close': float(bar.close),
                    'volume': int(bar.volume)
                })

            df = pd.DataFrame(data)
            df.set_index('timestamp', inplace=True)
            return df

        except Exception as e:
            logger.error("Failed to get stock bars",
                        event_category="error",
                        event_type="stock_bars_error",
                        symbol=symbol,
                        error=str(e))
            raise
    
    @api_retry
    def get_options_chain(self, underlying_symbol: str) -> List[Dict[str, Any]]:
        """Get options chain for a stock.

        Args:
            underlying_symbol: Underlying stock symbol

        Returns:
            List of option contracts
        """
        try:
            request = OptionChainRequest(underlying_symbol=underlying_symbol)
            chain = self.option_data_client.get_option_chain(request)

            options = []
            # Chain is a dictionary with option symbols as keys and OptionsSnapshot data as values
            for option_symbol, contract in chain.items():
                # Parse option symbol to extract details
                # Format: UNH251024C00185000 -> UNH 25/10/24 Call $185
                try:
                    # Extract option type and strike from symbol
                    if 'C' in option_symbol:
                        option_type = 'call'
                        parts = option_symbol.split('C')
                    elif 'P' in option_symbol:
                        option_type = 'put'
                        parts = option_symbol.split('P')
                    else:
                        option_type = 'unknown'
                        parts = [option_symbol, '00000000']

                    # Extract strike price (last 8 digits, divide by 1000)
                    strike_str = parts[1] if len(parts) > 1 else '00000000'
                    strike_price = float(strike_str) / 1000.0

                    # Extract expiration date from symbol (6 digits after underlying)
                    underlying_len = len(underlying_symbol)
                    exp_str = option_symbol[underlying_len:underlying_len+6]
                    if len(exp_str) == 6:
                        # Format: YYMMDD
                        year = 2000 + int(exp_str[:2])
                        month = int(exp_str[2:4])
                        day = int(exp_str[4:6])
                        exp_date = f"{year:04d}-{month:02d}-{day:02d}"
                    else:
                        exp_date = None

                except:
                    option_type = 'unknown'
                    strike_price = 0.0
                    exp_date = None

                # Extract quote data
                quote = getattr(contract, 'latest_quote', None)
                trade = getattr(contract, 'latest_trade', None)
                greeks = getattr(contract, 'greeks', None)

                bid = float(quote.bid_price) if quote and hasattr(quote, 'bid_price') and quote.bid_price else 0.0
                ask = float(quote.ask_price) if quote and hasattr(quote, 'ask_price') and quote.ask_price else 0.0
                bid_size = int(quote.bid_size) if quote and hasattr(quote, 'bid_size') and quote.bid_size else 0
                ask_size = int(quote.ask_size) if quote and hasattr(quote, 'ask_size') and quote.ask_size else 0

                last_price = float(trade.price) if trade and hasattr(trade, 'price') and trade.price else 0.0
                volume = int(trade.size) if trade and hasattr(trade, 'size') and trade.size else 0

                # Extract Greeks
                delta = float(greeks.delta) if greeks and hasattr(greeks, 'delta') and greeks.delta else 0.0
                gamma = float(greeks.gamma) if greeks and hasattr(greeks, 'gamma') and greeks.gamma else 0.0
                theta = float(greeks.theta) if greeks and hasattr(greeks, 'theta') and greeks.theta else 0.0
                vega = float(greeks.vega) if greeks and hasattr(greeks, 'vega') and greeks.vega else 0.0

                implied_vol = float(contract.implied_volatility) if hasattr(contract, 'implied_volatility') and contract.implied_volatility else 0.0

                options.append({
                    'symbol': option_symbol,
                    'underlying_symbol': underlying_symbol,
                    'option_type': option_type,
                    'strike_price': strike_price,
                    'expiration_date': exp_date,
                    'bid': bid,
                    'ask': ask,
                    'bid_size': bid_size,
                    'ask_size': ask_size,
                    'last_price': last_price,
                    'volume': volume,
                    'open_interest': 0,  # Not available in snapshot data
                    'implied_volatility': implied_vol,
                    'delta': delta,
                    'gamma': gamma,
                    'theta': theta,
                    'vega': vega
                })

            return options

        except Exception as e:
            logger.error("Failed to get options chain",
                        event_category="error",
                        event_type="options_chain_error",
                        symbol=underlying_symbol,
                        error=str(e))
            raise
    
    # Trading Operations
    def place_option_order(self, symbol: str, qty: int, side: str, order_type: str = "limit", 
                          limit_price: Optional[float] = None) -> Dict[str, Any]:
        """Place an option order.
        
        Args:
            symbol: Option contract symbol
            qty: Quantity to trade
            side: 'buy' or 'sell'
            order_type: 'market' or 'limit'
            limit_price: Limit price for limit orders
            
        Returns:
            Order response
        """
        try:
            order_side = OrderSide.BUY if side.lower() == 'buy' else OrderSide.SELL
            
            if order_type.lower() == 'market':
                order_data = MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=order_side,
                    time_in_force=TimeInForce.DAY
                )
            else:  # limit order
                if limit_price is None:
                    raise ValueError("Limit price required for limit orders")
                
                order_data = LimitOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=order_side,
                    time_in_force=TimeInForce.DAY,
                    limit_price=limit_price
                )
            
            order = self.trading_client.submit_order(order_data)

            # Validate order response - handle potential None values
            order_id = str(order.id) if order and order.id else None
            order_status = str(order.status) if order and order.status else 'unknown'
            submitted_at = order.submitted_at.isoformat() if order and order.submitted_at else None

            if not order_id:
                logger.error("Order submitted but no order ID returned - treating as failure",
                            event_category="error",
                            event_type="order_missing_id",
                            symbol=symbol, qty=qty, side=side)
                return {
                    'success': False,
                    'error_type': 'missing_order_id',
                    'error': 'Order submitted but no order ID returned',
                    'symbol': symbol,
                    'qty': qty,
                    'side': side
                }

            logger.info("Option order placed",
                       event_category="trade",
                       event_type="order_placed",
                       symbol=symbol, qty=qty, side=side,
                       order_type=order_type, order_id=order_id)

            return {
                'success': True,
                'order_id': order_id,
                'symbol': symbol,
                'qty': qty,
                'side': side,
                'status': order_status,
                'submitted_at': submitted_at
            }
            
        except Exception as e:
            error_msg = str(e)

            # Categorize error for better handling
            error_type = "unknown"
            if "insufficient" in error_msg.lower() or "buying power" in error_msg.lower():
                error_type = "insufficient_funds"
            elif "not found" in error_msg.lower() or "invalid symbol" in error_msg.lower():
                error_type = "invalid_symbol"
            elif "rejected" in error_msg.lower():
                error_type = "order_rejected"
            elif "timeout" in error_msg.lower() or "connection" in error_msg.lower():
                error_type = "connection_error"

            logger.error("Failed to place option order",
                        event_category="error",
                        event_type="order_placement_error",
                        symbol=symbol,
                        qty=qty,
                        side=side,
                        error=error_msg,
                        error_type=error_type)

            # Return structured error instead of raising for better handling upstream
            return {
                'success': False,
                'error_type': error_type,
                'error_message': error_msg,
                'symbol': symbol,
                'qty': qty,
                'side': side
            }
    
    @api_retry
    def get_orders(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get order history.

        Args:
            status: Filter by order status

        Returns:
            List of orders
        """
        try:
            orders = self.trading_client.get_orders()
            
            order_list = []
            for order in orders:
                if status is None or order.status.value.lower() == status.lower():
                    qty = int(order.qty)
                    filled_qty = int(order.filled_qty) if order.filled_qty else 0
                    is_partial_fill = filled_qty > 0 and filled_qty < qty

                    order_list.append({
                        'order_id': order.id,
                        'symbol': order.symbol,
                        'qty': qty,
                        'filled_qty': filled_qty,
                        'remaining_qty': qty - filled_qty,
                        'is_partial_fill': is_partial_fill,
                        'side': order.side.value,
                        'status': order.status.value,
                        'order_type': order.order_type.value,
                        'submitted_at': order.submitted_at,
                        'filled_at': order.filled_at,
                        'filled_avg_price': float(order.filled_avg_price) if order.filled_avg_price else None
                    })
            
            return order_list

        except Exception as e:
            logger.error("Failed to get orders",
                        event_category="error",
                        event_type="orders_error",
                        error=str(e))
            raise

    @api_retry
    def get_order_by_id(self, order_id: str) -> Dict[str, Any]:
        """Get order details by order ID.

        Args:
            order_id: The Alpaca order ID

        Returns:
            Dict with order details including status, fill info
        """
        try:
            order = self.trading_client.get_order_by_id(order_id)
            return {
                'order_id': str(order.id),
                'symbol': order.symbol,
                'status': order.status.value,
                'qty': int(order.qty),
                'filled_qty': int(order.filled_qty) if order.filled_qty else 0,
                'filled_avg_price': float(order.filled_avg_price) if order.filled_avg_price else None,
                'filled_at': order.filled_at.isoformat() if order.filled_at else None,
                'expired_at': order.expired_at.isoformat() if hasattr(order, 'expired_at') and order.expired_at else None,
                'canceled_at': order.canceled_at.isoformat() if hasattr(order, 'canceled_at') and order.canceled_at else None,
                'submitted_at': order.submitted_at.isoformat() if order.submitted_at else None
            }
        except Exception as e:
            logger.error("Failed to get order by ID",
                        event_category="error",
                        event_type="order_lookup_error",
                        order_id=order_id,
                        error=str(e))
            raise

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order.
        
        Args:
            order_id: Order ID to cancel
            
        Returns:
            True if successful
        """
        try:
            self.trading_client.cancel_order_by_id(order_id)
            logger.info("Order cancelled",
                       event_category="trade",
                       event_type="order_cancelled",
                       order_id=order_id)
            return True
        except Exception as e:
            logger.error("Failed to cancel order",
                        event_category="error",
                        event_type="cancel_order_error",
                        order_id=order_id,
                        error=str(e))
            return False