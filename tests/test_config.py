"""Tests for configuration management."""

import pytest
import os
import tempfile
from unittest.mock import patch
import yaml

from src.utils.config import Config


class TestConfig:
    """Test configuration loading and management."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.test_config_data = {
            'alpaca': {
                'paper_trading': True,
                'api_key_id': '${TEST_API_KEY}',
                'secret_key': '${TEST_SECRET_KEY}'
            },
            'strategy': {
                'put_target_dte': 7,
                'call_target_dte': 7,
                'put_delta_range': [0.10, 0.20],
                'call_delta_range': [0.10, 0.20],
                'min_put_premium': 0.50,
                'min_call_premium': 0.30,
                'max_positions_per_stock': 1,
                'max_total_positions': 10
            },
            'risk': {
                'max_portfolio_allocation': 0.80,
                'max_position_size': 0.10,
                'min_cash_reserve': 0.20,
                'use_put_stop_loss': False,
                'use_call_stop_loss': True,
                'put_stop_loss_percent': 0.50,
                'call_stop_loss_percent': 0.50,
                'stop_loss_multiplier': 1.5,
                'profit_target_percent': 0.50
            },
            'stocks': {
                'symbols': ['AAPL', 'MSFT', 'GOOGL']
            }
        }
    
    def test_config_loading(self):
        """Test basic configuration loading."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(self.test_config_data, f)
            config_path = f.name
        
        try:
            with patch.dict(os.environ, {'TEST_API_KEY': 'test_key', 'TEST_SECRET_KEY': 'test_secret'}):
                config = Config(config_path)
                
                assert config.paper_trading == True
                assert config.alpaca_api_key == 'test_key'
                assert config.alpaca_secret_key == 'test_secret'
                assert config.put_target_dte == 7
                assert config.call_target_dte == 7
                assert config.put_delta_range == [0.10, 0.20]
                assert config.call_delta_range == [0.10, 0.20]
                assert config.max_portfolio_allocation == 0.80
                assert config.use_put_stop_loss == False
                assert config.use_call_stop_loss == True
                assert config.stop_loss_multiplier == 1.5
                assert config.profit_target_percent == 0.50
                assert config.stock_symbols == ['AAPL', 'MSFT', 'GOOGL']
        finally:
            os.unlink(config_path)
    
    def test_environment_variable_substitution(self):
        """Test environment variable substitution in config values."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(self.test_config_data, f)
            config_path = f.name
        
        try:
            with patch.dict(os.environ, {'TEST_API_KEY': 'my_api_key', 'TEST_SECRET_KEY': 'my_secret'}):
                config = Config(config_path)
                assert config.alpaca_api_key == 'my_api_key'
                assert config.alpaca_secret_key == 'my_secret'
        finally:
            os.unlink(config_path)
    
    def test_config_get_method(self):
        """Test the get method for accessing nested config values."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(self.test_config_data, f)
            config_path = f.name
        
        try:
            config = Config(config_path)
            
            assert config.get('alpaca.paper_trading') == True
            assert config.get('strategy.put_target_dte') == 7
            assert config.get('nonexistent.key', 'default') == 'default'
            assert config.get('strategy.nonexistent', 42) == 42
        finally:
            os.unlink(config_path)
    
    def test_missing_config_file(self):
        """Test handling of missing configuration file."""
        with pytest.raises(FileNotFoundError):
            Config('nonexistent_config.yaml')
    
    def test_invalid_yaml(self):
        """Test handling of invalid YAML content."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("invalid: yaml: content: [")
            config_path = f.name
        
        try:
            with pytest.raises(yaml.YAMLError):
                Config(config_path)
        finally:
            os.unlink(config_path)