"""Tests for call selling module."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from src.strategy.call_seller import CallSeller
from src.utils.config import Config


class TestCallSellerEvaluateOpportunity:
    """Test CallSeller.evaluate_covered_call_opportunity."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.call_target_dte = 7
        self.mock_config.min_call_premium = 0.30

        self.call_seller = CallSeller(self.mock_alpaca, self.mock_market_data, self.mock_config)

        # Default stock metrics
        self.mock_market_data.get_stock_metrics.return_value = {
            'current_price': 175.0,
        }

    def test_find_suitable_covered_calls(self):
        """Test finding suitable covered call opportunities."""
        stock_position = {
            'symbol': 'AAPL',
            'qty': 100,
            'cost_basis': 16000.0,  # $160/share
            'market_value': 17500.0,
        }

        self.mock_market_data.find_suitable_calls.return_value = [
            {
                'symbol': 'AAPL250117C00185000',
                'strike_price': 185.0,
                'expiration_date': '2025-01-17',
                'dte': 7,
                'delta': 0.15,
                'mid_price': 1.80,
                'annual_return': 0.54,
            }
        ]

        result = self.call_seller.evaluate_covered_call_opportunity(stock_position)

        assert result is not None
        assert result['strategy'] == 'sell_call'
        assert result['symbol'] == 'AAPL'
        assert result['strike_price'] == 185.0
        assert result['contracts'] == 1
        # Verify cost basis was used for filtering
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'AAPL', min_strike_price=160.0
        )

    def test_strike_vs_cost_basis_filtering(self):
        """Test that find_suitable_calls is called with cost basis as min strike."""
        stock_position = {
            'symbol': 'MSFT',
            'qty': 200,
            'cost_basis': 60000.0,  # $300/share
            'market_value': 62000.0,
        }

        self.mock_market_data.find_suitable_calls.return_value = []

        result = self.call_seller.evaluate_covered_call_opportunity(stock_position)

        assert result is None
        # Cost basis per share = 60000 / 200 = 300
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'MSFT', min_strike_price=300.0
        )

    def test_insufficient_shares(self):
        """Test returns None when fewer than 100 shares owned."""
        stock_position = {
            'symbol': 'AAPL',
            'qty': 50,
            'cost_basis': 8000.0,
            'market_value': 8750.0,
        }

        result = self.call_seller.evaluate_covered_call_opportunity(stock_position)

        assert result is None
        self.mock_market_data.find_suitable_calls.assert_not_called()

    def test_no_suitable_calls_found(self):
        """Test returns None when no suitable calls exist."""
        stock_position = {
            'symbol': 'AAPL',
            'qty': 100,
            'cost_basis': 16000.0,
            'market_value': 17500.0,
        }

        self.mock_market_data.find_suitable_calls.return_value = []

        result = self.call_seller.evaluate_covered_call_opportunity(stock_position)
        assert result is None

    def test_multiple_round_lots(self):
        """Test correct contract count for multiple round lots."""
        stock_position = {
            'symbol': 'AAPL',
            'qty': 300,
            'cost_basis': 48000.0,  # $160/share
            'market_value': 52500.0,
        }

        self.mock_market_data.find_suitable_calls.return_value = [
            {
                'symbol': 'AAPL250117C00185000',
                'strike_price': 185.0,
                'expiration_date': '2025-01-17',
                'dte': 7,
                'delta': 0.15,
                'mid_price': 1.80,
                'annual_return': 0.54,
            }
        ]

        result = self.call_seller.evaluate_covered_call_opportunity(stock_position)

        assert result is not None
        assert result['contracts'] == 3  # 300 shares / 100 = 3 contracts

    def test_api_error_returns_none(self):
        """Test returns None on API error."""
        stock_position = {
            'symbol': 'AAPL',
            'qty': 100,
            'cost_basis': 16000.0,
            'market_value': 17500.0,
        }

        self.mock_market_data.find_suitable_calls.side_effect = Exception("API Error")

        result = self.call_seller.evaluate_covered_call_opportunity(stock_position)
        assert result is None


