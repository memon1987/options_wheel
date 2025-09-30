"""Tests for WheelStateManager wheel strategy state management."""

import pytest
from datetime import datetime, timedelta
from src.strategy.wheel_state_manager import WheelStateManager, WheelPhase


class TestWheelStateManager:
    """Test suite for wheel state management."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = WheelStateManager()
        self.symbol = "TEST"
        self.test_date = datetime(2024, 1, 15)

    def test_initial_state_allows_puts(self):
        """Test that initial state allows put selling."""
        assert self.manager.get_wheel_phase(self.symbol) == WheelPhase.SELLING_PUTS
        assert self.manager.can_sell_puts(self.symbol) is True
        assert self.manager.can_sell_calls(self.symbol) is False

    def test_put_position_tracking(self):
        """Test adding put positions."""
        # Add put position
        result = self.manager.add_put_position(self.symbol, 1, 2.50, self.test_date)
        assert result is True

        summary = self.manager.get_position_summary(self.symbol)
        assert summary['active_puts'] == 1
        assert summary['total_premium_collected'] == 2.50
        assert summary['can_sell_puts'] is True
        assert summary['can_sell_calls'] is False

    def test_put_assignment_creates_stock_position(self):
        """Test put assignment handling."""
        strike_price = 100.0
        shares = 100

        # Handle put assignment
        result = self.manager.handle_put_assignment(
            self.symbol, shares, strike_price, self.test_date
        )

        assert result['action'] == 'put_assignment'
        assert result['shares_assigned'] == shares
        assert result['total_shares'] == shares
        assert result['avg_cost_basis'] == strike_price
        assert result['phase_before'] == WheelPhase.SELLING_PUTS
        assert result['phase_after'] == WheelPhase.HOLDING_STOCK

        # Check wheel phase changed
        assert self.manager.get_wheel_phase(self.symbol) == WheelPhase.HOLDING_STOCK
        assert self.manager.can_sell_puts(self.symbol) is False
        assert self.manager.can_sell_calls(self.symbol) is True

    def test_covered_call_phase_transition(self):
        """Test covered call selling after assignment."""
        # First, create stock position
        self.manager.handle_put_assignment(self.symbol, 100, 100.0, self.test_date)

        # Add covered call position
        result = self.manager.add_call_position(self.symbol, 1, 3.00, self.test_date)
        assert result is True

        # Check phase
        assert self.manager.get_wheel_phase(self.symbol) == WheelPhase.SELLING_CALLS
        assert self.manager.can_sell_puts(self.symbol) is False
        assert self.manager.can_sell_calls(self.symbol) is True

        summary = self.manager.get_position_summary(self.symbol)
        assert summary['active_calls'] == 1
        assert summary['stock_shares'] == 100

    def test_call_assignment_completes_wheel_cycle(self):
        """Test call assignment completing a wheel cycle."""
        # Setup: put assignment -> stock position
        self.manager.handle_put_assignment(self.symbol, 100, 100.0, self.test_date)
        self.manager.add_call_position(self.symbol, 1, 3.00, self.test_date)

        # Call assignment
        call_date = self.test_date + timedelta(days=30)
        result = self.manager.handle_call_assignment(
            self.symbol, 100, 105.0, call_date
        )

        assert result['action'] == 'call_assignment'
        assert result['shares_called_away'] == 100
        assert result['strike_price'] == 105.0
        assert result['capital_gain'] == 5.0 * 100  # (105 - 100) * 100 shares
        assert result['remaining_shares'] == 0
        assert result['wheel_cycle_completed'] is True
        assert result['phase_after'] == WheelPhase.SELLING_PUTS

        # Check completed cycle data
        assert 'completed_cycle' in result
        cycle = result['completed_cycle']
        assert cycle['symbol'] == self.symbol
        assert cycle['duration_days'] == 30
        assert cycle['capital_gain'] == 500.0
        assert cycle['total_premium'] == 3.0  # From call premium

        # Verify state reset for new cycle
        assert self.manager.get_wheel_phase(self.symbol) == WheelPhase.SELLING_PUTS
        assert self.manager.can_sell_puts(self.symbol) is True
        assert self.manager.can_sell_calls(self.symbol) is False

    def test_partial_call_assignment(self):
        """Test partial call assignment (some shares remain)."""
        # Setup: 200 shares, sell 1 call (100 shares)
        self.manager.handle_put_assignment(self.symbol, 200, 100.0, self.test_date)
        self.manager.add_call_position(self.symbol, 1, 3.00, self.test_date)

        # Partial assignment (100 shares called away)
        result = self.manager.handle_call_assignment(
            self.symbol, 100, 105.0, self.test_date + timedelta(days=30)
        )

        assert result['remaining_shares'] == 100
        assert result['wheel_cycle_completed'] is False
        assert result['phase_after'] == WheelPhase.HOLDING_STOCK

        # Should still be able to sell calls on remaining shares
        assert self.manager.can_sell_calls(self.symbol) is True
        assert self.manager.can_sell_puts(self.symbol) is False

    def test_multiple_put_assignments_average_cost_basis(self):
        """Test multiple put assignments with cost basis averaging."""
        # First assignment
        self.manager.handle_put_assignment(self.symbol, 100, 100.0, self.test_date)

        # Second assignment at different price
        result = self.manager.handle_put_assignment(
            self.symbol, 100, 90.0, self.test_date + timedelta(days=7)
        )

        assert result['total_shares'] == 200
        assert result['avg_cost_basis'] == 95.0  # Average of 100 and 90

        summary = self.manager.get_position_summary(self.symbol)
        assert summary['stock_shares'] == 200
        assert summary['stock_cost_basis'] == 95.0

    def test_position_removal(self):
        """Test position removal (early close, expiration)."""
        # Add positions
        self.manager.add_put_position(self.symbol, 2, 2.50, self.test_date)

        # Remove one contract
        result = self.manager.remove_position(self.symbol, 'put', 1, 'profit_target')
        assert result is True

        summary = self.manager.get_position_summary(self.symbol)
        assert summary['active_puts'] == 1

        # Remove remaining contract
        self.manager.remove_position(self.symbol, 'put', 1, 'expiration')
        summary = self.manager.get_position_summary(self.symbol)
        assert summary['active_puts'] == 0

    def test_symbols_by_phase(self):
        """Test getting symbols by wheel phase."""
        symbols = ['TEST1', 'TEST2', 'TEST3']

        # All start in SELLING_PUTS
        put_phase_symbols = self.manager.get_symbols_by_phase(WheelPhase.SELLING_PUTS)
        assert len(put_phase_symbols) == 0  # No symbols tracked yet

        # Assign one to stock
        self.manager.handle_put_assignment(symbols[0], 100, 100.0, self.test_date)

        # Add put position to another
        self.manager.add_put_position(symbols[1], 1, 2.50, self.test_date)

        put_phase_symbols = self.manager.get_symbols_by_phase(WheelPhase.SELLING_PUTS)
        holding_symbols = self.manager.get_symbols_by_phase(WheelPhase.HOLDING_STOCK)

        assert symbols[0] in holding_symbols
        assert symbols[1] in put_phase_symbols

    def test_wheel_cycle_tracking(self):
        """Test completed wheel cycle tracking."""
        # Complete one full cycle
        self.manager.handle_put_assignment(self.symbol, 100, 100.0, self.test_date)
        self.manager.add_call_position(self.symbol, 1, 3.00, self.test_date + timedelta(days=5))
        self.manager.handle_call_assignment(
            self.symbol, 100, 105.0, self.test_date + timedelta(days=30)
        )

        cycles = self.manager.get_all_wheel_cycles()
        assert len(cycles) == 1

        cycle = cycles[0]
        assert cycle['symbol'] == self.symbol
        assert cycle['duration_days'] == 30
        assert cycle['capital_gain'] == 500.0
        assert cycle['total_return'] == 503.0  # Capital gain + premium

    def test_insufficient_shares_for_calls(self):
        """Test that insufficient shares prevent call selling."""
        # Only 50 shares (need 100 for calls)
        self.manager.handle_put_assignment(self.symbol, 50, 100.0, self.test_date)

        assert self.manager.get_wheel_phase(self.symbol) == WheelPhase.HOLDING_STOCK
        assert self.manager.can_sell_calls(self.symbol) is False
        assert self.manager.can_sell_puts(self.symbol) is False

    def test_cannot_sell_puts_with_stock_position(self):
        """Test that put selling is blocked when holding stock."""
        # Create stock position
        self.manager.handle_put_assignment(self.symbol, 100, 100.0, self.test_date)

        # Try to add put position (should fail)
        result = self.manager.add_put_position(self.symbol, 1, 2.50, self.test_date)
        assert result is False

        # Verify state hasn't changed
        summary = self.manager.get_position_summary(self.symbol)
        assert summary['active_puts'] == 0
        assert summary['stock_shares'] == 100

    def test_error_handling_call_assignment_no_position(self):
        """Test error handling for call assignment without existing position."""
        result = self.manager.handle_call_assignment(
            "NONEXISTENT", 100, 105.0, self.test_date
        )

        assert 'error' in result
        assert result['error'] == 'No existing position'

    def test_error_handling_call_assignment_insufficient_shares(self):
        """Test error handling for call assignment exceeding held shares."""
        # Only 50 shares
        self.manager.handle_put_assignment(self.symbol, 50, 100.0, self.test_date)

        # Try to assign 100 shares
        result = self.manager.handle_call_assignment(
            self.symbol, 100, 105.0, self.test_date
        )

        assert 'error' in result
        assert 'Insufficient shares' in result['error']

    def test_symbol_state_reset(self):
        """Test resetting symbol state."""
        # Create positions
        self.manager.handle_put_assignment(self.symbol, 100, 100.0, self.test_date)
        self.manager.add_call_position(self.symbol, 1, 3.00, self.test_date)

        # Reset
        self.manager.reset_symbol_state(self.symbol)

        # Should be back to initial state
        assert self.manager.get_wheel_phase(self.symbol) == WheelPhase.SELLING_PUTS
        assert self.manager.can_sell_puts(self.symbol) is True
        assert self.manager.can_sell_calls(self.symbol) is False

        summary = self.manager.get_position_summary(self.symbol)
        assert summary['stock_shares'] == 0
        assert summary['active_puts'] == 0
        assert summary['active_calls'] == 0

    def test_position_summary_empty_state(self):
        """Test position summary for unknown symbol."""
        summary = self.manager.get_position_summary("UNKNOWN")

        expected = {
            'symbol': "UNKNOWN",
            'wheel_phase': WheelPhase.SELLING_PUTS.value,
            'stock_shares': 0,
            'active_puts': 0,
            'active_calls': 0,
            'can_sell_puts': True,
            'can_sell_calls': False
        }

        for key, value in expected.items():
            assert summary[key] == value


class TestWheelPhaseTransitions:
    """Test wheel phase transition logic."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = WheelStateManager()
        self.symbol = "WHEEL"
        self.date = datetime(2024, 1, 15)

    def test_complete_wheel_strategy_flow(self):
        """Test complete wheel strategy flow from start to finish."""
        # Phase 1: SELLING_PUTS
        assert self.manager.get_wheel_phase(self.symbol) == WheelPhase.SELLING_PUTS
        assert self.manager.can_sell_puts(self.symbol)
        assert not self.manager.can_sell_calls(self.symbol)

        # Sell puts
        self.manager.add_put_position(self.symbol, 2, 2.50, self.date)

        # Phase 2: PUT_ASSIGNMENT -> HOLDING_STOCK
        assignment_result = self.manager.handle_put_assignment(
            self.symbol, 200, 95.0, self.date + timedelta(days=5)
        )

        assert assignment_result['phase_before'] == WheelPhase.SELLING_PUTS
        assert assignment_result['phase_after'] == WheelPhase.HOLDING_STOCK
        assert self.manager.get_wheel_phase(self.symbol) == WheelPhase.HOLDING_STOCK
        assert not self.manager.can_sell_puts(self.symbol)
        assert self.manager.can_sell_calls(self.symbol)

        # Phase 3: SELLING_CALLS
        self.manager.add_call_position(self.symbol, 2, 3.75, self.date + timedelta(days=7))
        assert self.manager.get_wheel_phase(self.symbol) == WheelPhase.SELLING_CALLS
        assert not self.manager.can_sell_puts(self.symbol)
        assert self.manager.can_sell_calls(self.symbol)

        # Phase 4: CALL_ASSIGNMENT -> back to SELLING_PUTS
        call_result = self.manager.handle_call_assignment(
            self.symbol, 200, 105.0, self.date + timedelta(days=30)
        )

        assert call_result['phase_before'] == WheelPhase.SELLING_CALLS
        assert call_result['phase_after'] == WheelPhase.SELLING_PUTS
        assert call_result['wheel_cycle_completed'] is True
        assert self.manager.get_wheel_phase(self.symbol) == WheelPhase.SELLING_PUTS
        assert self.manager.can_sell_puts(self.symbol)
        assert not self.manager.can_sell_calls(self.symbol)

        # Verify wheel cycle was recorded
        cycles = self.manager.get_all_wheel_cycles()
        assert len(cycles) == 1
        cycle = cycles[0]
        assert cycle['total_return'] == (105.0 - 95.0) * 200 + 2.50 * 2 + 3.75 * 2  # Capital gain + put premium + call premium
        assert cycle['duration_days'] == 25


if __name__ == "__main__":
    pytest.main([__file__, "-v"])