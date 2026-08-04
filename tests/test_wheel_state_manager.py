"""Tests for WheelStateManager — reconciliation's in-request bookkeeping.

**Scope after FC-069 item 8 stage 2.** The pre-shrink suite exercised a wheel
that did not exist: ``add_put_position``/``add_call_position`` accumulating
premium nothing ever paid, ``can_sell_puts``/``can_sell_calls`` gating trades
no live caller asked about, ``remove_position``/``record_call_roll`` maintaining
counters for a roller that went stateless in FC-078, and completed-cycle history
in a list whose only reader died with FC-068's ``get_strategy_status``. Those
tests passed for a year while the layer was inert — they pinned a simulation of
the wheel, not the wheel.

What is left is what ``WheelEngine.reconcile_positions`` actually calls, so
these tests pin the four survivors plus a census that fails if any of the
deleted surface comes back.

Plan: docs/plans/fc-069.md item 8. Closes FC-039.
"""

import inspect
from datetime import datetime, timedelta

import pytest

import src.strategy.wheel_state_manager as wsm_module
from src.strategy.wheel_state_manager import WheelStateManager, WheelPhase


class TestPutAssignment:
    """``handle_put_assignment`` — the OPASN-put half of reconciliation."""

    def setup_method(self):
        self.manager = WheelStateManager()
        self.symbol = "TEST"
        self.test_date = datetime(2024, 1, 15)

    def test_put_assignment_creates_the_stock_position(self):
        result = self.manager.handle_put_assignment(
            self.symbol, 100, 100.0, self.test_date
        )

        assert result['action'] == 'put_assignment'
        assert result['shares_assigned'] == 100
        assert result['total_shares'] == 100
        assert result['avg_cost_basis'] == 100.0
        assert result['phase_before'] == WheelPhase.SELLING_PUTS
        assert result['phase_after'] == WheelPhase.HOLDING_STOCK
        assert result['timestamp'] == self.test_date

        assert self.manager.get_wheel_phase(self.symbol) == WheelPhase.HOLDING_STOCK

    def test_a_first_assignment_opens_a_wheel_cycle(self):
        """``wheel_cycle_start`` is what makes the later cycle event fire; the
        cycle only opens on the transition from zero shares."""
        self.manager.handle_put_assignment(self.symbol, 100, 100.0, self.test_date)
        assert self.manager.symbol_states[self.symbol]['wheel_cycle_start'] == self.test_date

        later = self.test_date + timedelta(days=7)
        self.manager.handle_put_assignment(self.symbol, 100, 90.0, later)
        # Still the ORIGINAL start — a top-up does not restart the cycle.
        assert self.manager.symbol_states[self.symbol]['wheel_cycle_start'] == self.test_date

    def test_multiple_assignments_average_the_cost_basis(self):
        self.manager.handle_put_assignment(self.symbol, 100, 100.0, self.test_date)
        result = self.manager.handle_put_assignment(
            self.symbol, 100, 90.0, self.test_date + timedelta(days=7)
        )

        assert result['total_shares'] == 200
        assert result['avg_cost_basis'] == 95.0

        summary = self.manager.get_position_summary(self.symbol)
        assert summary['stock_shares'] == 200
        assert summary['stock_cost_basis'] == 95.0

    def test_assignment_decrements_the_tracked_put_count(self):
        """Reconciliation may have already recorded the short puts (the
        untracked-position sweep in ``reconcile_positions`` seeds them from
        Alpaca); assignment must consume them, one per 100 shares, floored."""
        self.manager.symbol_states[self.symbol] = {
            'stock_shares': 0, 'stock_cost_basis': 0.0, 'acquisition_date': None,
            'active_puts': 2, 'active_calls': 0, 'wheel_cycle_start': None,
        }
        self.manager.handle_put_assignment(self.symbol, 100, 100.0, self.test_date)
        assert self.manager.symbol_states[self.symbol]['active_puts'] == 1

        self.manager.handle_put_assignment(self.symbol, 300, 100.0, self.test_date)
        assert self.manager.symbol_states[self.symbol]['active_puts'] == 0

    def test_the_put_assignment_event_is_emitted_with_its_phase_transition(self):
        """The event, not the return value, is what survives the request — the
        result dict is discarded by both ``reconcile_positions`` call sites."""
        events = []
        original = wsm_module.log_position_update
        wsm_module.log_position_update = lambda logger, **kw: events.append(kw)
        try:
            self.manager.handle_put_assignment(self.symbol, 100, 100.0, self.test_date)
        finally:
            wsm_module.log_position_update = original

        assert len(events) == 1
        assert events[0] == {
            'event_type': 'put_assignment',
            'symbol': self.symbol,
            'position_status': 'assigned',
            'position_type': 'put',
            'action': 'assignment',
            'shares': 100,
            'assignment_price': 100.0,
            'total_shares': 100,
            'avg_cost_basis': 100.0,
            'phase_before': 'selling_puts',
            'phase_after': 'holding_stock',
            'wheel_cycle_started': True,
        }


