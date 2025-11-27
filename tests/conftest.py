"""Shared test fixtures for options wheel strategy tests."""

import pytest
import os
import tempfile
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone
from typing import Dict, Any, List
import yaml

from src.utils.config import Config


# ==================== Configuration Fixtures ====================

@pytest.fixture
def test_config_data() -> Dict[str, Any]:
    """Return a complete, valid test configuration dictionary."""
    return {
        'alpaca': {
            'paper_trading': True,
            'api_key_id': 'test_api_key',
            'secret_key': 'test_secret_key'
        },
        'strategy': {
            'put_target_dte': 7,
            'call_target_dte': 7,
            'put_delta_range': [0.10, 0.20],
            'call_delta_range': [0.10, 0.20],
            'min_put_premium': 0.50,
            'min_call_premium': 0.30,
            'min_stock_price': 20.0,
            'max_stock_price': 500.0,
            'min_avg_volume': 1000000,
            'max_positions_per_stock': 1,
            'max_total_positions': 10,
            'max_exposure_per_ticker': 50000.0,
            'opportunity_max_age_minutes': 30
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
            'profit_target_percent': 0.50,
            'profit_taking': {
                'use_dynamic_profit_target': True,
                'static_profit_target': 0.50,
                'min_profit_target': 0.30,
                'max_profit_target': 0.80,
                'default_long_dte_target': 0.50,
                'dte_bands': []
            },
            'gap_risk_controls': {
                'enable_gap_detection': True,
                'max_overnight_gap_percent': 0.05,
                'gap_lookback_days': 30,
                'max_gap_frequency': 0.10,
                'earnings_avoidance_days': 5,
                'premarket_gap_threshold': 0.03,
                'market_open_delay_minutes': 15,
                'max_historical_vol': 0.50,
                'vol_lookback_days': 20,
                'quality_gap_threshold': 0.05,
                'execution_gap_threshold': 0.03,
                'execution_gap_lookback_hours': 24
            }
        },
        'stocks': {
            'symbols': ['AAPL', 'MSFT', 'GOOGL']
        },
        'monitoring': {
            'check_interval_minutes': 5
        }
    }


@pytest.fixture
def config_file(test_config_data, tmp_path):
    """Create a temporary config file with valid test data."""
    config_path = tmp_path / "test_settings.yaml"
    with open(config_path, 'w') as f:
        yaml.dump(test_config_data, f)
    return str(config_path)


@pytest.fixture
def mock_config():
    """Create a mock Config object with common settings."""
    config = Mock(spec=Config)

    # Alpaca settings
    config.paper_trading = True
    config.alpaca_api_key = 'test_api_key'
    config.alpaca_secret_key = 'test_secret_key'

    # Strategy settings
    config.put_target_dte = 7
    config.call_target_dte = 7
    config.put_delta_range = [0.10, 0.20]
    config.call_delta_range = [0.10, 0.20]
    config.min_put_premium = 0.50
    config.min_call_premium = 0.30
    config.min_stock_price = 20.0
    config.max_stock_price = 500.0
    config.min_avg_volume = 1000000
    config.max_positions_per_stock = 1
    config.max_total_positions = 10
    config.max_exposure_per_ticker = 50000.0
    config.stock_symbols = ['AAPL', 'MSFT', 'GOOGL']
    config.opportunity_max_age_minutes = 30

    # Risk settings
    config.max_portfolio_allocation = 0.80
    config.max_position_size = 0.10
    config.min_cash_reserve = 0.20
    config.use_put_stop_loss = False
    config.use_call_stop_loss = True
    config.put_stop_loss_percent = 0.50
    config.call_stop_loss_percent = 0.50
    config.stop_loss_multiplier = 1.5
    config.profit_target_percent = 0.50

    # Profit taking settings
    config.use_dynamic_profit_target = True
    config.profit_taking_static_target = 0.50
    config.profit_taking_min_target = 0.30
    config.profit_taking_max_target = 0.80
    config.profit_taking_default_long_dte = 0.50
    config.profit_taking_dte_bands = []

    # Gap risk settings
    config.enable_gap_detection = True
    config.max_overnight_gap_percent = 0.05
    config.gap_lookback_days = 30
    config.max_gap_frequency = 0.10
    config.earnings_avoidance_days = 5
    config.premarket_gap_threshold = 0.03
    config.market_open_delay_minutes = 15
    config.max_historical_vol = 0.50
    config.vol_lookback_days = 20
    config.quality_gap_threshold = 0.05
    config.execution_gap_threshold = 0.03
    config.execution_gap_lookback_hours = 24

    # Monitoring settings
    config.check_interval_minutes = 5

    return config


# ==================== Account Fixtures ====================

