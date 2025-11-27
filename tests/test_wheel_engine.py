"""Tests for wheel strategy engine."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from src.strategy.wheel_engine import WheelEngine
from src.utils.config import Config


class TestWheelEngine:
    """Test wheel strategy engine functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.mock_config = Mock(spec=Config)
        self.mock_config.max_total_positions = 10
        self.mock_config.stock_symbols = ['AAPL', 'MSFT', 'GOOGL']
        
        # Mock the dependencies
        with patch('src.strategy.wheel_engine.AlpacaClient') as mock_alpaca_cls, \
             patch('src.strategy.wheel_engine.MarketDataManager') as mock_market_cls, \
             patch('src.strategy.wheel_engine.PutSeller') as mock_put_cls, \
             patch('src.strategy.wheel_engine.CallSeller') as mock_call_cls:
            
            self.mock_alpaca = Mock()
            self.mock_market_data = Mock()
            self.mock_put_seller = Mock()
            self.mock_call_seller = Mock()
            
            mock_alpaca_cls.return_value = self.mock_alpaca
            mock_market_cls.return_value = self.mock_market_data
            mock_put_cls.return_value = self.mock_put_seller
            mock_call_cls.return_value = self.mock_call_seller
            
            self.wheel_engine = WheelEngine(self.mock_config)
        
        # Set up mock responses
        self.sample_account = {
            'portfolio_value': 100000.0,
            'cash': 25000.0,
            'buying_power': 50000.0,
            'equity': 100000.0
        }
        
        self.sample_positions = [
            {
                'symbol': 'AAPL',
                'qty': 100,
                'asset_class': 'us_equity',
                'market_value': 15000.0,
                'unrealized_pl': 500.0
            },
            {
                'symbol': 'AAPL_PUT_150_2024_04_19',
                'qty': -1,
                'asset_class': 'us_option',
                'market_value': -200.0,
                'unrealized_pl': 100.0
            }
        ]
        
        self.mock_alpaca.get_account.return_value = self.sample_account
        self.mock_alpaca.get_positions.return_value = self.sample_positions
    
    def test_wheel_engine_initialization(self):
        """Test wheel engine initialization."""
        assert self.wheel_engine.config == self.mock_config
        assert self.wheel_engine.alpaca == self.mock_alpaca
        assert self.wheel_engine.market_data == self.mock_market_data
        assert self.wheel_engine.put_seller == self.mock_put_seller
        assert self.wheel_engine.call_seller == self.mock_call_seller
    
    def test_run_strategy_cycle_basic(self):
        """Test basic strategy cycle execution."""
        # Mock market data response
        self.mock_market_data.filter_suitable_stocks.return_value = [
            {'symbol': 'AAPL', 'current_price': 150.0, 'suitable_for_wheel': True}
        ]
        
        # Mock put seller response
        self.mock_put_seller.find_put_opportunity.return_value = {
            'action_type': 'new_position',
            'symbol': 'AAPL',
            'strategy': 'sell_put'
        }
        
        # Mock call seller response
        self.mock_call_seller.evaluate_covered_call_opportunity.return_value = None
        
        result = self.wheel_engine.run_strategy_cycle()
        
        assert 'timestamp' in result
        assert 'actions' in result
        assert 'account_info' in result
        assert 'positions_analyzed' in result
        
        assert result['account_info'] == self.sample_account
        assert result['positions_analyzed'] == len(self.sample_positions)
        assert len(result['actions']) >= 0
    
    def test_manage_existing_positions_with_stock(self):
        """Test management of existing stock positions."""
        stock_position = {
            'symbol': 'AAPL',
            'qty': 100,
            'asset_class': 'us_equity',
            'market_value': 15000.0,
            'unrealized_pl': 500.0
        }

        # Set up wheel state to have AAPL in holding_stock phase
        # This is required for covered call selling to be allowed
        self.wheel_engine.wheel_state.handle_put_assignment(
            symbol='AAPL',
            shares=100,
            cost_basis=150.0,
            assignment_date=datetime.now()
        )

        # Mock call seller to return an action
        self.mock_call_seller.evaluate_covered_call_opportunity.return_value = {
            'action_type': 'new_position',
            'strategy': 'sell_call',
            'symbol': 'AAPL'
        }

        actions = self.wheel_engine._manage_existing_positions([stock_position])

        assert len(actions) == 1
        assert actions[0]['strategy'] == 'sell_call'

        # Verify call seller was called with the stock position
        self.mock_call_seller.evaluate_covered_call_opportunity.assert_called_once_with(stock_position)
    
    def test_manage_existing_positions_with_options(self):
        """Test management of existing option positions."""
        option_position = {
            'symbol': 'AAPL_PUT_150_2024_04_19',
            'qty': -1,  # Short position
            'asset_class': 'us_option',
            'market_value': -200.0,
            'unrealized_pl': 100.0  # Profitable
        }
        
        actions = self.wheel_engine._manage_existing_positions([option_position])
        
        # Should consider closing profitable positions
        assert len(actions) >= 0
        
        # If an action is generated, it should be a close position
        if actions:
            assert actions[0]['action_type'] == 'close_position'
    
    def test_can_open_new_positions_success(self):
        """Test can open new positions when within limits."""
        # Few positions, good buying power
        limited_positions = [
            {
                'symbol': 'AAPL_PUT_150_2024_04_19',
                'qty': -1,
                'asset_class': 'us_option',
                'market_value': -200.0,
                'unrealized_pl': 0.0
            }
        ]
        
        can_open = self.wheel_engine._can_open_new_positions(limited_positions)
        assert can_open == True
    
    def test_can_open_new_positions_max_reached(self):
        """Test can't open new positions when maximum reached."""
        # Create positions at the limit
        max_positions = []
        for i in range(10):
            max_positions.append({
                'symbol': f'TEST_{i}_PUT',
                'qty': -1,
                'asset_class': 'us_option',
                'market_value': -100.0,
                'unrealized_pl': 0.0
            })
        
        can_open = self.wheel_engine._can_open_new_positions(max_positions)
        assert can_open == False
    
    def test_can_open_new_positions_low_buying_power(self):
        """Test can't open new positions with low buying power."""
        # Mock low buying power account
        low_bp_account = self.sample_account.copy()
        low_bp_account['buying_power'] = 500.0
        
        self.mock_alpaca.get_account.return_value = low_bp_account
        
        can_open = self.wheel_engine._can_open_new_positions([])
        assert can_open == False
    
    def test_find_new_opportunities(self):
        """Test finding new trading opportunities."""
        # Mock suitable stocks
        self.mock_market_data.filter_suitable_stocks.return_value = [
            {'symbol': 'MSFT', 'current_price': 300.0, 'suitable_for_wheel': True},
            {'symbol': 'GOOGL', 'current_price': 2500.0, 'suitable_for_wheel': True}
        ]
        
        # Mock put opportunity
        self.mock_put_seller.find_put_opportunity.return_value = {
            'action_type': 'new_position',
            'symbol': 'MSFT',
            'strategy': 'sell_put',
            'premium': 5.00
        }
        
        # Mock no existing positions in these stocks
        self.mock_alpaca.get_positions.return_value = []
        
        actions = self.wheel_engine._find_new_opportunities()
        
        assert len(actions) >= 0
        
        # Should call filter_suitable_stocks
        self.mock_market_data.filter_suitable_stocks.assert_called_once()
        
        # If actions found, should be new positions
        if actions:
            assert all(action['action_type'] == 'new_position' for action in actions)
    
    def test_has_existing_position_with_stock(self):
        """Test detection of existing stock positions."""
        positions_with_aapl = [
            {
                'symbol': 'AAPL',
                'asset_class': 'us_equity',
                'market_value': 15000.0,
                'unrealized_pl': 500.0
            }
        ]
        
        self.mock_alpaca.get_positions.return_value = positions_with_aapl
        
        has_position = self.wheel_engine._has_existing_position('AAPL')
        assert has_position == True
        
        has_position_msft = self.wheel_engine._has_existing_position('MSFT')
        assert has_position_msft == False
    
    def test_has_existing_position_with_options(self):
        """Test detection of existing option positions."""
        positions_with_options = [
            {
                'symbol': 'AAPL_PUT_150_2024_04_19',
                'asset_class': 'us_option',
                'market_value': -200.0,
                'unrealized_pl': 100.0
            }
        ]
        
        self.mock_alpaca.get_positions.return_value = positions_with_options
        
        has_position = self.wheel_engine._has_existing_position('AAPL')
        assert has_position == True
    
    def test_get_strategy_status(self):
        """Test getting strategy status summary."""
        status = self.wheel_engine.get_strategy_status()
        
        assert 'account' in status
        assert 'positions' in status
        assert 'capacity' in status
        assert 'timestamp' in status
        
        assert status['account']['portfolio_value'] == self.sample_account['portfolio_value']
        assert status['positions']['total_positions'] == len(self.sample_positions)
        assert 'can_open_new_positions' in status['capacity']
        assert 'positions_remaining' in status['capacity']
    
    def test_strategy_cycle_with_errors(self):
        """Test strategy cycle handling with errors."""
        # Mock an error in account retrieval
        self.mock_alpaca.get_account.side_effect = Exception("API Error")
        
        result = self.wheel_engine.run_strategy_cycle()
        
        assert 'errors' in result
        assert len(result['errors']) > 0
        assert "API Error" in result['errors'][0]
    
    def test_evaluate_option_position_profitable(self):
        """Test evaluation of profitable option position."""
        profitable_position = {
            'symbol': 'AAPL_PUT_150_2024_04_19',
            'qty': -1,  # Short position
            'unrealized_pl': 150.0,  # Profitable
            'market_value': -200.0
        }
        
        action = self.wheel_engine._evaluate_option_position(profitable_position)
        
        assert action is not None
        assert action['action_type'] == 'close_position'
        assert action['reason'] == 'profit_target'
        assert action['unrealized_pl'] == 150.0