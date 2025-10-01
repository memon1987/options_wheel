"""Alpaca API client wrapper for options wheel strategy."""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import pandas as pd
import structlog

from alpaca.trading.client import TradingClient
from alpaca.data import OptionHistoricalDataClient, StockHistoricalDataClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, AssetClass
from alpaca.data.requests import StockLatestQuoteRequest, OptionChainRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from ..utils.config import Config

logger = structlog.get_logger(__name__)


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
        
        logger.info("Alpaca client initialized", paper_trading=config.paper_trading)
    
    # Account Information
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
            logger.error("Failed to get account info", error=str(e))
            raise
    
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
            logger.error("Failed to get positions", error=str(e))
            raise
    
    # Market Data
    def get_stock_quote(self, symbol: str) -> Dict[str, Any]:
        """Get latest stock quote.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Latest quote data
        """
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
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
            logger.error("Failed to get stock quote", symbol=symbol, error=str(e))
            raise
    
    def get_stock_bars(self, symbol: str, days: int = 30) -> pd.DataFrame:
        """Get historical stock bars.
        
        Args:
            symbol: Stock symbol
            days: Number of days of history
            
        Returns:
            DataFrame with OHLCV data
        """
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            request = StockBarsRequest(
                symbol_or_symbols=[symbol],
                timeframe=TimeFrame.Day,
                start=start_date,
                end=end_date
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
            logger.error("Failed to get stock bars", symbol=symbol, error=str(e))
            raise
    
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
            logger.error("Failed to get options chain", symbol=underlying_symbol, error=str(e))
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
            
            logger.info("Option order placed", 
                       symbol=symbol, qty=qty, side=side, 
                       order_type=order_type, order_id=order.id)
            
            return {
                'order_id': order.id,
                'symbol': symbol,
                'qty': qty,
                'side': side,
                'status': order.status,
                'submitted_at': order.submitted_at
            }
            
        except Exception as e:
            logger.error("Failed to place option order", 
                        symbol=symbol, qty=qty, side=side, error=str(e))
            raise
    
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
                    order_list.append({
                        'order_id': order.id,
                        'symbol': order.symbol,
                        'qty': int(order.qty),
                        'side': order.side.value,
                        'status': order.status.value,
                        'order_type': order.order_type.value,
                        'submitted_at': order.submitted_at,
                        'filled_at': order.filled_at,
                        'filled_avg_price': float(order.filled_avg_price) if order.filled_avg_price else None
                    })
            
            return order_list
            
        except Exception as e:
            logger.error("Failed to get orders", error=str(e))
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
            logger.info("Order cancelled", order_id=order_id)
            return True
        except Exception as e:
            logger.error("Failed to cancel order", order_id=order_id, error=str(e))
            return False