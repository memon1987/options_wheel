"""In-request position bookkeeping for ``WheelEngine.reconcile_positions``.

**What this is, post-FC-069 item 8 (stage 2).** A plain, per-request dictionary
of what reconciliation believes each symbol holds, plus the assignment handlers
that emit the wheel's assignment/cycle telemetry. It is built empty on every
request, diffed against Alpaca, and thrown away. Alpaca is the source of truth;
this object is the scratch pad reconciliation diffs against.

**What it is not.** It is not durable state, and nothing that trades reads it.
FC-039 proved four ways that the GCS persistence this module used to carry had
never worked (``STATE_STORAGE_BUCKET`` unset since inception; no state object in
any bucket in the project), so a year of "canonical wheel state" was in fact a
per-instance scratch pad that three separate investigations mistook for durable
truth. Stage 1 (S5) removed the orphaned ``CallSeller`` plumbing; stage 2 (this
file) removed the rest: the GCS save/load, the phase *gates*
(``can_sell_puts``/``can_sell_calls``), the premium accumulators, the roll
counters and roll history, the roller's six state methods (consumer-less since
FC-078 made the roller stateless-from-Alpaca), the in-memory ``wheel_cycles``
list, and the position-tracking setters no live caller ever reached.

**Standing rule inherited from FC-069 item 8(b)** — for whoever next wants
durable state here: a configured-but-unresolvable persistence target must
**fail loudly at startup**, never silently no-op. The silent
``storage_bucket=None`` no-op is exactly how this layer stayed fictional for a
year while the docs called it canonical.

``WheelPhase`` survives as a *derived label*, not a gate: it is a pure function
of ``stock_shares`` and ``active_calls``, and it is what the assignment events
report as ``phase_before``/``phase_after``. Nothing consults it for permission.
"""

from typing import Dict, Any
from datetime import datetime
from enum import Enum
import structlog

from ..utils.logging_events import log_position_update

logger = structlog.get_logger(__name__)


class WheelPhase(Enum):
    """Phases of the options wheel strategy."""
    SELLING_PUTS = "selling_puts"           # No stock position, selling cash-secured puts
    HOLDING_STOCK = "holding_stock"         # Assigned stock, selling covered calls only
    SELLING_CALLS = "selling_calls"         # Actively selling covered calls on stock position


class WheelStateManager:
    """Per-request position bookkeeping for reconciliation.

    Takes no arguments: there is no persistence target and no configuration.
    See the module docstring for why.
    """

    def __init__(self):
        """Initialize an empty, in-memory-only bookkeeping map."""
        self.symbol_states: Dict[str, Dict[str, Any]] = {}

    def get_wheel_phase(self, symbol: str) -> WheelPhase:
        """Derive the wheel phase for a symbol from its tracked position.

        Pure function of ``stock_shares``/``active_calls`` — a label for the
        assignment telemetry, never a permission check.

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
                   event_category="trade",
                   symbol=symbol,
                   shares_assigned=shares,
                   cost_basis=cost_basis,
                   total_shares=new_total_shares,
                   avg_cost_basis=state['stock_cost_basis'],
                   phase_transition=f"{old_phase.value} -> {new_phase.value}")

        # Enhanced position update logging with phase transition
        log_position_update(
            logger,
            event_type="put_assignment",
            symbol=symbol,
            position_status="assigned",
            position_type="put",
            action="assignment",
            shares=shares,
            assignment_price=cost_basis,
            total_shares=new_total_shares,
            avg_cost_basis=state['stock_cost_basis'],
            phase_before=old_phase.value,
            phase_after=new_phase.value,
            wheel_cycle_started=(current_shares == 0)
        )

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
            State update summary with realized capital gain
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
                }

                # Log wheel cycle completion. This event has a live consumer:
                # the ``options_wheel_logs.wheel_cycles`` BigQuery view matches
                # on ``event_type = 'wheel_cycle_complete'``. FC-069 item 8
                # stage 2 dropped the premium fields it used to carry — they
                # were fed only by ``add_put_position``/``add_call_position``,
                # which no production path ever called, so every one of them
                # was structurally 0.0. The view selects none of them.
                log_position_update(
                    logger,
                    event_type="wheel_cycle_complete",
                    symbol=symbol,
                    position_status="cycle_complete",
                    capital_gain=capital_gain,
                    cycle_duration_days=(assignment_date - cycle_start).days,
                    cost_basis=cost_basis,
                    exit_price=strike_price,
                )

            # Reset for new cycle
            state['wheel_cycle_start'] = None

        new_phase = self.get_wheel_phase(symbol)

        logger.info("Call assignment processed",
                   event_category="trade",
                   symbol=symbol,
                   shares_called_away=shares,
                   strike_price=strike_price,
                   capital_gain=capital_gain,
                   remaining_shares=remaining_shares,
                   wheel_cycle_completed=wheel_cycle_completed,
                   phase_transition=f"{old_phase.value} -> {new_phase.value}")

        # Enhanced position update logging with phase transition
        log_position_update(
            logger,
            event_type="call_assignment",
            symbol=symbol,
            position_status="assigned",
            position_type="call",
            action="assignment",
            shares=shares,
            assignment_price=strike_price,
            capital_gain=capital_gain,
            remaining_shares=remaining_shares,
            phase_before=old_phase.value,
            phase_after=new_phase.value,
            wheel_cycle_completed=wheel_cycle_completed,
            cycle_duration_days=cycle_data.get('duration_days', 0) if cycle_data else 0,
        )

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

    def get_position_summary(self, symbol: str) -> Dict[str, Any]:
        """Get the tracked position summary for a symbol.

        Reconciliation reads ``stock_shares``/``active_puts``/``active_calls``
        off this; the rest is telemetry context.

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
            'wheel_cycle_start': state.get('wheel_cycle_start'),
        }