@pytest.fixture
def sample_account_info() -> Dict[str, Any]:
    """Return a sample Alpaca account info dictionary."""
    return {
        'id': 'test_account_id',
        'account_number': '123456789',
        'status': 'ACTIVE',
        'currency': 'USD',
        'portfolio_value': 100000.0,
        'cash': 25000.0,
        'buying_power': 50000.0,
        'equity': 100000.0,
        'last_equity': 99500.0,
        'long_market_value': 75000.0,
        'short_market_value': 0.0,
        'initial_margin': 37500.0,
        'maintenance_margin': 25000.0,
        'daytrading_buying_power': 100000.0,
        'non_marginable_buying_power': 25000.0,
        'accrued_fees': 0.0,
        'pending_transfer_in': 0.0,
        'pending_transfer_out': 0.0,
        'pattern_day_trader': False,
        'trading_blocked': False,
        'transfers_blocked': False,
        'account_blocked': False,
        'created_at': '2024-01-01T00:00:00Z',
        'trade_suspended_by_user': False,
        'multiplier': '4',
        'shorting_enabled': True,
        'options_trading_level': 2,
        'options_approved_level': 2
    }


# ==================== Position Fixtures ====================

@pytest.fixture
def sample_stock_position() -> Dict[str, Any]:
    """Return a sample stock position."""
    return {
        'asset_id': 'test_asset_id',
        'symbol': 'AAPL',
        'exchange': 'NASDAQ',
        'asset_class': 'us_equity',
        'asset_marginable': True,
        'qty': 100,
        'qty_available': 100,
        'side': 'long',
        'market_value': 17500.0,
        'cost_basis': 16000.0,
        'unrealized_pl': 1500.0,
        'unrealized_plpc': 0.09375,
        'unrealized_intraday_pl': 250.0,
        'unrealized_intraday_plpc': 0.0145,
        'current_price': 175.0,
        'lastday_price': 172.5,
        'change_today': 0.0145,
        'avg_entry_price': 160.0
    }


@pytest.fixture
def sample_option_position() -> Dict[str, Any]:
    """Return a sample option position (short put)."""
    return {
        'asset_id': 'test_option_id',
        'symbol': 'AAPL250117P00170000',
        'exchange': 'OPRA',
        'asset_class': 'us_option',
        'asset_marginable': True,
        'qty': -1,
        'qty_available': -1,
        'side': 'short',
        'market_value': -150.0,
        'cost_basis': 200.0,
        'unrealized_pl': 50.0,
        'unrealized_plpc': 0.25,
        'unrealized_intraday_pl': 10.0,
        'unrealized_intraday_plpc': 0.071,
        'current_price': 1.50,
        'lastday_price': 1.60,
        'change_today': -0.0625,
        'avg_entry_price': 2.00
    }


@pytest.fixture
def sample_positions(sample_stock_position, sample_option_position) -> List[Dict[str, Any]]:
    """Return a list of sample positions."""
    return [sample_stock_position, sample_option_position]


# ==================== Opportunity Fixtures ====================

@pytest.fixture
def sample_put_opportunity() -> Dict[str, Any]:
    """Return a sample put selling opportunity."""
    return {
        'strategy': 'sell_put',
        'symbol': 'MSFT',
        'option_symbol': 'MSFT250117P00380000',
        'strike_price': 380.0,
        'strike': 380.0,
        'current_stock_price': 400.0,
        'expiration': '2025-01-17',
        'dte': 7,
        'delta': -0.15,
        'premium': 2.50,
        'bid': 2.45,
        'ask': 2.55,
        'volume': 1500,
        'open_interest': 5000,
        'implied_volatility': 0.25,
        'capital_required': 38000.0,
        'contracts': 1,
        'annual_return': 0.24,
        'created_at': datetime.now(timezone.utc).isoformat()
    }


@pytest.fixture
def sample_call_opportunity() -> Dict[str, Any]:
    """Return a sample call selling opportunity."""
    return {
        'strategy': 'sell_call',
        'symbol': 'AAPL',
        'option_symbol': 'AAPL250117C00185000',
        'strike_price': 185.0,
        'strike': 185.0,
        'current_stock_price': 175.0,
        'expiration': '2025-01-17',
        'dte': 7,
        'delta': 0.15,
        'premium': 1.80,
        'bid': 1.75,
        'ask': 1.85,
        'volume': 2000,
        'open_interest': 8000,
        'implied_volatility': 0.22,
        'capital_required': 0.0,
        'contracts': 1,
        'annual_return': 0.54,
        'created_at': datetime.now(timezone.utc).isoformat()
    }


# ==================== Order Fixtures ====================

