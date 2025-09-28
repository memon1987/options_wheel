"""Tests for risk management system."""

import pytest
from unittest.mock import Mock

from src.risk.risk_manager import RiskManager
from src.utils.config import Config


class TestRiskManager:
    """Test risk management functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.mock_config = Mock(spec=Config)
        self.mock_config.max_position_size = 0.10
        self.mock_config.max_total_positions = 10
        self.mock_config.max_positions_per_stock = 2
        self.mock_config.min_cash_reserve = 0.20
        self.mock_config.put_delta_range = [0.10, 0.20]
        self.mock_config.call_delta_range = [0.10, 0.20]
        self.mock_config.min_put_premium = 0.50
        self.mock_config.min_call_premium = 0.30
        self.mock_config.put_target_dte = 7
        self.mock_config.call_target_dte = 7
        self.mock_config.max_exposure_per_ticker = 50000
        
        self.risk_manager = RiskManager(self.mock_config)
        
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
    
    def test_validate_new_position_success(self):
        """Test successful position validation."""
        opportunity = {
            'strategy': 'sell_put',
            'symbol': 'MSFT',
            'capital_required': 5000.0,  # Reduced to pass cash reserve test
            'delta': 0.15,
            'premium': 1.50,
            'dte': 7,
            'current_stock_price': 300.0,
            'strike_price': 280.0
        }
        
        is_valid, reason = self.risk_manager.validate_new_position(
            opportunity, self.sample_account, self.sample_positions
        )
        
        assert is_valid == True
        assert "approved" in reason.lower()
    
    def test_validate_position_exceeds_allocation(self):
        """Test rejection when position exceeds allocation limit."""
        opportunity = {
            'strategy': 'sell_put',
            'symbol': 'MSFT',
            'capital_required': 15000.0,  # 15% of portfolio, exceeds 10% limit
            'delta': 0.20,
            'premium': 1.50,
            'dte': 35,
            'current_stock_price': 300.0,
            'strike_price': 280.0
        }
        
        is_valid, reason = self.risk_manager.validate_new_position(
            opportunity, self.sample_account, self.sample_positions
        )
        
        assert is_valid == False
        assert "allocation" in reason.lower()
        assert "exceeds limit" in reason.lower()
    
    def test_validate_position_max_positions_reached(self):
        """Test rejection when maximum positions reached."""
        # Create positions at the limit
        many_positions = []
        for i in range(10):
            many_positions.append({
                'symbol': f'TEST_{i}_PUT',
                'qty': -1,
                'asset_class': 'us_option',
                'market_value': -100.0,
                'unrealized_pl': 0.0
            })
        
        opportunity = {
            'strategy': 'sell_put',
            'symbol': 'MSFT',
            'capital_required': 5000.0,
            'delta': 0.20,
            'premium': 1.50,
            'dte': 35
        }
        
        is_valid, reason = self.risk_manager.validate_new_position(
            opportunity, self.sample_account, many_positions
        )
        
        assert is_valid == False
        assert "maximum positions reached" in reason.lower()
    
    def test_validate_option_delta_out_of_range(self):
        """Test rejection when option delta is out of range."""
        opportunity = {
            'strategy': 'sell_put',
            'symbol': 'MSFT',
            'capital_required': 5000.0,
            'delta': 0.50,  # Too high delta
            'premium': 1.50,
            'dte': 35,
            'current_stock_price': 300.0,
            'strike_price': 280.0
        }
        
        is_valid, reason = self.risk_manager.validate_new_position(
            opportunity, self.sample_account, self.sample_positions
        )
        
        assert is_valid == False
        assert "delta" in reason.lower()
        assert "outside range" in reason.lower()
    
    def test_validate_premium_too_low(self):
        """Test rejection when premium is too low."""
        opportunity = {
            'strategy': 'sell_put',
            'symbol': 'MSFT',
            'capital_required': 5000.0,
            'delta': 0.20,
            'premium': 0.25,  # Below minimum
            'dte': 35,
            'current_stock_price': 300.0,
            'strike_price': 280.0
        }
        
        is_valid, reason = self.risk_manager.validate_new_position(
            opportunity, self.sample_account, self.sample_positions
        )
        
        assert is_valid == False
        assert "premium" in reason.lower()
        assert "below minimum" in reason.lower()
    
    def test_calculate_portfolio_risk_metrics(self):
        """Test portfolio risk metrics calculation."""
        risk_metrics = self.risk_manager.calculate_portfolio_risk_metrics(
            self.sample_account, self.sample_positions
        )
        
        assert 'portfolio_value' in risk_metrics
        assert 'cash_allocation' in risk_metrics
        assert 'stock_allocation' in risk_metrics
        assert 'total_positions' in risk_metrics
        assert 'max_exposure_symbol' in risk_metrics
        assert 'unrealized_pl' in risk_metrics
        assert 'risk_warnings' in risk_metrics
        
        assert risk_metrics['portfolio_value'] == 100000.0
        assert risk_metrics['total_positions'] == 2
        assert risk_metrics['cash_allocation'] == 0.25  # 25% cash
        
    def test_should_reduce_positions_low_cash(self):
        """Test position reduction recommendation due to low cash."""
        low_cash_account = self.sample_account.copy()
        low_cash_account['cash'] = 10000.0  # 10% cash, below 20% minimum
        
        risk_metrics = self.risk_manager.calculate_portfolio_risk_metrics(
            low_cash_account, self.sample_positions
        )
        
        should_reduce, reasons = self.risk_manager.should_reduce_positions(risk_metrics)
        
        assert should_reduce == True
        assert any("cash" in reason.lower() for reason in reasons)
    
    def test_should_reduce_positions_large_losses(self):
        """Test position reduction recommendation due to large losses."""
        losing_positions = [
            {
                'symbol': 'AAPL',
                'qty': 100,
                'asset_class': 'us_equity',
                'market_value': 15000.0,
                'unrealized_pl': -12000.0  # Large loss
            }
        ]
        
        risk_metrics = self.risk_manager.calculate_portfolio_risk_metrics(
            self.sample_account, losing_positions
        )
        
        should_reduce, reasons = self.risk_manager.should_reduce_positions(risk_metrics)
        
        assert should_reduce == True
        assert any("loss" in reason.lower() for reason in reasons)
    
    def test_check_emergency_conditions(self):
        """Test emergency stop condition checking."""
        # Create severe loss scenario
        severe_loss_positions = [
            {
                'symbol': 'AAPL',
                'qty': 100,
                'asset_class': 'us_equity',
                'market_value': 15000.0,
                'unrealized_pl': -20000.0  # 20% portfolio loss
            }
        ]
        
        risk_metrics = self.risk_manager.calculate_portfolio_risk_metrics(
            self.sample_account, severe_loss_positions
        )
        
        emergency_stop, reasons = self.risk_manager.check_emergency_conditions(
            self.sample_account, risk_metrics
        )
        
        assert emergency_stop == True
        assert any("portfolio loss" in reason.lower() for reason in reasons)
    
    def test_covered_call_validation(self):
        """Test covered call specific validation."""
        call_opportunity = {
            'strategy': 'sell_call',
            'symbol': 'GOOGL',  # Use different symbol to avoid position count limit
            'capital_required': 0,  # Covered calls don't require additional capital
            'delta': 0.15,
            'premium': 1.00,
            'dte': 7,
            'current_stock_price': 150.0,
            'strike_price': 155.0
        }
        
        is_valid, reason = self.risk_manager.validate_new_position(
            call_opportunity, self.sample_account, self.sample_positions
        )
        
        assert is_valid == True
        assert "approved" in reason.lower()