class TestCallAssignment:
    """``handle_call_assignment`` — the OPASN-call half."""

    def setup_method(self):
        self.manager = WheelStateManager()
        self.symbol = "TEST"
        self.test_date = datetime(2024, 1, 15)

    def _held(self, shares=100, cost_basis=100.0, calls=1):
        self.manager.handle_put_assignment(
            self.symbol, shares, cost_basis, self.test_date
        )
        self.manager.symbol_states[self.symbol]['active_calls'] = calls

    def test_full_call_away_completes_the_cycle(self):
        self._held()
        call_date = self.test_date + timedelta(days=30)

        result = self.manager.handle_call_assignment(
            self.symbol, 100, 105.0, call_date
        )

        assert result['action'] == 'call_assignment'
        assert result['shares_called_away'] == 100
        assert result['strike_price'] == 105.0
        assert result['capital_gain'] == 500.0     # (105 - 100) * 100
        assert result['remaining_shares'] == 0
        assert result['wheel_cycle_completed'] is True
        assert result['phase_before'] == WheelPhase.SELLING_CALLS
        assert result['phase_after'] == WheelPhase.SELLING_PUTS

        cycle = result['completed_cycle']
        assert cycle['symbol'] == self.symbol
        assert cycle['duration_days'] == 30
        assert cycle['capital_gain'] == 500.0
        assert cycle['initial_cost_basis'] == 100.0
        assert cycle['final_sale_price'] == 105.0
        # The premium keys are gone: their only writers were the deleted
        # add_*_position methods, so every one of them was always 0.0.
        assert 'total_premium' not in cycle
        assert 'total_return' not in cycle

        # State reset for the next cycle.
        assert self.manager.symbol_states[self.symbol]['wheel_cycle_start'] is None
        assert self.manager.get_wheel_phase(self.symbol) == WheelPhase.SELLING_PUTS

    def test_partial_call_away_leaves_the_cycle_open(self):
        self._held(shares=200)

        result = self.manager.handle_call_assignment(
            self.symbol, 100, 105.0, self.test_date + timedelta(days=30)
        )

        assert result['remaining_shares'] == 100
        assert result['wheel_cycle_completed'] is False
        assert 'completed_cycle' not in result
        assert result['phase_after'] == WheelPhase.HOLDING_STOCK
        assert self.manager.symbol_states[self.symbol]['wheel_cycle_start'] == self.test_date

    def test_call_assignment_on_an_unknown_symbol_errors(self):
        result = self.manager.handle_call_assignment(
            "NONEXISTENT", 100, 105.0, self.test_date
        )
        assert result == {'error': 'No existing position'}

    def test_call_assignment_exceeding_held_shares_errors(self):
        self._held(shares=50)
        result = self.manager.handle_call_assignment(
            self.symbol, 100, 105.0, self.test_date
        )
        assert 'Insufficient shares' in result['error']
        # And it is a no-op — the position is untouched.
        assert self.manager.symbol_states[self.symbol]['stock_shares'] == 50

    def test_the_wheel_cycle_complete_event_still_fires(self):
        """This event has a **live** consumer: the BigQuery view
        ``options_wheel_logs.wheel_cycles`` matches on
        ``event_type = 'wheel_cycle_complete'``. Deleting the emission would
        silently starve it, so the emission is pinned independently of the
        return value.
        """
        self._held()
        call_date = self.test_date + timedelta(days=30)

        events = []
        original = wsm_module.log_position_update
        wsm_module.log_position_update = lambda logger, **kw: events.append(kw)
        try:
            self.manager.handle_call_assignment(self.symbol, 100, 105.0, call_date)
        finally:
            wsm_module.log_position_update = original

        cycle_events = [e for e in events
                        if e['event_type'] == 'wheel_cycle_complete']
        assert len(cycle_events) == 1
        assert cycle_events[0] == {
            'event_type': 'wheel_cycle_complete',
            'symbol': self.symbol,
            'position_status': 'cycle_complete',
            'capital_gain': 500.0,
            'cycle_duration_days': 30,
            'cost_basis': 100.0,
            'exit_price': 105.0,
        }

        assignment_events = [e for e in events
                             if e['event_type'] == 'call_assignment']
        assert len(assignment_events) == 1
        assert assignment_events[0] == {
            'event_type': 'call_assignment',
            'symbol': self.symbol,
            'position_status': 'assigned',
            'position_type': 'call',
            'action': 'assignment',
            'shares': 100,
            'assignment_price': 105.0,
            'capital_gain': 500.0,
            'remaining_shares': 0,
            'phase_before': 'selling_calls',
            'phase_after': 'selling_puts',
            'wheel_cycle_completed': True,
            'cycle_duration_days': 30,
        }

    def test_no_cycle_event_without_a_recorded_cycle_start(self):
        """The untracked-position sweep in ``reconcile_positions`` seeds state
        with ``wheel_cycle_start = None`` (it has no idea when the lot was
        acquired). A call-away on such a lot must not invent a duration.
        """
        self.manager.symbol_states[self.symbol] = {
            'stock_shares': 100, 'stock_cost_basis': 100.0,
            'acquisition_date': None, 'active_puts': 0, 'active_calls': 1,
            'wheel_cycle_start': None,
        }

        events = []
        original = wsm_module.log_position_update
        wsm_module.log_position_update = lambda logger, **kw: events.append(kw)
        try:
            result = self.manager.handle_call_assignment(
                self.symbol, 100, 105.0, self.test_date
            )
        finally:
            wsm_module.log_position_update = original

        assert result['wheel_cycle_completed'] is True
        assert 'completed_cycle' not in result
        assert not [e for e in events
                    if e['event_type'] == 'wheel_cycle_complete']
        assert [e for e in events
                if e['event_type'] == 'call_assignment'][0]['cycle_duration_days'] == 0


