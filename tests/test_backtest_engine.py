"""Tests for backtesting engine."""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig
from src.backtesting.portfolio import BacktestPortfolio
from src.utils.config import Config


class TestBacktestEngine:
    """Test backtesting engine functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Mock configuration
        self.mock_config = Mock(spec=Config)
        self.mock_config.put_target_dte = 7
        self.mock_config.call_target_dte = 7
        self.mock_config.put_delta_range = [0.10, 0.20]
        self.mock_config.call_delta_range = [0.10, 0.20]
        self.mock_config.min_put_premium = 0.50
        self.mock_config.min_call_premium = 0.30
        self.mock_config.max_position_size = 0.10
        self.mock_config.min_cash_reserve = 0.20
        self.mock_config.max_total_positions = 10
        self.mock_config.profit_target_percent = 0.50
        self.mock_config.use_call_stop_loss = True
        self.mock_config.call_stop_loss_percent = 0.50
        self.mock_config.stop_loss_multiplier = 1.5
        self.mock_config._config = {
            'strategy': {
                'put_target_dte': 7,
                'call_target_dte': 7,
                'put_delta_range': [0.10, 0.20],
                'call_delta_range': [0.10, 0.20]
            }
        }
        
        # Backtest configuration
        self.backtest_config = BacktestConfig(
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 1, 31),
            initial_capital=100000.0,
            symbols=['AAPL', 'MSFT'],
            commission_per_contract=1.00,
            slippage_bps=5
        )
        
        # Sample stock data
        dates = pd.date_range('2023-01-01', '2023-01-31', freq='D')
        self.sample_stock_data = {
            'AAPL': pd.DataFrame({
                'open': np.random.uniform(150, 160, len(dates)),
                'high': np.random.uniform(160, 170, len(dates)),
                'low': np.random.uniform(140, 150, len(dates)),
                'close': np.random.uniform(150, 160, len(dates)),
                'volume': np.random.uniform(50000000, 100000000, len(dates)),
                'returns': np.random.normal(0, 0.02, len(dates)),
                'volatility': np.random.uniform(0.20, 0.30, len(dates))
            }, index=dates),
            'MSFT': pd.DataFrame({
                'open': np.random.uniform(250, 260, len(dates)),
                'high': np.random.uniform(260, 270, len(dates)),
                'low': np.random.uniform(240, 250, len(dates)),
                'close': np.random.uniform(250, 260, len(dates)),
                'volume': np.random.uniform(30000000, 60000000, len(dates)),
                'returns': np.random.normal(0, 0.02, len(dates)),
                'volatility': np.random.uniform(0.20, 0.30, len(dates))
            }, index=dates)
        }
    
    def test_backtest_engine_initialization(self):
        """Test backtest engine initialization."""
        with patch('src.backtesting.backtest_engine.HistoricalDataManager'):
            engine = BacktestEngine(self.mock_config, self.backtest_config)
            
            assert engine.config == self.mock_config
            assert engine.backtest_config == self.backtest_config
            assert engine.portfolio.initial_cash == 100000.0
            assert engine.portfolio.cash == 100000.0
    
    def test_config_override(self):
        """Test configuration parameter override."""
        backtest_config = BacktestConfig(
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 1, 31),
            put_target_dte=14,  # Override
            put_delta_range=[0.15, 0.25]  # Override
        )
        
        with patch('src.backtesting.backtest_engine.HistoricalDataManager'):
            engine = BacktestEngine(self.mock_config, backtest_config)
            engine._override_config()
            
            assert self.mock_config._config['strategy']['put_target_dte'] == 14
            assert self.mock_config._config['strategy']['put_delta_range'] == [0.15, 0.25]
    
    @patch('src.backtesting.backtest_engine.HistoricalDataManager')
    def test_load_historical_data(self, mock_data_manager):
        """Test historical data loading."""
        # Mock data manager
        mock_data_manager_instance = Mock()
        mock_data_manager.return_value = mock_data_manager_instance
        
        # Mock get_stock_data to return our sample data
        def mock_get_stock_data(symbol, start, end):
            return self.sample_stock_data.get(symbol, pd.DataFrame())
        
        mock_data_manager_instance.get_stock_data = mock_get_stock_data
        
        engine = BacktestEngine(self.mock_config, self.backtest_config)
        engine._load_historical_data()
        
        assert 'AAPL' in engine.stock_data
        assert 'MSFT' in engine.stock_data
        assert len(engine.stock_data['AAPL']) > 0
    
    @patch('src.backtesting.backtest_engine.HistoricalDataManager')
    def test_portfolio_value_update(self, mock_data_manager):
        """Test portfolio value updates."""
        mock_data_manager_instance = Mock()
        mock_data_manager.return_value = mock_data_manager_instance
        mock_data_manager_instance.get_stock_data = lambda *args: pd.DataFrame()
        
        engine = BacktestEngine(self.mock_config, self.backtest_config)
        engine.stock_data = self.sample_stock_data
        
        # Add a stock position
        stock_position = {
            'symbol': 'AAPL',
            'quantity': 100,
            'entry_price': 150.0,
            'current_price': 150.0,
            'market_value': 15000.0
        }
        engine.portfolio.stock_positions.append(stock_position)
        
        # Update values for a specific date
        test_date = datetime(2023, 1, 15)
        engine._update_portfolio_values(test_date)
        
        # Check that current_price was updated
        updated_position = engine.portfolio.stock_positions[0]
        assert updated_position['current_price'] != 150.0  # Should be updated
        assert updated_position['market_value'] == updated_position['current_price'] * 100
    
    @patch('src.backtesting.backtest_engine.HistoricalDataManager')
    def test_option_value_estimation(self, mock_data_manager):
        """Test option value estimation."""
        mock_data_manager_instance = Mock()
        mock_data_manager.return_value = mock_data_manager_instance
        mock_data_manager_instance.calculate_option_greeks = Mock(return_value={
            'delta': -0.15,
            'gamma': 0.01,
            'theta': -0.05,
            'vega': 0.20
        })
        
        engine = BacktestEngine(self.mock_config, self.backtest_config)
        engine.stock_data = self.sample_stock_data
        
        # Create option position
        option_position = {
            'underlying': 'AAPL',
            'strike': 145.0,
            'expiration': datetime(2023, 1, 20),
            'type': 'PUT'
        }
        
        test_date = datetime(2023, 1, 15)
        estimated_value = engine._estimate_option_value(option_position, test_date)
        
        assert isinstance(estimated_value, float)
        assert estimated_value >= 0  # Option value should be non-negative
    
    @patch('src.backtesting.backtest_engine.HistoricalDataManager')
    def test_trading_day_check(self, mock_data_manager):
        """Test trading day identification."""
        mock_data_manager.return_value = Mock()
        
        engine = BacktestEngine(self.mock_config, self.backtest_config)
        
        # Test weekdays (should be trading days)
        monday = datetime(2023, 1, 2)  # Monday
        tuesday = datetime(2023, 1, 3)  # Tuesday
        
        assert engine._is_trading_day(monday) == True
        assert engine._is_trading_day(tuesday) == True
        
        # Test weekends (should not be trading days)
        saturday = datetime(2023, 1, 7)  # Saturday
        sunday = datetime(2023, 1, 8)    # Sunday
        
        assert engine._is_trading_day(saturday) == False
        assert engine._is_trading_day(sunday) == False
    
    @patch('src.backtesting.backtest_engine.HistoricalDataManager')
    def test_put_assignment_handling(self, mock_data_manager):
        """Test put assignment logic."""
        mock_data_manager.return_value = Mock()
        
        engine = BacktestEngine(self.mock_config, self.backtest_config)
        engine.stock_data = self.sample_stock_data
        
        # Create put position that should be assigned (ITM)
        put_position = {
            'underlying': 'AAPL',
            'strike': 160.0,  # Strike above current price
            'expiration': datetime(2023, 1, 15),
            'type': 'PUT',
            'quantity': -1  # Short position
        }
        
        initial_cash = engine.portfolio.cash
        initial_stock_positions = len(engine.portfolio.stock_positions)
        
        # Handle assignment
        engine._handle_put_assignment(put_position, datetime(2023, 1, 15))
        
        # Check results
        assert engine.portfolio.cash < initial_cash  # Cash should decrease
        assert len(engine.portfolio.stock_positions) == initial_stock_positions + 1  # Stock position added
        assert len(engine.trade_history) > 0  # Trade recorded
    
    @patch('src.backtesting.backtest_engine.HistoricalDataManager')
    def test_call_assignment_handling(self, mock_data_manager):
        """Test call assignment logic."""
        mock_data_manager.return_value = Mock()
        
        engine = BacktestEngine(self.mock_config, self.backtest_config)
        engine.stock_data = self.sample_stock_data
        
        # Add stock position first
        stock_position = {
            'symbol': 'AAPL',
            'quantity': 100,
            'entry_price': 150.0,
            'current_price': 155.0,
            'market_value': 15500.0
        }
        engine.portfolio.stock_positions.append(stock_position)
        
        # Create call position that should be assigned (ITM)
        call_position = {
            'underlying': 'AAPL',
            'strike': 150.0,  # Strike below current price
            'expiration': datetime(2023, 1, 15),
            'type': 'CALL',
            'quantity': -1  # Short position
        }
        
        initial_cash = engine.portfolio.cash
        initial_stock_positions = len(engine.portfolio.stock_positions)
        
        # Handle assignment
        engine._handle_call_assignment(call_position, datetime(2023, 1, 15))
        
        # Check results
        assert engine.portfolio.cash > initial_cash  # Cash should increase
        assert len(engine.portfolio.stock_positions) == initial_stock_positions - 1  # Stock position removed
        assert len(engine.trade_history) > 0  # Trade recorded
    
    @patch('src.backtesting.backtest_engine.HistoricalDataManager')
    def test_suitable_put_finding(self, mock_data_manager):
        """Test finding suitable put options."""
        mock_data_manager_instance = Mock()
        mock_data_manager.return_value = mock_data_manager_instance
        mock_data_manager_instance.calculate_option_greeks = Mock(return_value={
            'delta': -0.15,  # Within range
            'gamma': 0.01,
            'theta': -0.05,
            'vega': 0.20
        })
        
        engine = BacktestEngine(self.mock_config, self.backtest_config)
        engine.stock_data = self.sample_stock_data
        
        # Find suitable put
        put_opportunity = engine._find_suitable_put('AAPL', 155.0, datetime(2023, 1, 15))
        
        if put_opportunity:  # Might be None if criteria not met
            assert put_opportunity['type'] == 'PUT'
            assert put_opportunity['underlying'] == 'AAPL'
            assert put_opportunity['strike'] < 155.0  # Should be OTM
            assert put_opportunity['premium'] >= self.mock_config.min_put_premium
    
    @patch('src.backtesting.backtest_engine.HistoricalDataManager')
    def test_suitable_call_finding(self, mock_data_manager):
        """Test finding suitable call options."""
        mock_data_manager_instance = Mock()
        mock_data_manager.return_value = mock_data_manager_instance
        mock_data_manager_instance.calculate_option_greeks = Mock(return_value={
            'delta': 0.15,  # Within range
            'gamma': 0.01,
            'theta': -0.05,
            'vega': 0.20
        })
        
        engine = BacktestEngine(self.mock_config, self.backtest_config)
        engine.stock_data = self.sample_stock_data
        
        # Find suitable call
        call_opportunity = engine._find_suitable_call('AAPL', 155.0, datetime(2023, 1, 15))
        
        if call_opportunity:  # Might be None if criteria not met
            assert call_opportunity['type'] == 'CALL'
            assert call_opportunity['underlying'] == 'AAPL'
            assert call_opportunity['strike'] > 155.0  # Should be OTM
            assert call_opportunity['premium'] >= self.mock_config.min_call_premium
    
    @patch('src.backtesting.backtest_engine.HistoricalDataManager')
    def test_position_closure_logic(self, mock_data_manager):
        """Test position closure logic."""
        mock_data_manager.return_value = Mock()
        
        engine = BacktestEngine(self.mock_config, self.backtest_config)
        
        # Create profitable position (should close)
        profitable_position = {
            'type': 'PUT',
            'quantity': -1,
            'entry_price': 2.00,
            'current_price': 0.80,  # 60% profit
            'underlying': 'AAPL'
        }
        
        should_close = engine._should_close_position(profitable_position, datetime(2023, 1, 15))
        assert should_close == True  # Should close due to profit target
        
        # Create losing call position (should close if stop loss enabled)
        losing_position = {
            'type': 'CALL',
            'quantity': -1,
            'entry_price': 1.00,
            'current_price': 2.00,  # 100% loss
            'underlying': 'AAPL'
        }
        
        should_close_loss = engine._should_close_position(losing_position, datetime(2023, 1, 15))
        assert should_close_loss == True  # Should close due to stop loss
    
    def test_backtest_config_validation(self):
        """Test backtest configuration validation."""
        # Test valid config
        config = BacktestConfig(
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 12, 31),
            initial_capital=100000.0
        )
        assert config.start_date < config.end_date
        assert config.initial_capital > 0
        
        # Test default values
        assert config.commission_per_contract == 1.00
        assert config.slippage_bps == 5
        assert len(config.symbols) > 0


class TestBacktestPortfolio:
    """Test backtesting portfolio functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.portfolio = BacktestPortfolio(100000.0)
    
    def test_portfolio_initialization(self):
        """Test portfolio initialization."""
        assert self.portfolio.initial_cash == 100000.0
        assert self.portfolio.cash == 100000.0
        assert len(self.portfolio.stock_positions) == 0
        assert len(self.portfolio.option_positions) == 0
    
    def test_stock_position_management(self):
        """Test stock position addition and removal."""
        # Add stock position
        stock_pos = {
            'symbol': 'AAPL',
            'quantity': 100,
            'entry_price': 150.0,
            'current_price': 155.0,
            'market_value': 15500.0,
            'cost_basis': 15000.0
        }
        
        self.portfolio.add_stock_position(stock_pos)
        assert len(self.portfolio.stock_positions) == 1
        assert self.portfolio.stock_value == 15500.0
        
        # Remove partial position
        success = self.portfolio.remove_stock_position('AAPL', 50)
        assert success == True
        assert self.portfolio.stock_positions[0]['quantity'] == 50
        
        # Remove remaining position
        success = self.portfolio.remove_stock_position('AAPL', 50)
        assert success == True
        assert len(self.portfolio.stock_positions) == 0
    
    def test_option_position_management(self):
        """Test option position addition and removal."""
        # Add option position
        option_pos = {
            'symbol': 'AAPL_PUT_150_20230120',
            'underlying': 'AAPL',
            'type': 'PUT',
            'strike': 150.0,
            'quantity': -1,
            'entry_price': 2.00,
            'current_price': 1.50,
            'market_value': -150.0
        }
        
        self.portfolio.add_option_position(option_pos)
        assert len(self.portfolio.option_positions) == 1
        assert self.portfolio.option_value == -150.0
        
        # Remove position
        success = self.portfolio.remove_option_position('AAPL_PUT_150_20230120')
        assert success == True
        assert len(self.portfolio.option_positions) == 0
    
    def test_portfolio_value_calculation(self):
        """Test total portfolio value calculation."""
        # Add positions
        stock_pos = {
            'symbol': 'AAPL',
            'quantity': 100,
            'market_value': 15500.0
        }
        option_pos = {
            'symbol': 'AAPL_PUT',
            'market_value': -150.0
        }
        
        self.portfolio.add_stock_position(stock_pos)
        self.portfolio.add_option_position(option_pos)
        
        # Update cash
        self.portfolio.cash = 85000.0
        
        total_value = self.portfolio.total_value
        expected_value = 85000.0 + 15500.0 + (-150.0)  # Cash + Stock + Option
        
        assert total_value == expected_value
    
    def test_portfolio_summary(self):
        """Test portfolio summary generation."""
        summary = self.portfolio.get_portfolio_summary()
        
        assert 'cash' in summary
        assert 'total_value' in summary
        assert 'total_return' in summary
        assert summary['total_return'] == 0.0  # No change initially
    
    def test_risk_metrics(self):
        """Test risk metrics calculation."""
        # Add a large position to test concentration
        large_pos = {
            'symbol': 'AAPL',
            'market_value': 50000.0  # 50% of portfolio
        }
        self.portfolio.add_stock_position(large_pos)
        
        risk_metrics = self.portfolio.get_risk_metrics()
        
        assert 'concentration_risk' in risk_metrics
        assert 'cash_percentage' in risk_metrics
        assert risk_metrics['concentration_risk'] > 0.3  # Should show high concentration