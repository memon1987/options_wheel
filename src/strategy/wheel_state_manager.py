"""Wheel strategy state management for proper position tracking and phase transitions."""

from typing import Dict, List, Any, Optional, Literal
from datetime import datetime
from enum import Enum
import structlog

logger = structlog.get_logger(__name__)


class WheelPhase(Enum):
    """Phases of the options wheel strategy."""
    SELLING_PUTS = "selling_puts"           # No stock position, selling cash-secured puts
    HOLDING_STOCK = "holding_stock"         # Assigned stock, selling covered calls only
    SELLING_CALLS = "selling_calls"         # Actively selling covered calls on stock position


class WheelStateManager:
    """Manages wheel strategy state and phase transitions for proper position handling."""

    def __init__(self):
        """Initialize wheel state manager."""
        self.symbol_states: Dict[str, Dict[str, Any]] = {}
        self.wheel_cycles: List[Dict[str, Any]] = []

    def get_wheel_phase(self, symbol: str) -> WheelPhase:
        """Get current wheel phase for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Current wheel phase
        """
        if symbol not in self.symbol_states:
            return WheelPhase.SELLING_PUTS

        state = self.symbol_states[symbol]

        # Determine phase based on positions
        has_stock = state.get('stock_shares', 0) > 0
        has_active_calls = state.get('active_calls', 0) > 0

        if has_stock and has_active_calls:
            return WheelPhase.SELLING_CALLS
        elif has_stock:
            return WheelPhase.HOLDING_STOCK
        else:
            return WheelPhase.SELLING_PUTS

    def can_sell_puts(self, symbol: str) -> bool:
        """Check if we can sell puts for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            True if puts can be sold
        """
        phase = self.get_wheel_phase(symbol)

        # Can only sell puts when we don't have stock positions
        can_sell = phase == WheelPhase.SELLING_PUTS

        if not can_sell:
            logger.info("Put selling blocked by wheel state",
                       symbol=symbol,
                       phase=phase.value,
                       reason="holding_stock_position")

        return can_sell

    def can_sell_calls(self, symbol: str) -> bool:
        """Check if we can sell covered calls for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            True if covered calls can be sold
        """
        if symbol not in self.symbol_states:
            return False

        state = self.symbol_states[symbol]
        stock_shares = state.get('stock_shares', 0)

        # Need at least 100 shares for covered calls
        can_sell = stock_shares >= 100

        if not can_sell and stock_shares > 0:
            logger.info("Covered call selling blocked - insufficient shares",
                       symbol=symbol,
                       shares=stock_shares,
                       required=100)

        return can_sell

    def handle_put_assignment(self, symbol: str, shares: int, cost_basis: float,
                            assignment_date: datetime, trade_info: Dict[str, Any] = None) -> Dict[str, Any]:
        """Handle put assignment and update wheel state.

        Args:
            symbol: Stock symbol
            shares: Number of shares assigned
            cost_basis: Cost basis per share
            assignment_date: Date of assignment
            trade_info: Additional trade information

        Returns:
            State update summary
        """
        if symbol not in self.symbol_states:
            self.symbol_states[symbol] = {
                'stock_shares': 0,
                'stock_cost_basis': 0.0,
                'acquisition_date': None,
                'active_puts': 0,
                'active_calls': 0,
                'wheel_cycle_start': None,
                'total_premium_collected': 0.0
            }

        state = self.symbol_states[symbol]

        # Update stock position
        current_shares = state['stock_shares']
        current_total_cost = current_shares * state.get('stock_cost_basis', 0)
        new_total_cost = current_total_cost + (shares * cost_basis)
        new_total_shares = current_shares + shares

        state['stock_shares'] = new_total_shares
        state['stock_cost_basis'] = new_total_cost / new_total_shares if new_total_shares > 0 else 0
        state['acquisition_date'] = assignment_date

        # Start new wheel cycle if this is first assignment
        if current_shares == 0:
            state['wheel_cycle_start'] = assignment_date

        # Reduce active puts (assignment closes put position)
        state['active_puts'] = max(0, state['active_puts'] - (shares // 100))

        old_phase = WheelPhase.SELLING_PUTS
        new_phase = self.get_wheel_phase(symbol)

        logger.info("Put assignment processed",
                   symbol=symbol,
                   shares_assigned=shares,
                   cost_basis=cost_basis,
                   total_shares=new_total_shares,
                   avg_cost_basis=state['stock_cost_basis'],
                   phase_transition=f"{old_phase.value} -> {new_phase.value}")

        return {
            'symbol': symbol,
            'action': 'put_assignment',
            'shares_assigned': shares,
            'total_shares': new_total_shares,
            'avg_cost_basis': state['stock_cost_basis'],
            'phase_before': old_phase,
            'phase_after': new_phase,
            'timestamp': assignment_date
        }

    def handle_call_assignment(self, symbol: str, shares: int, strike_price: float,
                             assignment_date: datetime, trade_info: Dict[str, Any] = None) -> Dict[str, Any]:
        """Handle call assignment and update wheel state.

        Args:
            symbol: Stock symbol
            shares: Number of shares called away
            strike_price: Call strike price
            assignment_date: Date of assignment
            trade_info: Additional trade information

        Returns:
            State update summary with P&L
        """
        if symbol not in self.symbol_states:
            logger.warning("Call assignment on unknown position", symbol=symbol)
            return {'error': 'No existing position'}

        state = self.symbol_states[symbol]
        current_shares = state['stock_shares']

        if current_shares < shares:
            logger.error("Call assignment exceeds held shares",
                        symbol=symbol,
                        shares_to_assign=shares,
                        shares_held=current_shares)
            return {'error': 'Insufficient shares for assignment'}

        # Calculate realized P&L
        cost_basis = state['stock_cost_basis']
        capital_gain = (strike_price - cost_basis) * shares

        old_phase = self.get_wheel_phase(symbol)

        # Update position
        remaining_shares = current_shares - shares
        state['stock_shares'] = remaining_shares
        state['active_calls'] = max(0, state['active_calls'] - (shares // 100))

        # Complete wheel cycle if all shares called away
        wheel_cycle_completed = False
        cycle_data = None

        if remaining_shares == 0:
            wheel_cycle_completed = True
            cycle_start = state.get('wheel_cycle_start')

            if cycle_start:
                cycle_data = {
                    'symbol': symbol,
                    'cycle_start': cycle_start,
                    'cycle_end': assignment_date,
                    'duration_days': (assignment_date - cycle_start).days,
                    'initial_cost_basis': cost_basis,
                    'final_sale_price': strike_price,
                    'capital_gain': capital_gain,
                    'total_premium': state.get('total_premium_collected', 0),
                    'total_return': capital_gain + state.get('total_premium_collected', 0)
                }

                self.wheel_cycles.append(cycle_data)

            # Reset for new cycle
            state['wheel_cycle_start'] = None
            state['total_premium_collected'] = 0.0

        new_phase = self.get_wheel_phase(symbol)

        logger.info("Call assignment processed",
                   symbol=symbol,
                   shares_called_away=shares,
                   strike_price=strike_price,
                   capital_gain=capital_gain,
                   remaining_shares=remaining_shares,
                   wheel_cycle_completed=wheel_cycle_completed,
                   phase_transition=f"{old_phase.value} -> {new_phase.value}")

        result = {
            'symbol': symbol,
            'action': 'call_assignment',
            'shares_called_away': shares,
            'strike_price': strike_price,
            'capital_gain': capital_gain,
            'remaining_shares': remaining_shares,
            'phase_before': old_phase,
            'phase_after': new_phase,
            'wheel_cycle_completed': wheel_cycle_completed,
            'timestamp': assignment_date
        }

        if cycle_data:
            result['completed_cycle'] = cycle_data

        return result

    def add_put_position(self, symbol: str, contracts: int, premium: float,
                        entry_date: datetime) -> bool:
        """Add new put position to tracking.

        Args:
            symbol: Stock symbol
            contracts: Number of contracts
            premium: Premium received per contract
            entry_date: Trade entry date

        Returns:
            True if position added successfully
        """
        if not self.can_sell_puts(symbol):
            return False

        if symbol not in self.symbol_states:
            self.symbol_states[symbol] = {
                'stock_shares': 0,
                'stock_cost_basis': 0.0,
                'acquisition_date': None,
                'active_puts': 0,
                'active_calls': 0,
                'wheel_cycle_start': None,
                'total_premium_collected': 0.0
            }

        state = self.symbol_states[symbol]
        state['active_puts'] += contracts
        state['total_premium_collected'] += premium * contracts

        logger.info("Put position added",
                   symbol=symbol,
                   contracts=contracts,
                   premium_per_contract=premium,
                   total_active_puts=state['active_puts'])

        return True

    def add_call_position(self, symbol: str, contracts: int, premium: float,
                         entry_date: datetime) -> bool:
        """Add new call position to tracking.

        Args:
            symbol: Stock symbol
            contracts: Number of contracts
            premium: Premium received per contract
            entry_date: Trade entry date

        Returns:
            True if position added successfully
        """
        if not self.can_sell_calls(symbol):
            return False

        state = self.symbol_states[symbol]
        state['active_calls'] += contracts
        state['total_premium_collected'] += premium * contracts

        logger.info("Call position added",
                   symbol=symbol,
                   contracts=contracts,
                   premium_per_contract=premium,
                   total_active_calls=state['active_calls'])

        return True

    def remove_position(self, symbol: str, position_type: Literal['put', 'call'],
                       contracts: int, close_reason: str = 'closed') -> bool:
        """Remove position from tracking (early close, expiration).

        Args:
            symbol: Stock symbol
            position_type: 'put' or 'call'
            contracts: Number of contracts to remove
            close_reason: Reason for closing

        Returns:
            True if position removed successfully
        """
        if symbol not in self.symbol_states:
            return False

        state = self.symbol_states[symbol]

        if position_type == 'put':
            state['active_puts'] = max(0, state['active_puts'] - contracts)
        elif position_type == 'call':
            state['active_calls'] = max(0, state['active_calls'] - contracts)

        logger.info("Position removed",
                   symbol=symbol,
                   type=position_type,
                   contracts=contracts,
                   reason=close_reason)

        return True

    def get_position_summary(self, symbol: str) -> Dict[str, Any]:
        """Get comprehensive position summary for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Position summary
        """
        if symbol not in self.symbol_states:
            return {
                'symbol': symbol,
                'wheel_phase': WheelPhase.SELLING_PUTS.value,
                'stock_shares': 0,
                'active_puts': 0,
                'active_calls': 0,
                'can_sell_puts': True,
                'can_sell_calls': False
            }

        state = self.symbol_states[symbol]
        phase = self.get_wheel_phase(symbol)

        return {
            'symbol': symbol,
            'wheel_phase': phase.value,
            'stock_shares': state['stock_shares'],
            'stock_cost_basis': state.get('stock_cost_basis', 0),
            'acquisition_date': state.get('acquisition_date'),
            'active_puts': state['active_puts'],
            'active_calls': state['active_calls'],
            'total_premium_collected': state.get('total_premium_collected', 0),
            'wheel_cycle_start': state.get('wheel_cycle_start'),
            'can_sell_puts': self.can_sell_puts(symbol),
            'can_sell_calls': self.can_sell_calls(symbol)
        }

    def get_all_wheel_cycles(self) -> List[Dict[str, Any]]:
        """Get all completed wheel cycles.

        Returns:
            List of completed wheel cycle data
        """
        return self.wheel_cycles.copy()

    def get_symbols_by_phase(self, phase: WheelPhase) -> List[str]:
        """Get all symbols currently in a specific wheel phase.

        Args:
            phase: Target wheel phase

        Returns:
            List of symbols in the specified phase
        """
        symbols = []
        for symbol in self.symbol_states:
            if self.get_wheel_phase(symbol) == phase:
                symbols.append(symbol)
        return symbols

    def reset_symbol_state(self, symbol: str):
        """Reset all state for a symbol (for testing or manual reset).

        Args:
            symbol: Stock symbol to reset
        """
        if symbol in self.symbol_states:
            del self.symbol_states[symbol]
            logger.info("Symbol state reset", symbol=symbol)