class TestPositionSummaryAndPhase:
    """``get_position_summary`` and the derived phase label."""

    def setup_method(self):
        self.manager = WheelStateManager()
        self.symbol = "TEST"
        self.test_date = datetime(2024, 1, 15)

    def test_summary_for_an_untracked_symbol(self):
        assert self.manager.get_position_summary("UNKNOWN") == {
            'symbol': "UNKNOWN",
            'wheel_phase': WheelPhase.SELLING_PUTS.value,
            'stock_shares': 0,
            'active_puts': 0,
            'active_calls': 0,
        }

    def test_summary_exposes_the_three_keys_reconciliation_diffs_on(self):
        """``reconcile_positions`` reads exactly these three off the summary;
        everything else in it is telemetry context."""
        self.manager.handle_put_assignment(self.symbol, 100, 100.0, self.test_date)
        self.manager.symbol_states[self.symbol]['active_puts'] = 2
        self.manager.symbol_states[self.symbol]['active_calls'] = 1

        summary = self.manager.get_position_summary(self.symbol)
        assert summary['stock_shares'] == 100
        assert summary['active_puts'] == 2
        assert summary['active_calls'] == 1
        assert summary['wheel_phase'] == WheelPhase.SELLING_CALLS.value
        assert summary['stock_cost_basis'] == 100.0
        assert summary['acquisition_date'] == self.test_date
        assert summary['wheel_cycle_start'] == self.test_date

    def test_the_summary_carries_no_permission_flags(self):
        """``can_sell_puts``/``can_sell_calls`` were gates nothing consulted
        (FC-069 item 8). Their presence in the summary is what made the layer
        look like a control."""
        self.manager.handle_put_assignment(self.symbol, 100, 100.0, self.test_date)
        for summary in (self.manager.get_position_summary(self.symbol),
                        self.manager.get_position_summary("UNKNOWN")):
            assert 'can_sell_puts' not in summary
            assert 'can_sell_calls' not in summary

    @pytest.mark.parametrize("shares,calls,expected", [
        (0, 0, WheelPhase.SELLING_PUTS),
        (100, 0, WheelPhase.HOLDING_STOCK),
        (100, 1, WheelPhase.SELLING_CALLS),
        (0, 1, WheelPhase.SELLING_PUTS),   # no shares -> not a covered call
    ])
    def test_phase_is_derived_from_the_position(self, shares, calls, expected):
        self.manager.symbol_states[self.symbol] = {
            'stock_shares': shares, 'stock_cost_basis': 0.0,
            'acquisition_date': None, 'active_puts': 0, 'active_calls': calls,
            'wheel_cycle_start': None,
        }
        assert self.manager.get_wheel_phase(self.symbol) == expected

    def test_an_untracked_symbol_has_no_phase_side_effects(self):
        """Reading a phase must not create state — reconciliation iterates the
        keys of ``symbol_states`` while calling these."""
        self.manager.get_wheel_phase("GHOST")
        self.manager.get_position_summary("GHOST")
        assert self.manager.symbol_states == {}


