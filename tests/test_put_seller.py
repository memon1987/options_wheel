"""Tests for put selling module."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from src.strategy.put_seller import PutSeller
from src.utils.config import Config


class TestPutSellerFindOpportunity:
    """Test PutSeller.find_put_opportunity."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.max_position_size = 0.10
        self.mock_config.min_put_premium = 0.50
        self.mock_config.put_target_dte = 7

        self.put_seller = PutSeller(self.mock_alpaca, self.mock_market_data, self.mock_config)

        # Standard account info for position sizing
        self.mock_alpaca.get_account.return_value = {
            'portfolio_value': 100000.0,
            'buying_power': 50000.0,
            'options_buying_power': 50000.0,
        }

    def test_find_put_opportunity_success(self):
        """Test finding a suitable put opportunity."""
        self.mock_market_data.find_suitable_puts.return_value = [
            {
                'symbol': 'AAPL250117P00080000',
                'strike_price': 80.0,
                'expiration_date': '2025-01-17',
                'dte': 7,
                'delta': -0.15,
                'mid_price': 2.50,
                'annual_return': 0.24,
            }
        ]

        result = self.put_seller.find_put_opportunity('AAPL')

        assert result is not None
        assert result['strategy'] == 'sell_put'
        assert result['symbol'] == 'AAPL'
        assert result['strike_price'] == 80.0
        assert result['premium'] == 2.50
        assert result['contracts'] == 1
        self.mock_market_data.find_suitable_puts.assert_called_once_with('AAPL')

    def test_find_put_opportunity_no_suitable_puts(self):
        """Test returns None when no suitable puts exist."""
        self.mock_market_data.find_suitable_puts.return_value = []

        result = self.put_seller.find_put_opportunity('AAPL')
        assert result is None

    def test_find_put_opportunity_api_error(self):
        """Test returns None on API error."""
        self.mock_market_data.find_suitable_puts.side_effect = Exception("API Error")

        result = self.put_seller.find_put_opportunity('AAPL')
        assert result is None

    def test_find_put_opportunity_blocked_by_wheel_state(self):
        """Test returns None when wheel state blocks put selling."""
        mock_wheel_state = Mock()
        mock_wheel_state.can_sell_puts.return_value = False
        mock_wheel_state.get_wheel_phase.return_value = Mock(value='holding_stock')

        result = self.put_seller.find_put_opportunity('AAPL', wheel_state_manager=mock_wheel_state)
        assert result is None
        self.mock_market_data.find_suitable_puts.assert_not_called()

    def test_find_put_opportunity_wheel_state_allows(self):
        """Test proceeds when wheel state allows put selling."""
        mock_wheel_state = Mock()
        mock_wheel_state.can_sell_puts.return_value = True

        self.mock_market_data.find_suitable_puts.return_value = [
            {
                'symbol': 'AAPL250117P00080000',
                'strike_price': 80.0,
                'expiration_date': '2025-01-17',
                'dte': 7,
                'delta': -0.15,
                'mid_price': 2.50,
                'annual_return': 0.24,
            }
        ]

        result = self.put_seller.find_put_opportunity('AAPL', wheel_state_manager=mock_wheel_state)
        assert result is not None
        assert result['strategy'] == 'sell_put'


