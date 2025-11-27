"""Tests for Alpaca API client wrapper."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone
import requests.exceptions

from src.api.alpaca_client import (
    AlpacaClient,
    api_retry,
    is_rate_limit_error,
    is_retryable_error
)
from tenacity import RetryError


class TestRetryHelpers:
    """Test retry helper functions."""

    def test_is_rate_limit_error_with_429(self):
        """Test detection of 429 rate limit errors."""
        exc = Exception("HTTP 429: Too Many Requests")
        assert is_rate_limit_error(exc) is True

    def test_is_rate_limit_error_with_rate_limit_message(self):
        """Test detection of rate limit in message."""
        exc = Exception("Rate limit exceeded, please try again later")
        assert is_rate_limit_error(exc) is True

    def test_is_rate_limit_error_with_other_error(self):
        """Test that non-rate-limit errors return False."""
        exc = Exception("Invalid API key")
        assert is_rate_limit_error(exc) is False

    def test_is_retryable_error_timeout(self):
        """Test detection of timeout errors."""
        exc = Exception("Connection timeout after 30 seconds")
        assert is_retryable_error(exc) is True

    def test_is_retryable_error_connection(self):
        """Test detection of connection errors."""
        exc = Exception("Connection refused by server")
        assert is_retryable_error(exc) is True

    def test_is_retryable_error_503(self):
        """Test detection of 503 service unavailable."""
        exc = Exception("HTTP 503: Service Unavailable")
        assert is_retryable_error(exc) is True

    def test_is_retryable_error_502(self):
        """Test detection of 502 bad gateway."""
        exc = Exception("HTTP 502: Bad Gateway")
        assert is_retryable_error(exc) is True

    def test_is_retryable_error_invalid_request(self):
        """Test that invalid request errors are not retryable."""
        exc = Exception("Invalid symbol: XYZ123")
        assert is_retryable_error(exc) is False

    def test_is_retryable_error_auth_error(self):
        """Test that auth errors are not retryable."""
        exc = Exception("Invalid API key provided")
        assert is_retryable_error(exc) is False


class TestApiRetryDecorator:
    """Test the api_retry decorator."""

    def test_api_retry_success_first_attempt(self):
        """Test that successful calls work without retries."""
        call_count = 0

        @api_retry
        def successful_function():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_function()
        assert result == "success"
        assert call_count == 1

    def test_api_retry_retries_on_timeout(self):
        """Test that timeout errors are retried."""
        call_count = 0

        @api_retry
        def timeout_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise requests.exceptions.Timeout("Connection timed out")
            return "success"

        result = timeout_then_success()
        assert result == "success"
        assert call_count == 2

    def test_api_retry_retries_on_connection_error(self):
        """Test that connection errors are retried."""
        call_count = 0

        @api_retry
        def connection_error_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise requests.exceptions.ConnectionError("Failed to connect")
            return "success"

        result = connection_error_then_success()
        assert result == "success"
        assert call_count == 2

    def test_api_retry_gives_up_after_max_attempts(self):
        """Test that retries stop after max attempts."""
        call_count = 0

        @api_retry
        def always_timeout():
            nonlocal call_count
            call_count += 1
            raise requests.exceptions.Timeout("Connection timed out")

        with pytest.raises(requests.exceptions.Timeout):
            always_timeout()

        assert call_count == 3  # Initial + 2 retries

    def test_api_retry_no_retry_on_auth_error(self):
        """Test that authentication errors are not retried."""
        call_count = 0

        @api_retry
        def auth_error():
            nonlocal call_count
            call_count += 1
            raise Exception("Invalid API credentials")

        with pytest.raises(Exception) as exc_info:
            auth_error()

        assert "Invalid API credentials" in str(exc_info.value)
        assert call_count == 1  # No retries

    def test_api_retry_retries_on_rate_limit(self):
        """Test that rate limit errors (429) trigger retries."""
        call_count = 0

        @api_retry
        def rate_limited_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("HTTP 429: Too Many Requests")
            return "success"

        result = rate_limited_then_success()
        assert result == "success"
        assert call_count == 2


class TestAlpacaClientInit:
    """Test AlpacaClient initialization."""

    @patch('src.api.alpaca_client.TradingClient')
    @patch('src.api.alpaca_client.StockHistoricalDataClient')
    @patch('src.api.alpaca_client.OptionHistoricalDataClient')
    def test_client_initialization(
        self,
        mock_option_client,
        mock_stock_client,
        mock_trading_client,
        mock_config
    ):
        """Test that client initializes with correct credentials."""
        client = AlpacaClient(mock_config)

        mock_trading_client.assert_called_once_with(
            api_key='test_api_key',
            secret_key='test_secret_key',
            paper=True
        )
        mock_stock_client.assert_called_once()
        mock_option_client.assert_called_once()

    @patch('src.api.alpaca_client.TradingClient')
    @patch('src.api.alpaca_client.StockHistoricalDataClient')
    @patch('src.api.alpaca_client.OptionHistoricalDataClient')
    def test_client_stores_config(
        self,
        mock_option_client,
        mock_stock_client,
        mock_trading_client,
        mock_config
    ):
        """Test that client stores config reference."""
        client = AlpacaClient(mock_config)
        assert client.config == mock_config


class TestAlpacaClientAccount:
    """Test AlpacaClient account methods."""

    @patch('src.api.alpaca_client.TradingClient')
    @patch('src.api.alpaca_client.StockHistoricalDataClient')
    @patch('src.api.alpaca_client.OptionHistoricalDataClient')
    def test_get_account_returns_dict(
        self,
        mock_option_client,
        mock_stock_client,
        mock_trading_client,
        mock_config
    ):
        """Test get_account returns properly formatted dict."""
        # Setup mock account
        mock_account = MagicMock()
        mock_account.buying_power = "50000.00"
        mock_account.cash = "25000.00"
        mock_account.portfolio_value = "100000.00"
        mock_account.equity = "100000.00"
        mock_account.options_buying_power = "25000.00"
        mock_account.options_approved_level = 2

        mock_trading_client.return_value.get_account.return_value = mock_account

        client = AlpacaClient(mock_config)
        account = client.get_account()

        assert account['buying_power'] == 50000.0
        assert account['cash'] == 25000.0
        assert account['portfolio_value'] == 100000.0
        assert account['equity'] == 100000.0
        assert account['options_buying_power'] == 25000.0
        assert account['options_approved_level'] == 2

    @patch('src.api.alpaca_client.TradingClient')
    @patch('src.api.alpaca_client.StockHistoricalDataClient')
    @patch('src.api.alpaca_client.OptionHistoricalDataClient')
    def test_get_account_handles_missing_options_buying_power(
        self,
        mock_option_client,
        mock_stock_client,
        mock_trading_client,
        mock_config
    ):
        """Test get_account handles accounts without options_buying_power."""
        mock_account = MagicMock(spec=['buying_power', 'cash', 'portfolio_value', 'equity'])
        mock_account.buying_power = "50000.00"
        mock_account.cash = "25000.00"
        mock_account.portfolio_value = "100000.00"
        mock_account.equity = "100000.00"
        # Note: options_buying_power is NOT in spec, so hasattr returns False

        mock_trading_client.return_value.get_account.return_value = mock_account

        client = AlpacaClient(mock_config)
        account = client.get_account()

        assert account['options_buying_power'] == 0.0


class TestAlpacaClientPositions:
    """Test AlpacaClient position methods."""

    @patch('src.api.alpaca_client.TradingClient')
    @patch('src.api.alpaca_client.StockHistoricalDataClient')
    @patch('src.api.alpaca_client.OptionHistoricalDataClient')
    def test_get_positions_empty(
        self,
        mock_option_client,
        mock_stock_client,
        mock_trading_client,
        mock_config
    ):
        """Test get_positions with no positions."""
        mock_trading_client.return_value.get_all_positions.return_value = []

        client = AlpacaClient(mock_config)
        positions = client.get_positions()

        assert positions == []

    @patch('src.api.alpaca_client.TradingClient')
    @patch('src.api.alpaca_client.StockHistoricalDataClient')
    @patch('src.api.alpaca_client.OptionHistoricalDataClient')
    def test_get_positions_returns_list(
        self,
        mock_option_client,
        mock_stock_client,
        mock_trading_client,
        mock_config
    ):
        """Test get_positions returns properly formatted list."""
        mock_position = MagicMock()
        mock_position.symbol = "AAPL"
        mock_position.qty = "100"
        mock_position.side = "long"
        mock_position.market_value = "17500.00"
        mock_position.cost_basis = "16000.00"
        mock_position.unrealized_pl = "1500.00"
        mock_position.asset_class = "us_equity"

        mock_trading_client.return_value.get_all_positions.return_value = [mock_position]

        client = AlpacaClient(mock_config)
        positions = client.get_positions()

        assert len(positions) == 1
        assert positions[0]['symbol'] == "AAPL"
        assert positions[0]['qty'] == 100.0
        assert positions[0]['market_value'] == 17500.0

    @patch('src.api.alpaca_client.TradingClient')
    @patch('src.api.alpaca_client.StockHistoricalDataClient')
    @patch('src.api.alpaca_client.OptionHistoricalDataClient')
    def test_get_option_positions_filters_correctly(
        self,
        mock_option_client,
        mock_stock_client,
        mock_trading_client,
        mock_config
    ):
        """Test get_option_positions filters to only options."""
        from alpaca.trading.enums import AssetClass

        stock_position = MagicMock()
        stock_position.symbol = "AAPL"
        stock_position.qty = "100"
        stock_position.side = "long"
        stock_position.market_value = "17500.00"
        stock_position.cost_basis = "16000.00"
        stock_position.unrealized_pl = "1500.00"
        stock_position.asset_class = AssetClass.US_EQUITY

        option_position = MagicMock()
        option_position.symbol = "AAPL250117P00170000"
        option_position.qty = "-1"
        option_position.side = "short"
        option_position.market_value = "-150.00"
        option_position.cost_basis = "200.00"
        option_position.unrealized_pl = "50.00"
        option_position.asset_class = AssetClass.US_OPTION

        mock_trading_client.return_value.get_all_positions.return_value = [
            stock_position, option_position
        ]

        client = AlpacaClient(mock_config)
        option_positions = client.get_option_positions()

        assert len(option_positions) == 1
        assert "250117P" in option_positions[0]['symbol']


class TestAlpacaClientMarketData:
    """Test AlpacaClient market data methods."""

    @patch('src.api.alpaca_client.TradingClient')
    @patch('src.api.alpaca_client.StockHistoricalDataClient')
    @patch('src.api.alpaca_client.OptionHistoricalDataClient')
    def test_get_stock_quote(
        self,
        mock_option_client,
        mock_stock_client,
        mock_trading_client,
        mock_config
    ):
        """Test get_stock_quote returns formatted data."""
        mock_quote = MagicMock()
        mock_quote.bid_price = 174.50
        mock_quote.ask_price = 175.50
        mock_quote.bid_size = 100
        mock_quote.ask_size = 100
        mock_quote.timestamp = datetime.now(timezone.utc)

        mock_stock_client.return_value.get_stock_latest_quote.return_value = {
            'AAPL': mock_quote
        }

        client = AlpacaClient(mock_config)
        quote = client.get_stock_quote('AAPL')

        assert quote['symbol'] == 'AAPL'
        assert quote['bid'] == 174.50
        assert quote['ask'] == 175.50
        assert quote['bid_size'] == 100
        assert quote['ask_size'] == 100


class TestAlpacaClientOrders:
    """Test AlpacaClient order methods."""

    @patch('src.api.alpaca_client.TradingClient')
    @patch('src.api.alpaca_client.StockHistoricalDataClient')
    @patch('src.api.alpaca_client.OptionHistoricalDataClient')
    def test_place_option_order_success(
        self,
        mock_option_client,
        mock_stock_client,
        mock_trading_client,
        mock_config
    ):
        """Test successful option order placement."""
        mock_order = MagicMock()
        mock_order.id = "test-order-id-123"
        mock_order.status = "new"
        mock_order.symbol = "MSFT250117P00380000"
        mock_order.qty = "1"
        mock_order.filled_qty = "0"
        mock_order.side = "sell"
        mock_order.type = "limit"
        mock_order.limit_price = "2.50"

        mock_trading_client.return_value.submit_order.return_value = mock_order

        client = AlpacaClient(mock_config)
        result = client.place_option_order(
            symbol="MSFT250117P00380000",
            qty=1,
            side="sell",
            order_type="limit",
            limit_price=2.50
        )

        assert result['success'] is True
        assert result['order_id'] == "test-order-id-123"
        assert result['status'] == "new"


class TestAlpacaClientErrorHandling:
    """Test AlpacaClient error handling."""

    @patch('src.api.alpaca_client.TradingClient')
    @patch('src.api.alpaca_client.StockHistoricalDataClient')
    @patch('src.api.alpaca_client.OptionHistoricalDataClient')
    def test_get_account_raises_on_error(
        self,
        mock_option_client,
        mock_stock_client,
        mock_trading_client,
        mock_config
    ):
        """Test get_account raises exception on API error."""
        mock_trading_client.return_value.get_account.side_effect = Exception("API Error")

        client = AlpacaClient(mock_config)

        with pytest.raises(Exception) as exc_info:
            client.get_account()

        assert "API Error" in str(exc_info.value)

    @patch('src.api.alpaca_client.TradingClient')
    @patch('src.api.alpaca_client.StockHistoricalDataClient')
    @patch('src.api.alpaca_client.OptionHistoricalDataClient')
    def test_get_positions_raises_on_error(
        self,
        mock_option_client,
        mock_stock_client,
        mock_trading_client,
        mock_config
    ):
        """Test get_positions raises exception on API error."""
        mock_trading_client.return_value.get_all_positions.side_effect = Exception("API Error")

        client = AlpacaClient(mock_config)

        with pytest.raises(Exception) as exc_info:
            client.get_positions()

        assert "API Error" in str(exc_info.value)