class TestCallSellerExecuteSale:
    """Test CallSeller.execute_call_sale."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)

        self.call_seller = CallSeller(self.mock_alpaca, self.mock_market_data, self.mock_config)

    def test_execute_call_sale_success(self):
        """Test successful call sale execution."""
        self.mock_alpaca.place_option_order.return_value = {
            'success': True,
            'order_id': 'order-789',
            'status': 'new',
        }

        opportunity = {
            'option_symbol': 'AAPL250117C00185000',
            'symbol': 'AAPL',
            'contracts': 1,
            'premium': 1.80,
            'strike_price': 185.0,
            'stock_cost_basis': 16000.0,
            'shares_covered': 100,
            'dte': 7,
        }

        result = self.call_seller.execute_call_sale(opportunity)

        assert result['success'] is True
        assert result['order_id'] == 'order-789'
        assert result['strategy'] == 'sell_call'

    def test_execute_call_sale_blocks_below_cost_basis(self):
        """Test that selling calls below cost basis is blocked."""
        opportunity = {
            'option_symbol': 'AAPL250117C00150000',
            'symbol': 'AAPL',
            'contracts': 1,
            'premium': 3.00,
            'strike_price': 150.0,  # Below cost basis per share
            'stock_cost_basis': 16000.0,  # $160/share for 100 shares
            'shares_covered': 100,
        }

        result = self.call_seller.execute_call_sale(opportunity)

        assert result['success'] is False
        assert result['error'] == 'strike_below_cost_basis'
        # Order should NOT have been placed
        self.mock_alpaca.place_option_order.assert_not_called()

    def test_execute_call_sale_allows_above_cost_basis(self):
        """Test that selling calls above cost basis proceeds."""
        self.mock_alpaca.place_option_order.return_value = {
            'success': True,
            'order_id': 'order-abc',
        }

        opportunity = {
            'option_symbol': 'AAPL250117C00185000',
            'symbol': 'AAPL',
            'contracts': 1,
            'premium': 1.80,
            'strike_price': 185.0,  # Above cost basis per share of $160
            'stock_cost_basis': 16000.0,
            'shares_covered': 100,
            'dte': 7,
        }

        result = self.call_seller.execute_call_sale(opportunity)
        assert result['success'] is True

    def test_execute_call_sale_order_failure(self):
        """Test handling of order placement failure."""
        self.mock_alpaca.place_option_order.return_value = {
            'success': False,
            'error_type': 'order_rejected',
            'error_message': 'Market closed',
        }

        opportunity = {
            'option_symbol': 'AAPL250117C00185000',
            'symbol': 'AAPL',
            'contracts': 1,
            'premium': 1.80,
            'strike_price': 185.0,
            'stock_cost_basis': 16000.0,
            'shares_covered': 100,
        }

        result = self.call_seller.execute_call_sale(opportunity)

        assert result['success'] is False
        assert result['error'] == 'order_rejected'

    def test_execute_call_sale_exception(self):
        """Test handling of unexpected exception."""
        self.mock_alpaca.place_option_order.side_effect = Exception("Connection lost")

        opportunity = {
            'option_symbol': 'AAPL250117C00185000',
            'symbol': 'AAPL',
            'contracts': 1,
            'premium': 1.80,
            'strike_price': 185.0,
            'stock_cost_basis': 16000.0,
            'shares_covered': 100,
        }

        result = self.call_seller.execute_call_sale(opportunity)

        assert result['success'] is False
        assert result['error'] == 'execution_exception'


class TestCallSellerEarlyClose:
    """Test CallSeller.should_close_call_early."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.use_call_stop_loss = True
        self.mock_config.call_stop_loss_percent = 0.50
        self.mock_config.stop_loss_multiplier = 1.5
        self.mock_config.use_dynamic_profit_target = False
        self.mock_config.profit_taking_static_target = 0.50

        self.call_seller = CallSeller(self.mock_alpaca, self.mock_market_data, self.mock_config)

    def test_should_close_at_profit_target(self):
        """Test closing when profit target is reached."""
        position = {
            'symbol': 'AAPL250117C00185000',
            'unrealized_pl': 120.0,
            'market_value': -200.0,  # 120/200 = 0.60 > 0.50
        }

        result = self.call_seller.should_close_call_early(position)
        assert result is True

    def test_should_not_close_below_profit_target(self):
        """Test not closing below profit target."""
        position = {
            'symbol': 'AAPL250117C00185000',
            'unrealized_pl': 50.0,
            'market_value': -200.0,  # 50/200 = 0.25 < 0.50
        }

        result = self.call_seller.should_close_call_early(position)
        assert result is False

    def test_stop_loss_triggered(self):
        """Test stop loss triggers for large losses."""
        # stop_loss_threshold = 0.50 * 1.5 = 0.75
        position = {
            'symbol': 'AAPL250117C00185000',
            'unrealized_pl': -200.0,
            'market_value': -200.0,  # loss_pct = 200/200 = 1.0 > 0.75
        }

        result = self.call_seller.should_close_call_early(position)
        assert result is True

    def test_delta_stop_loss_triggered(self):
        """Test delta-based stop loss when option goes ITM."""
        position = {
            'symbol': 'AAPL250117C00185000',
            'unrealized_pl': -50.0,
            'market_value': -300.0,  # loss_pct = 50/300 = 0.167 < 0.75
        }
        current_option_data = {'delta': 0.7}  # > 0.5, likely ITM

        result = self.call_seller.should_close_call_early(position, current_option_data)
        assert result is True

    def test_exception_returns_false(self):
        """Test that exceptions are handled gracefully."""
        position = {
            'symbol': 'AAPL250117C00185000',
            # Missing required keys to trigger exception
        }

        result = self.call_seller.should_close_call_early(position)
        assert result is False