@pytest.fixture
def sample_order_response() -> Dict[str, Any]:
    """Return a sample order response."""
    return {
        'id': 'test_order_id_123',
        'client_order_id': 'client_order_123',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'submitted_at': datetime.now(timezone.utc).isoformat(),
        'filled_at': None,
        'expired_at': None,
        'canceled_at': None,
        'failed_at': None,
        'replaced_at': None,
        'replaced_by': None,
        'replaces': None,
        'asset_id': 'test_asset_id',
        'symbol': 'MSFT250117P00380000',
        'asset_class': 'us_option',
        'notional': None,
        'qty': 1,
        'filled_qty': 0,
        'filled_avg_price': None,
        'order_class': 'simple',
        'order_type': 'limit',
        'type': 'limit',
        'side': 'sell',
        'time_in_force': 'day',
        'limit_price': 2.50,
        'stop_price': None,
        'status': 'new',
        'extended_hours': False,
        'legs': None,
        'trail_percent': None,
        'trail_price': None,
        'hwm': None
    }


# ==================== Option Chain Fixtures ====================

@pytest.fixture
def sample_option_contract() -> Dict[str, Any]:
    """Return a sample option contract from chain."""
    return {
        'symbol': 'MSFT250117P00380000',
        'underlying_symbol': 'MSFT',
        'expiration': '2025-01-17',
        'strike': 380.0,
        'option_type': 'PUT',
        'bid': 2.45,
        'ask': 2.55,
        'last': 2.50,
        'volume': 1500,
        'open_interest': 5000,
        'delta': -0.15,
        'gamma': 0.02,
        'theta': -0.05,
        'vega': 0.10,
        'implied_volatility': 0.25
    }


@pytest.fixture
def sample_option_chain(sample_option_contract) -> Dict[str, List[Dict[str, Any]]]:
    """Return a sample option chain with puts and calls."""
    puts = []
    calls = []

    # Generate puts at different strikes
    for strike in [370, 375, 380, 385, 390]:
        put = sample_option_contract.copy()
        put['strike'] = float(strike)
        put['symbol'] = f"MSFT250117P00{strike}000"
        put['delta'] = -0.10 - (390 - strike) * 0.02
        puts.append(put)

    # Generate calls at different strikes
    for strike in [400, 405, 410, 415, 420]:
        call = sample_option_contract.copy()
        call['strike'] = float(strike)
        call['option_type'] = 'CALL'
        call['symbol'] = f"MSFT250117C00{strike}000"
        call['delta'] = 0.10 + (strike - 400) * 0.02
        calls.append(call)

    return {'puts': puts, 'calls': calls}


# ==================== Mock Client Fixtures ====================

@pytest.fixture
def mock_trading_client():
    """Create a mock Alpaca trading client."""
    client = MagicMock()

    # Mock account info
    mock_account = MagicMock()
    mock_account.id = 'test_account_id'
    mock_account.status = 'ACTIVE'
    mock_account.portfolio_value = '100000.0'
    mock_account.cash = '25000.0'
    mock_account.buying_power = '50000.0'
    mock_account.equity = '100000.0'
    mock_account.options_trading_level = 2
    mock_account.options_approved_level = 2
    client.get_account.return_value = mock_account

    # Mock empty positions by default
    client.get_all_positions.return_value = []

    return client


@pytest.fixture
def mock_data_client():
    """Create a mock Alpaca data client."""
    client = MagicMock()

    # Mock stock quote
    mock_quote = MagicMock()
    mock_quote.bid_price = 174.50
    mock_quote.ask_price = 175.50
    mock_quote.bid_size = 100
    mock_quote.ask_size = 100
    client.get_stock_latest_quote.return_value = {'AAPL': mock_quote}

    return client


@pytest.fixture
def mock_option_client():
    """Create a mock Alpaca option client."""
    client = MagicMock()
    return client


# ==================== Environment Fixtures ====================

@pytest.fixture
def mock_env_vars():
    """Patch environment variables for testing."""
    env_vars = {
        'ALPACA_API_KEY_ID': 'test_api_key',
        'ALPACA_SECRET_KEY': 'test_secret_key',
        'GCS_BUCKET_NAME': 'test-bucket',
        'GOOGLE_CLOUD_PROJECT': 'test-project'
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


# ==================== Time Fixtures ====================

@pytest.fixture
def market_hours_time():
    """Return a datetime during market hours (10:00 AM ET)."""
    return datetime(2025, 1, 15, 15, 0, 0, tzinfo=timezone.utc)  # 10 AM ET = 3 PM UTC


@pytest.fixture
def after_hours_time():
    """Return a datetime after market hours (5:00 PM ET)."""
    return datetime(2025, 1, 15, 22, 0, 0, tzinfo=timezone.utc)  # 5 PM ET = 10 PM UTC


@pytest.fixture
def weekend_time():
    """Return a datetime on a weekend (Saturday)."""
    return datetime(2025, 1, 18, 15, 0, 0, tzinfo=timezone.utc)  # Saturday
