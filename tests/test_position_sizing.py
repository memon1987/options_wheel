"""Tests for position sizing utilities."""

import pytest
from unittest.mock import Mock

from src.risk.position_sizing import PositionSizer
from src.utils.config import Config


class TestPositionSizer:
    """Test position sizing calculations."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.mock_config = Mock(spec=Config)
        self.mock_config.max_position_size = 0.10  # 10% max position size
        self.mock_config.min_cash_reserve = 0.20   # 20% minimum cash
        
        self.position_sizer = PositionSizer(self.mock_config)
        
        self.sample_account = {
            'portfolio_value': 100000.0,
            'cash': 40000.0,  # Increased to allow for cash reserves
            'buying_power': 50000.0
        }
        
        self.sample_put_option = {
            'strike_price': 90.0,  # Reduced to fit within 10% position limit
            'mid_price': 2.50,
            'dte': 7,
            'delta': -0.15,
            'implied_volatility': 0.25
        }
        
        self.sample_call_option = {
            'strike_price': 160.0,
            'mid_price': 1.75,
            'dte': 7,
            'delta': 0.15,
            'implied_volatility': 0.22
        }
        
        self.sample_stock_position = {
            'symbol': 'AAPL',
            'qty': 500,
            'cost_basis': 75000.0  # $150 per share
        }
    
    def test_calculate_put_position_size_basic(self):
        """Test basic put position size calculation."""
        result = self.position_sizer.calculate_put_position_size(
            self.sample_put_option, self.sample_account
        )
        
        assert 'recommended_contracts' in result
        assert 'capital_required' in result
        assert 'premium_income' in result
        assert 'portfolio_allocation' in result
        assert 'max_return_percent' in result
        assert 'annualized_return_estimate' in result
        
        # Should recommend some contracts
        assert result['recommended_contracts'] > 0
        
        # Capital required should be reasonable
        capital_per_contract = self.sample_put_option['strike_price'] * 100
        expected_capital = result['recommended_contracts'] * capital_per_contract
        assert result['capital_required'] == expected_capital
        
        # Portfolio allocation should be within limits
        assert result['portfolio_allocation'] <= self.mock_config.max_position_size
    
    def test_calculate_put_position_size_with_volatility_adjustment(self):
        """Test put position sizing with volatility adjustment."""
        # High volatility should reduce position size
        high_vol_result = self.position_sizer.calculate_put_position_size(
            self.sample_put_option, self.sample_account, stock_volatility=0.50
        )
        
        # Normal volatility
        normal_vol_result = self.position_sizer.calculate_put_position_size(
            self.sample_put_option, self.sample_account, stock_volatility=0.25
        )
        
        # High volatility should result in smaller position
        assert high_vol_result['recommended_contracts'] <= normal_vol_result['recommended_contracts']
    
    def test_calculate_put_position_size_insufficient_funds(self):
        """Test put position sizing when insufficient funds."""
        poor_account = {
            'portfolio_value': 10000.0,
            'cash': 2000.0,
            'buying_power': 5000.0
        }
        
        result = self.position_sizer.calculate_put_position_size(
            self.sample_put_option, poor_account
        )
        
        # Should still return a result but with 0 or very few contracts
        assert 'recommended_contracts' in result
        assert result['recommended_contracts'] >= 0
    
    def test_calculate_call_position_size_basic(self):
        """Test basic covered call position size calculation."""
        result = self.position_sizer.calculate_call_position_size(
            self.sample_call_option, 500, self.sample_stock_position
        )
        
        assert 'recommended_contracts' in result
        assert 'shares_covered' in result
        assert 'premium_income' in result
        assert 'total_return_if_called' in result
        assert 'return_percent_if_called' in result
        assert 'annualized_premium_return' in result
        
        # Should recommend 5 contracts (500 shares / 100)
        assert result['recommended_contracts'] == 5
        assert result['shares_covered'] == 500
        
        # Premium income calculation
        expected_premium = 5 * self.sample_call_option['mid_price'] * 100
        assert result['premium_income'] == expected_premium
    
    def test_calculate_call_position_size_insufficient_shares(self):
        """Test call position sizing with insufficient shares."""
        result = self.position_sizer.calculate_call_position_size(
            self.sample_call_option, 50, self.sample_stock_position  # Only 50 shares
        )
        
        assert result['recommended_contracts'] == 0
        assert 'reason' in result
        assert result['reason'] == 'insufficient_shares'
        assert 'shares_needed' in result
        assert result['shares_needed'] == 50  # Need 50 more to reach 100
    
    def test_calculate_call_position_size_profit_scenarios(self):
        """Test call position sizing profit/loss scenarios."""
        # Strike above cost basis (profit scenario)
        profitable_call = self.sample_call_option.copy()
        profitable_call['strike_price'] = 160.0  # Above $150 cost basis
        
        result = self.position_sizer.calculate_call_position_size(
            profitable_call, 500, self.sample_stock_position
        )
        
        # Should show positive total return if called
        assert result['total_return_if_called'] > result['premium_income']
        assert result['assignment_outcomes']['profit_loss_if_called'] > 0
        
        # Strike below cost basis (loss scenario)
        loss_call = self.sample_call_option.copy()
        loss_call['strike_price'] = 140.0  # Below $150 cost basis
        
        loss_result = self.position_sizer.calculate_call_position_size(
            loss_call, 500, self.sample_stock_position
        )
        
        # Should show capital loss component if called
        assert loss_result['assignment_outcomes']['profit_loss_if_called'] < 0
    
    def test_volatility_adjustment_calculation(self):
        """Test volatility adjustment factor calculation."""
        # Low volatility should increase position size (up to 1.5x)
        low_vol_adj = self.position_sizer._get_volatility_adjustment(0.10)
        assert low_vol_adj > 1.0
        assert low_vol_adj <= 1.5
        
        # High volatility should decrease position size (down to 0.5x)
        high_vol_adj = self.position_sizer._get_volatility_adjustment(0.60)
        assert high_vol_adj < 1.0
        assert high_vol_adj >= 0.5
        
        # Base volatility should give 1.0
        base_vol_adj = self.position_sizer._get_volatility_adjustment(0.25)
        assert base_vol_adj == 1.0
    
    def test_kelly_sizing_calculation(self):
        """Test Kelly criterion position sizing."""
        kelly_contracts = self.position_sizer._calculate_kelly_sizing(
            self.sample_put_option, 100000.0
        )
        
        # Should return a reasonable number of contracts
        assert kelly_contracts >= 1
        assert kelly_contracts <= 10  # Should be conservative
    
    def test_validate_position_size_success(self):
        """Test successful position size validation."""
        position_size_info = {
            'recommended_contracts': 2,
            'capital_required': 8000.0,
            'portfolio_allocation': 0.08  # 8% allocation
        }
        
        is_valid, reason = self.position_sizer.validate_position_size(
            position_size_info, self.sample_account
        )
        
        assert is_valid == True
        assert "validated" in reason.lower()
    
    def test_validate_position_size_exceeds_allocation(self):
        """Test position size validation failure due to allocation."""
        position_size_info = {
            'recommended_contracts': 5,
            'capital_required': 15000.0,
            'portfolio_allocation': 0.15  # 15% allocation, exceeds 10% limit
        }
        
        is_valid, reason = self.position_sizer.validate_position_size(
            position_size_info, self.sample_account
        )
        
        assert is_valid == False
        assert "allocation" in reason.lower()
        assert "exceeds limit" in reason.lower()
    
    def test_validate_position_size_insufficient_buying_power(self):
        """Test position size validation failure due to buying power."""
        position_size_info = {
            'recommended_contracts': 10,
            'capital_required': 60000.0,  # Exceeds buying power
            'portfolio_allocation': 0.10
        }
        
        is_valid, reason = self.position_sizer.validate_position_size(
            position_size_info, self.sample_account
        )
        
        assert is_valid == False
        assert "buying power" in reason.lower()