class TestPutSellerPositionSizing:
    """Test PutSeller._calculate_position_size."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.max_position_size = 0.10

        self.put_seller = PutSeller(self.mock_alpaca, self.mock_market_data, self.mock_config)

    def test_position_size_normal(self):
        """Test standard position sizing returns 1 contract."""
        self.mock_alpaca.get_account.return_value = {
            'portfolio_value': 100000.0,
            'buying_power': 50000.0,
            'options_buying_power': 50000.0,
        }

        put_option = {
            'symbol': 'AAPL250117P00080000',
            'strike_price': 80.0,
            'mid_price': 2.00,
        }

        result = self.put_seller._calculate_position_size(put_option)

        assert result is not None
        assert result['contracts'] == 1
        assert result['capital_required'] == 8000.0  # 80 * 100
        assert result['max_profit'] == 200.0  # 2.00 * 100
        assert result['breakeven'] == 78.0  # 80 - 2

    def test_position_size_insufficient_buying_power(self):
        """Test returns None when buying power too low."""
        self.mock_alpaca.get_account.return_value = {
            'portfolio_value': 100000.0,
            'buying_power': 100.0,
            'options_buying_power': 100.0,
        }

        put_option = {
            'symbol': 'AAPL250117P00170000',
            'strike_price': 170.0,
            'mid_price': 2.50,
        }

        result = self.put_seller._calculate_position_size(put_option)
        assert result is None

    def test_position_size_exceeds_allocation_limit(self):
        """Test returns None when strike is too high relative to portfolio."""
        self.mock_alpaca.get_account.return_value = {
            'portfolio_value': 10000.0,  # Small portfolio
            'buying_power': 50000.0,
            'options_buying_power': 50000.0,
        }
        # max_position_size=0.10 -> max position value = 1000
        # strike 200 * 100 = 20000 >> 1000

        put_option = {
            'symbol': 'AAPL250117P00200000',
            'strike_price': 200.0,
            'mid_price': 3.00,
        }

        result = self.put_seller._calculate_position_size(put_option)
        assert result is None

    def test_position_size_with_override_buying_power(self):
        """Test position sizing with override buying power parameter."""
        self.mock_alpaca.get_account.return_value = {
            'portfolio_value': 100000.0,
            'buying_power': 50000.0,
            'options_buying_power': 50000.0,
        }

        put_option = {
            'symbol': 'AAPL250117P00080000',
            'strike_price': 80.0,
            'mid_price': 2.00,
        }

        result = self.put_seller._calculate_position_size(put_option, override_buying_power=20000.0)
        assert result is not None
        assert result['contracts'] == 1

    def test_position_size_api_error(self):
        """Test returns None when account API fails."""
        self.mock_alpaca.get_account.side_effect = Exception("API Error")

        put_option = {
            'symbol': 'AAPL250117P00170000',
            'strike_price': 170.0,
            'mid_price': 2.50,
        }

        result = self.put_seller._calculate_position_size(put_option)
        assert result is None


class TestPutSellerCostBasisProtection:
    """Test cost basis and breakeven calculations."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.max_position_size = 0.10

        self.put_seller = PutSeller(self.mock_alpaca, self.mock_market_data, self.mock_config)

        self.mock_alpaca.get_account.return_value = {
            'portfolio_value': 100000.0,
            'buying_power': 50000.0,
            'options_buying_power': 50000.0,
        }

    def test_breakeven_calculation(self):
        """Test that breakeven is correctly calculated as strike - premium."""
        put_option = {
            'symbol': 'MSFT250117P00080000',
            'strike_price': 80.0,
            'mid_price': 3.50,
        }

        result = self.put_seller._calculate_position_size(put_option)

        assert result is not None
        assert result['breakeven'] == 76.5  # 80 - 3.50

    def test_portfolio_allocation_calculated(self):
        """Test portfolio allocation percentage is included."""
        put_option = {
            'symbol': 'MSFT250117P00050000',
            'strike_price': 50.0,
            'mid_price': 1.50,
        }

        result = self.put_seller._calculate_position_size(put_option)

        assert result is not None
        assert 'portfolio_allocation' in result
        # 5000 / 100000 = 0.05
        assert result['portfolio_allocation'] == 0.05


