"""Mock Alpaca API clients and response objects for testing."""

from dataclasses import dataclass, field
from datetime import datetime, timezone, date
from typing import Optional, List, Dict, Any
from decimal import Decimal
from enum import Enum


class AssetClass(str, Enum):
    """Asset class enumeration."""
    US_EQUITY = "us_equity"
    US_OPTION = "us_option"


class OrderSide(str, Enum):
    """Order side enumeration."""
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Order type enumeration."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    """Order status enumeration."""
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    DONE_FOR_DAY = "done_for_day"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REPLACED = "replaced"
    PENDING_CANCEL = "pending_cancel"
    PENDING_REPLACE = "pending_replace"
    PENDING_NEW = "pending_new"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class TimeInForce(str, Enum):
    """Time in force enumeration."""
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"


@dataclass
class MockAccount:
    """Mock Alpaca Account object."""
    id: str = "test-account-id"
    account_number: str = "123456789"
    status: str = "ACTIVE"
    currency: str = "USD"
    cash: str = "25000.00"
    portfolio_value: str = "100000.00"
    buying_power: str = "50000.00"
    equity: str = "100000.00"
    last_equity: str = "99500.00"
    long_market_value: str = "75000.00"
    short_market_value: str = "0.00"
    initial_margin: str = "37500.00"
    maintenance_margin: str = "25000.00"
    daytrading_buying_power: str = "100000.00"
    non_marginable_buying_power: str = "25000.00"
    pattern_day_trader: bool = False
    trading_blocked: bool = False
    transfers_blocked: bool = False
    account_blocked: bool = False
    options_trading_level: int = 2
    options_approved_level: int = 2
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class MockPosition:
    """Mock Alpaca Position object."""
    asset_id: str = "test-asset-id"
    symbol: str = "AAPL"
    exchange: str = "NASDAQ"
    asset_class: AssetClass = AssetClass.US_EQUITY
    asset_marginable: bool = True
    qty: str = "100"
    qty_available: str = "100"
    side: str = "long"
    market_value: str = "17500.00"
    cost_basis: str = "16000.00"
    unrealized_pl: str = "1500.00"
    unrealized_plpc: str = "0.09375"
    unrealized_intraday_pl: str = "250.00"
    unrealized_intraday_plpc: str = "0.0145"
    current_price: str = "175.00"
    lastday_price: str = "172.50"
    change_today: str = "0.0145"
    avg_entry_price: str = "160.00"


@dataclass
class MockOrder:
    """Mock Alpaca Order object."""
    id: str = "test-order-id"
    client_order_id: str = "client-order-123"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    filled_at: Optional[datetime] = None
    expired_at: Optional[datetime] = None
    canceled_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    asset_id: str = "test-asset-id"
    symbol: str = "MSFT250117P00380000"
    asset_class: AssetClass = AssetClass.US_OPTION
    qty: str = "1"
    filled_qty: str = "0"
    filled_avg_price: Optional[str] = None
    order_class: str = "simple"
    order_type: OrderType = OrderType.LIMIT
    type: str = "limit"
    side: OrderSide = OrderSide.SELL
    time_in_force: TimeInForce = TimeInForce.DAY
    limit_price: str = "2.50"
    stop_price: Optional[str] = None
    status: OrderStatus = OrderStatus.NEW
    extended_hours: bool = False
    legs: Optional[List[Any]] = None


@dataclass
class MockOptionContract:
    """Mock Alpaca Option Contract object."""
    id: str = "test-option-contract-id"
    symbol: str = "MSFT250117P00380000"
    name: str = "MSFT Jan 17 2025 380 Put"
    status: str = "active"
    tradable: bool = True
    underlying_symbol: str = "MSFT"
    underlying_asset_id: str = "test-underlying-id"
    expiration_date: date = field(default_factory=lambda: date(2025, 1, 17))
    strike_price: str = "380.00"
    type: str = "put"
    style: str = "american"
    root_symbol: str = "MSFT"
    open_interest: Optional[int] = 5000
    open_interest_date: Optional[date] = None
    close_price: Optional[str] = "2.50"
    close_price_date: Optional[date] = None


@dataclass
class MockBar:
    """Mock Alpaca Bar (OHLCV) object."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    open: float = 175.00
    high: float = 176.50
    low: float = 174.25
    close: float = 175.75
    volume: int = 1000000
    trade_count: int = 5000
    vwap: float = 175.50


