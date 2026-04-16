"""Tests for CallRoller (FC-006)."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, date

from src.strategy.call_roller import CallRoller
from src.strategy.wheel_state_manager import WheelStateManager
from src.risk.risk_manager import RiskManager


@pytest.fixture
def rolling_config():
    """Mock config with rolling settings."""
    config = Mock()
    config.rolling_enabled = True
    config.rolling_max_current_dte = 1
    config.rolling_itm_trigger_ratio = 0.98
    config.rolling_max_rolls_per_position = 2
    config.rolling_earnings_blackout_days = 2
    config.rolling_max_debit_pct_of_premium = 0.25
    config.rolling_max_debit_pct_of_notional = 0.005
    config.rolling_btc_limit_over_ask_pct = 0.05
    config.rolling_stc_limit_under_bid_pct = 0.05
    config.rolling_btc_fill_timeout_seconds = 5  # short for tests
    config.rolling_fallback_strike_attempts = 2
    config.call_delta_range = [0.30, 0.70]
    config.min_call_premium = 0.30
    config.call_target_dte = 7
    return config


@pytest.fixture
def mock_alpaca():
    return Mock()


@pytest.fixture
def mock_market_data():
    return Mock()


@pytest.fixture
def mock_wheel_state():
    state = Mock(spec=WheelStateManager)
    state.get_roll_count.return_value = 0
    state.get_active_call_details.return_value = {
        'option_symbol': 'AMD260417C00100000',
        'premium_per_contract': 2.00,
        'strike': 100.0,
        'contracts': 1,
        'sell_date': '2026-04-10',
    }
    return state


@pytest.fixture
def mock_risk_manager(rolling_config):
    return RiskManager(rolling_config)


@pytest.fixture
def mock_earnings():
    ec = Mock()
    ec.is_earnings_within_n_days.return_value = False
    ec.get_earnings_proximity.return_value = {
        'next_earnings_date': '2026-05-05',
        'days_until': 19,
        'earnings_hour': 'amc',
    }
    return ec


@pytest.fixture
def roller(mock_alpaca, mock_market_data, rolling_config, mock_wheel_state,
           mock_risk_manager, mock_earnings):
    return CallRoller(
        mock_alpaca, mock_market_data, rolling_config,
        mock_wheel_state, mock_risk_manager, mock_earnings)


# === should_roll gate tests ===

class TestShouldRoll:

    def test_eligible_when_all_gates_pass(self, roller):
        call_pos = {'symbol': 'AMD260417C00100000', 'qty': '-1'}
        stock_pos = {'symbol': 'AMD', 'qty': '100', 'cost_basis': '9500'}
        should, reason = roller.should_roll(call_pos, stock_pos, 105.0)
        assert should is True
        assert reason == 'eligible'

    def test_blocked_dte_too_high(self, roller):
        # DTE > 1 should fail
        call_pos = {'symbol': 'AMD260424C00100000', 'qty': '-1'}
        stock_pos = {'symbol': 'AMD', 'qty': '100'}
        should, reason = roller.should_roll(call_pos, stock_pos, 105.0)
        assert should is False
        assert 'dte_too_high' in reason

    def test_blocked_not_itm_enough(self, roller):
        # Stock at 95, strike at 100 => ratio 0.95 < 0.98
        call_pos = {'symbol': 'AMD260417C00100000', 'qty': '-1'}
        stock_pos = {'symbol': 'AMD', 'qty': '100'}
        should, reason = roller.should_roll(call_pos, stock_pos, 95.0)
        assert should is False
        assert 'not_itm_enough' in reason

    def test_blocked_max_rolls_reached(self, roller, mock_wheel_state):
        mock_wheel_state.get_roll_count.return_value = 2
        call_pos = {'symbol': 'AMD260417C00100000', 'qty': '-1'}
        stock_pos = {'symbol': 'AMD', 'qty': '100'}
        should, reason = roller.should_roll(call_pos, stock_pos, 105.0)
        assert should is False
        assert 'max_rolls_reached' in reason

    def test_blocked_earnings_blackout(self, roller, mock_earnings):
        mock_earnings.is_earnings_within_n_days.return_value = True
        call_pos = {'symbol': 'AMD260417C00100000', 'qty': '-1'}
        stock_pos = {'symbol': 'AMD', 'qty': '100'}
        should, reason = roller.should_roll(call_pos, stock_pos, 105.0)
        assert should is False
        assert reason == 'earnings_blackout'


# === Debit tolerance tests ===

class TestDebitTolerance:

    def test_credit_roll_always_passes(self, roller):
        assert roller._check_debit_tolerance(0, 2.00, 10000) is True

    def test_debit_within_premium_pct(self, roller):
        # 0.40 debit, 2.00 premium, 25% threshold => max 0.50 => passes
        assert roller._check_debit_tolerance(0.40, 2.00, 10000) is True

    def test_debit_exceeds_premium_pct(self, roller):
        # 0.60 debit, 2.00 premium, 25% threshold => max 0.50 => fails
        assert roller._check_debit_tolerance(0.60, 2.00, 10000) is False

    def test_debit_exceeds_notional_backstop(self, roller):
        # Very small notional: 0.40 debit, notional 100 * 0.005 = 0.50 => passes
        # But notional 50 * 0.005 = 0.25 => fails
        assert roller._check_debit_tolerance(0.40, 10.00, 50) is False

    def test_debit_zero_original_premium(self, roller):
        # If original premium is 0, any debit fails (999% > 25%)
        assert roller._check_debit_tolerance(0.10, 0, 10000) is False


# === Economics computation ===

class TestRollEconomics:

    def test_credit_roll(self, roller):
        result = roller._compute_net_roll_economics(2.00, 3.00, 4.00, 1)
        assert result['net_credit'] == 1.00
        assert result['net_debit'] == 0

    def test_debit_roll(self, roller):
        result = roller._compute_net_roll_economics(2.00, 5.00, 3.00, 1)
        assert result['net_debit'] == 2.00
        assert result['net_credit'] == 0
        assert result['debit_pct_of_premium'] == 100.0

    def test_even_roll(self, roller):
        result = roller._compute_net_roll_economics(2.00, 3.00, 3.00, 1)
        assert result['net_debit'] == 0
        assert result['net_credit'] == 0


# === validate_roll (RiskManager) tests ===

class TestValidateRoll:

    def test_valid_roll_up(self, mock_risk_manager):
        new_call = {'strike_price': 110, 'delta': 0.40, 'mid_price': 1.50, 'dte': 7}
        valid, reason = mock_risk_manager.validate_roll(new_call, 100.0, 95.0)
        assert valid is True

    def test_rejects_roll_down(self, mock_risk_manager):
        new_call = {'strike_price': 95, 'delta': 0.40, 'mid_price': 1.50, 'dte': 7}
        valid, reason = mock_risk_manager.validate_roll(new_call, 100.0, 90.0)
        assert valid is False
        assert 'not above current' in reason

    def test_rejects_below_cost_basis(self, mock_risk_manager):
        new_call = {'strike_price': 105, 'delta': 0.40, 'mid_price': 1.50, 'dte': 7}
        valid, reason = mock_risk_manager.validate_roll(new_call, 100.0, 110.0)
        assert valid is False
        assert 'cost basis' in reason

    def test_rejects_delta_out_of_range(self, mock_risk_manager):
        new_call = {'strike_price': 110, 'delta': 0.05, 'mid_price': 1.50, 'dte': 7}
        valid, reason = mock_risk_manager.validate_roll(new_call, 100.0, 95.0)
        assert valid is False
        assert 'Delta' in reason

    def test_rejects_low_premium(self, mock_risk_manager):
        new_call = {'strike_price': 110, 'delta': 0.40, 'mid_price': 0.10, 'dte': 7}
        valid, reason = mock_risk_manager.validate_roll(new_call, 100.0, 95.0)
        assert valid is False
        assert 'Premium' in reason


# === WheelStateManager roll tracking tests ===

class TestWheelStateRollTracking:

    def test_set_and_get_active_call_details(self):
        wsm = WheelStateManager()
        wsm.handle_put_assignment('AMD', 100, 95.0, datetime.now())
        wsm.set_active_call_details('AMD', 'AMD260417C00100000', 2.00, 100.0, 1, '2026-04-10')
        details = wsm.get_active_call_details('AMD')
        assert details is not None
        assert details['premium_per_contract'] == 2.00
        assert details['strike'] == 100.0

    def test_record_call_roll(self):
        wsm = WheelStateManager()
        wsm.handle_put_assignment('AMD', 100, 95.0, datetime.now())
        wsm.record_call_roll('AMD', 'OLD', 'NEW', 1, -0.50, 300.0, 250.0, 100.0, 105.0, '2026-04-18')
        assert wsm.get_roll_count('AMD') == 1
        state = wsm.symbol_states['AMD']
        assert len(state.get('roll_history', [])) == 1
        assert state['cumulative_roll_premium'] == -0.50

    def test_roll_count_increments(self):
        wsm = WheelStateManager()
        wsm.handle_put_assignment('AMD', 100, 95.0, datetime.now())
        wsm.record_call_roll('AMD', 'OLD1', 'NEW1', 1, 0.10, 200, 210, 100, 105, '2026-04-18')
        wsm.record_call_roll('AMD', 'OLD2', 'NEW2', 1, -0.20, 300, 280, 105, 110, '2026-04-25')
        assert wsm.get_roll_count('AMD') == 2

    def test_get_roll_count_no_state(self):
        wsm = WheelStateManager()
        assert wsm.get_roll_count('NONEXISTENT') == 0

    def test_get_active_call_details_no_state(self):
        wsm = WheelStateManager()
        assert wsm.get_active_call_details('NONEXISTENT') is None