class TestPutSellerExecutePutSale:
    """Test PutSeller.execute_put_sale."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)

        self.put_seller = PutSeller(self.mock_alpaca, self.mock_market_data, self.mock_config)

    def test_execute_put_sale_success(self):
        """Test successful put sale execution."""
        self.mock_alpaca.get_account.return_value = {
            'options_buying_power': 50000.0,
        }
        self.mock_alpaca.place_option_order.return_value = {
            'success': True,
            'order_id': 'order-123',
            'status': 'new',
        }

        opportunity = {
            'option_symbol': 'AAPL250117P00170000',
            'symbol': 'AAPL',
            'contracts': 1,
            'premium': 2.50,
            'strike_price': 170.0,
            'bid': 2.45,
            'ask': 2.55,
            'dte': 7,
        }

        result = self.put_seller.execute_put_sale(opportunity)

        assert result['success'] is True
        assert result['order_id'] == 'order-123'
        assert result['strategy'] == 'sell_put'

    def test_execute_put_sale_insufficient_buying_power(self):
        """Test rejection when buying power is insufficient."""
        self.mock_alpaca.get_account.return_value = {
            'options_buying_power': 1000.0,  # Not enough
        }

        opportunity = {
            'option_symbol': 'AAPL250117P00170000',
            'symbol': 'AAPL',
            'contracts': 1,
            'premium': 2.50,
            'strike_price': 170.0,
            'bid': 2.45,
            'ask': 2.55,
        }

        result = self.put_seller.execute_put_sale(opportunity)

        assert result['success'] is False
        assert result['error'] == 'insufficient_buying_power'

    def test_execute_put_sale_skip_buying_power_check(self):
        """Test execution with buying power check skipped."""
        self.mock_alpaca.place_option_order.return_value = {
            'success': True,
            'order_id': 'order-456',
        }

        opportunity = {
            'option_symbol': 'AAPL250117P00170000',
            'symbol': 'AAPL',
            'contracts': 1,
            'premium': 2.50,
            'strike_price': 170.0,
            'bid': 2.45,
            'ask': 2.55,
        }

        result = self.put_seller.execute_put_sale(opportunity, skip_buying_power_check=True)

        assert result['success'] is True
        # get_account should not be called when skipping
        self.mock_alpaca.get_account.assert_not_called()

    def test_execute_put_sale_order_failure(self):
        """Test handling of order placement failure."""
        self.mock_alpaca.get_account.return_value = {
            'options_buying_power': 50000.0,
        }
        self.mock_alpaca.place_option_order.return_value = {
            'success': False,
            'error_type': 'order_rejected',
            'error_message': 'Insufficient margin',
        }

        opportunity = {
            'option_symbol': 'AAPL250117P00170000',
            'symbol': 'AAPL',
            'contracts': 1,
            'premium': 2.50,
            'strike_price': 170.0,
            'bid': 2.45,
            'ask': 2.55,
        }

        result = self.put_seller.execute_put_sale(opportunity)

        assert result['success'] is False
        assert result['error'] == 'order_rejected'

    def test_execute_put_sale_exception(self):
        """Test handling of unexpected exception during execution."""
        self.mock_alpaca.get_account.side_effect = Exception("Network error")

        opportunity = {
            'option_symbol': 'AAPL250117P00170000',
            'symbol': 'AAPL',
            'contracts': 1,
            'premium': 2.50,
            'strike_price': 170.0,
        }

        result = self.put_seller.execute_put_sale(opportunity)

        assert result['success'] is False
        assert result['error'] == 'buying_power_check_failed'


class TestPutSellerEarlyClose:
    """Test PutSeller.should_close_put_early."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.use_put_stop_loss = False
        self.mock_config.use_dynamic_profit_target = False
        self.mock_config.profit_taking_static_target = 0.50

        self.put_seller = PutSeller(self.mock_alpaca, self.mock_market_data, self.mock_config)

    def test_should_close_at_profit_target(self):
        """Test closing when profit target reached."""
        position = {
            'symbol': 'AAPL250117P00170000',
            'unrealized_pl': 120.0,
            'market_value': -200.0,  # abs = 200, 120/200 = 0.60 > 0.50
        }

        result = self.put_seller.should_close_put_early(position)
        assert result is True

    def test_should_not_close_below_profit_target(self):
        """Test not closing when below profit target."""
        position = {
            'symbol': 'AAPL250117P00170000',
            'unrealized_pl': 50.0,
            'market_value': -200.0,  # abs = 200, 50/200 = 0.25 < 0.50
        }

        result = self.put_seller.should_close_put_early(position)
        assert result is False

    def test_should_not_close_losing_position_no_stop_loss(self):
        """Test not closing losing position when stop loss disabled."""
        position = {
            'symbol': 'AAPL250117P00170000',
            'unrealized_pl': -100.0,
            'market_value': -200.0,
        }

        result = self.put_seller.should_close_put_early(position)
        assert result is False
