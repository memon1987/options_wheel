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
            for contract in chain:
                options.append({
                    'symbol': contract.symbol,
                    'underlying_symbol': contract.underlying_symbol,
                    'option_type': contract.option_type,
                    'strike_price': float(contract.strike_price),
                    'expiration_date': contract.expiration_date,
                    'bid': float(contract.bid) if contract.bid else 0.0,
                    'ask': float(contract.ask) if contract.ask else 0.0,
                    'last_price': float(contract.last_price) if contract.last_price else 0.0,
                    'volume': int(contract.volume) if contract.volume else 0,
                    'open_interest': int(contract.open_interest) if contract.open_interest else 0,
                    'implied_volatility': float(contract.implied_volatility) if contract.implied_volatility else 0.0,
                    'delta': float(contract.delta) if contract.delta else 0.0,
                    'gamma': float(contract.gamma) if contract.gamma else 0.0,
                    'theta': float(contract.theta) if contract.theta else 0.0,
                    'vega': float(contract.vega) if contract.vega else 0.0
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