@dataclass
class MockQuote:
    """Mock Alpaca Quote object."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    bid_price: float = 174.50
    ask_price: float = 175.50
    bid_size: int = 100
    ask_size: int = 100
    bid_exchange: str = "Q"
    ask_exchange: str = "Q"


class MockTradingClient:
    """Mock Alpaca Trading Client for unit testing."""

    def __init__(
        self,
        api_key: str = "test_key",
        secret_key: str = "test_secret",
        paper: bool = True,
        account: Optional[MockAccount] = None,
        positions: Optional[List[MockPosition]] = None,
        orders: Optional[List[MockOrder]] = None
    ):
        self.api_key = api_key
        self.secret_key = secret_key
        self.paper = paper
        self._account = account or MockAccount()
        self._positions = positions or []
        self._orders = orders or []
        self._order_counter = 0

    def get_account(self) -> MockAccount:
        """Get account information."""
        return self._account

    def get_all_positions(self) -> List[MockPosition]:
        """Get all positions."""
        return self._positions

    def get_open_position(self, symbol: str) -> Optional[MockPosition]:
        """Get position for a specific symbol."""
        for pos in self._positions:
            if pos.symbol == symbol:
                return pos
        return None

    def close_position(self, symbol: str, **kwargs) -> MockOrder:
        """Close a position."""
        self._order_counter += 1
        return MockOrder(
            id=f"close-order-{self._order_counter}",
            symbol=symbol,
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            filled_qty="1",
            filled_avg_price="2.00"
        )

    def submit_order(self, order_data) -> MockOrder:
        """Submit an order."""
        self._order_counter += 1
        order = MockOrder(
            id=f"order-{self._order_counter}",
            symbol=getattr(order_data, 'symbol', 'TEST'),
            qty=str(getattr(order_data, 'qty', 1)),
            side=getattr(order_data, 'side', OrderSide.SELL),
            order_type=getattr(order_data, 'type', OrderType.LIMIT),
            limit_price=str(getattr(order_data, 'limit_price', '0')),
            time_in_force=getattr(order_data, 'time_in_force', TimeInForce.DAY),
            status=OrderStatus.NEW
        )
        self._orders.append(order)
        return order

    def get_orders(self, **kwargs) -> List[MockOrder]:
        """Get orders."""
        return self._orders

    def get_order_by_id(self, order_id: str) -> Optional[MockOrder]:
        """Get order by ID."""
        for order in self._orders:
            if order.id == order_id:
                return order
        return None

    def cancel_order_by_id(self, order_id: str) -> None:
        """Cancel an order."""
        for order in self._orders:
            if order.id == order_id:
                order.status = OrderStatus.CANCELED

    # Helper methods for testing
    def set_account(self, account: MockAccount) -> None:
        """Set the mock account."""
        self._account = account

    def set_positions(self, positions: List[MockPosition]) -> None:
        """Set the mock positions."""
        self._positions = positions

    def add_position(self, position: MockPosition) -> None:
        """Add a position."""
        self._positions.append(position)

    def clear_positions(self) -> None:
        """Clear all positions."""
        self._positions = []


class MockOptionHistoricalDataClient:
    """Mock Alpaca Option Historical Data Client for unit testing."""

    def __init__(
        self,
        api_key: str = "test_key",
        secret_key: str = "test_secret",
        option_chain: Optional[Dict[str, List[MockOptionContract]]] = None
    ):
        self.api_key = api_key
        self.secret_key = secret_key
        self._option_chain = option_chain or {}

    def get_option_chain(self, underlying_symbol: str, **kwargs) -> Dict[str, Any]:
        """Get option chain for underlying."""
        if underlying_symbol in self._option_chain:
            return self._option_chain[underlying_symbol]
        return {'contracts': []}

    def get_option_bars(self, symbols: List[str], **kwargs) -> Dict[str, List[MockBar]]:
        """Get option bars."""
        return {symbol: [MockBar()] for symbol in symbols}

    def get_option_latest_quote(self, symbols: List[str], **kwargs) -> Dict[str, MockQuote]:
        """Get latest option quotes."""
        return {symbol: MockQuote() for symbol in symbols}

    # Helper methods for testing
    def set_option_chain(self, underlying: str, contracts: List[MockOptionContract]) -> None:
        """Set the option chain for an underlying."""
        self._option_chain[underlying] = {'contracts': contracts}


class MockStockHistoricalDataClient:
    """Mock Alpaca Stock Historical Data Client for unit testing."""

    def __init__(
        self,
        api_key: str = "test_key",
        secret_key: str = "test_secret",
        quotes: Optional[Dict[str, MockQuote]] = None,
        bars: Optional[Dict[str, List[MockBar]]] = None
    ):
        self.api_key = api_key
        self.secret_key = secret_key
        self._quotes = quotes or {}
        self._bars = bars or {}

    def get_stock_latest_quote(self, symbol_or_symbols: List[str], **kwargs) -> Dict[str, MockQuote]:
        """Get latest stock quotes."""
        result = {}
        for symbol in symbol_or_symbols:
            if symbol in self._quotes:
                result[symbol] = self._quotes[symbol]
            else:
                result[symbol] = MockQuote()
        return result

    def get_stock_bars(self, symbol_or_symbols: List[str], **kwargs) -> Dict[str, List[MockBar]]:
        """Get stock bars."""
        result = {}
        for symbol in symbol_or_symbols:
            if symbol in self._bars:
                result[symbol] = self._bars[symbol]
            else:
                result[symbol] = [MockBar()]
        return result

    # Helper methods for testing
    def set_quote(self, symbol: str, quote: MockQuote) -> None:
        """Set a quote for a symbol."""
        self._quotes[symbol] = quote

    def set_bars(self, symbol: str, bars: List[MockBar]) -> None:
        """Set bars for a symbol."""
        self._bars[symbol] = bars


# Factory functions for common test scenarios

def create_filled_order(symbol: str = "MSFT250117P00380000", qty: int = 1, price: float = 2.50) -> MockOrder:
    """Create a filled order for testing."""
    return MockOrder(
        id=f"filled-order-{symbol}",
        symbol=symbol,
        qty=str(qty),
        filled_qty=str(qty),
        filled_avg_price=str(price),
        status=OrderStatus.FILLED,
        filled_at=datetime.now(timezone.utc)
    )


def create_short_put_position(
    symbol: str = "MSFT250117P00380000",
    qty: int = -1,
    entry_price: float = 2.50,
    current_price: float = 2.00
) -> MockPosition:
    """Create a short put position for testing."""
    market_value = current_price * abs(qty) * 100 * -1  # Negative for short
    cost_basis = entry_price * abs(qty) * 100
    unrealized_pl = cost_basis + market_value  # Profit when price drops

    return MockPosition(
        symbol=symbol,
        asset_class=AssetClass.US_OPTION,
        qty=str(qty),
        side="short",
        market_value=str(market_value),
        cost_basis=str(cost_basis),
        unrealized_pl=str(unrealized_pl),
        current_price=str(current_price),
        avg_entry_price=str(entry_price)
    )


def create_stock_position(
    symbol: str = "AAPL",
    qty: int = 100,
    entry_price: float = 160.0,
    current_price: float = 175.0
) -> MockPosition:
    """Create a stock position for testing."""
    market_value = current_price * qty
    cost_basis = entry_price * qty
    unrealized_pl = market_value - cost_basis

    return MockPosition(
        symbol=symbol,
        asset_class=AssetClass.US_EQUITY,
        qty=str(qty),
        side="long",
        market_value=str(market_value),
        cost_basis=str(cost_basis),
        unrealized_pl=str(unrealized_pl),
        current_price=str(current_price),
        avg_entry_price=str(entry_price)
    )


def create_option_contract(
    underlying: str = "MSFT",
    strike: float = 380.0,
    expiration: date = date(2025, 1, 17),
    option_type: str = "put"
) -> MockOptionContract:
    """Create an option contract for testing."""
    type_code = "P" if option_type.lower() == "put" else "C"
    strike_str = f"{int(strike * 1000):08d}"
    exp_str = expiration.strftime("%y%m%d")
    symbol = f"{underlying}{exp_str}{type_code}{strike_str}"

    return MockOptionContract(
        symbol=symbol,
        underlying_symbol=underlying,
        expiration_date=expiration,
        strike_price=str(strike),
        type=option_type
    )