class TestTheShrinkCensus:
    """Tripwires for FC-069 item 8 stage 2 / FC-039.

    Each deleted method had a verified zero-caller census at deletion time. If
    one comes back, it comes back with a consumer — or these fail.
    """

    DELETED = (
        # GCS persistence — never enabled (FC-039), four ways proven.
        '_save_state', '_load_state', '_serialise_state', '_deserialise_state',
        # Phase gates — no live caller post-FC-068.
        'can_sell_puts', 'can_sell_calls',
        # Premium accumulators / position tracking — no live caller.
        'add_put_position', 'add_call_position', 'remove_position',
        'set_stock_cost_basis', 'reset_symbol_state',
        # Roller state — consumer-less since FC-078 made the roller stateless.
        'get_roll_count', 'get_active_call_details', 'set_active_call_details',
        'record_call_roll',
        # Cycle history — its reader died with FC-068's get_strategy_status.
        'get_all_wheel_cycles', 'get_symbols_by_phase',
    )

    def test_none_of_the_deleted_methods_exist(self):
        manager = WheelStateManager()
        back = [name for name in self.DELETED if hasattr(manager, name)]
        assert back == [], f"deleted state methods are back: {back}"

    def test_the_surviving_public_surface_is_exactly_four_methods(self):
        """An exhaustive assertion, not a subset one: a new public method here
        is a new consumer of a layer that is supposed to be shrinking."""
        public = sorted(
            name for name, _ in inspect.getmembers(
                WheelStateManager, predicate=inspect.isfunction)
            if not name.startswith('_')
        )
        assert public == [
            'get_position_summary',
            'get_wheel_phase',
            'handle_call_assignment',
            'handle_put_assignment',
        ], public

    def test_there_is_no_cycle_history_list(self):
        manager = WheelStateManager()
        assert not hasattr(manager, 'wheel_cycles')
        assert vars(manager) == {'symbol_states': {}}

    def test_state_entries_carry_no_premium_accumulators(self):
        """Their only writers are deleted, so any surviving key would be a
        permanent 0.0 masquerading as a measurement — the exact failure mode
        FC-069 item 10 dropped a whole BigQuery table over."""
        manager = WheelStateManager()
        manager.handle_put_assignment("TEST", 100, 100.0, datetime(2024, 1, 15))
        for key in ('total_premium_collected', 'put_premium_collected',
                    'call_premium_collected', 'total_rolls', 'roll_history',
                    'cumulative_roll_premium', 'active_call_details'):
            assert key not in manager.symbol_states["TEST"], key


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
