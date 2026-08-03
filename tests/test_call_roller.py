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
        # Use today's date to ensure DTE=0 (always eligible)
        today = datetime.now().strftime('%y%m%d')
        call_pos = {'symbol': f'AMD{today}C00100000', 'qty': '-1'}
        stock_pos = {'symbol': 'AMD', 'qty': '100', 'cost_basis': '9500'}
        should, reason = roller.should_roll(call_pos, stock_pos, 105.0)
        assert should is True
        assert reason == 'eligible'

    def test_blocked_dte_too_high(self, roller):
        # DTE > 1 should fail — use far-future expiry to avoid date sensitivity
        call_pos = {'symbol': 'AMD261231C00100000', 'qty': '-1'}
        stock_pos = {'symbol': 'AMD', 'qty': '100'}
        should, reason = roller.should_roll(call_pos, stock_pos, 105.0)
        assert should is False
        assert 'dte_too_high' in reason

    def test_blocked_not_itm_enough(self, roller):
        # Stock at 95, strike at 100 => ratio 0.95 < 0.98
        today = datetime.now().strftime('%y%m%d')
        call_pos = {'symbol': f'AMD{today}C00100000', 'qty': '-1'}
        stock_pos = {'symbol': 'AMD', 'qty': '100'}
        should, reason = roller.should_roll(call_pos, stock_pos, 95.0)
        assert should is False
        assert 'not_itm_enough' in reason

    def test_blocked_max_rolls_reached(self, roller, mock_wheel_state):
        mock_wheel_state.get_roll_count.return_value = 2
        today = datetime.now().strftime('%y%m%d')
        call_pos = {'symbol': f'AMD{today}C00100000', 'qty': '-1'}
        stock_pos = {'symbol': 'AMD', 'qty': '100'}
        should, reason = roller.should_roll(call_pos, stock_pos, 105.0)
        assert should is False
        assert 'max_rolls_reached' in reason

    def test_blocked_earnings_blackout(self, roller, mock_earnings):
        mock_earnings.is_earnings_within_n_days.return_value = True
        today = datetime.now().strftime('%y%m%d')
        call_pos = {'symbol': f'AMD{today}C00100000', 'qty': '-1'}
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

    def test_a_strike_exactly_at_the_floor_is_allowed(self):
        """FC-065 Phase 2, the gate half of the at-floor reconciliation: every
        floor gate rejects only ``strike < floor``. Called away at cost is flat
        on the shares plus both premiums — the guard blocks losses, not
        break-even — so the scanner's ``assignment_above_cost_basis`` flag now
        uses ``>=`` to say the same thing."""
        config = Mock()
        config.call_delta_range = [0.30, 0.70]
        config.min_call_premium = 0.30
        config.call_target_dte = 7
        new_call = {'strike_price': 110.0, 'delta': 0.40, 'mid_price': 1.50, 'dte': 7}

        valid, reason = RiskManager(config).validate_roll(new_call, 100.0, 110.0)

        assert valid is True, reason


# === FC-065 Phase 2: the roll's strike floor ===

class TestTheRollFloorComesFromTheSharedResolver:
    """Rolling places orders without passing ``execute_call_sale``, so its
    strike floor is the *only* below-basis protection on that path. FC-065
    Phase 2 routes it through the shared ``CostBasisResolver`` — the same
    number the scanner and the seller use — and fails closed when there is no
    usable floor.

    What it replaced: ``cost_basis / qty`` computed inline, which yielded 0
    whenever Alpaca reported no cost basis and left
    ``min_strike = current_strike + 0.01``. That is not a weak floor, it is no
    floor: it permits any strike a penny above the call being closed,
    regardless of what the shares cost. Every test in this class fails if that
    degradation is restored.
    """

    def _call_position(self):
        # DTE 0 so the rolling_max_current_dte gate passes on any run date.
        today = datetime.now().strftime('%y%m%d')
        return {'symbol': f'AMD{today}C00100000', 'qty': '-1'}

    def _stock_position(self, **overrides):
        """An assigned 100-share AMD lot.

        ``cost_basis``/``qty`` deliberately imply $95.00/share, which is *not*
        any floor these tests expect: it is the number the replaced derivation
        would produce, so a revert is visible rather than coincidentally
        passing.
        """
        position = {'symbol': 'AMD', 'qty': '100', 'cost_basis': '9500.0',
                    'asset_class': 'us_equity', 'side': 'long'}
        position.update(overrides)
        return position

    def _arm(self, mock_alpaca, mock_market_data, candidate_strike):
        """Wire a roll that succeeds on every gate except the floor.

        Stock at 105 against the 100 strike clears the ITM trigger; the
        replacement is a credit roll (BTC 1.20 / STC 1.40) well inside the
        debit tolerance. The floor is the only variable left.
        """
        mock_alpaca.get_stock_quote.return_value = {'last_price': 105.0}
        mock_alpaca.get_option_quote.return_value = {'ask_price': 1.20}
        mock_market_data.find_suitable_calls.return_value = [{
            'symbol': 'AMD260424C%08d' % int(candidate_strike * 1000),
            'strike_price': candidate_strike, 'delta': 0.40,
            'mid_price': 1.50, 'bid': 1.40, 'dte': 7,
        }]

    def test_an_unresolved_basis_blocks_the_roll(self, roller, mock_alpaca,
                                                 mock_market_data):
        """No ``avg_entry_price`` means no floor, and no floor means no roll.

        Reverting to ``max(cost_basis / qty, current_strike + 0.01)`` makes
        this fail loudly: with the field absent the old code floors at $100.01
        and returns a fully-formed opportunity to sell the 105 strike against
        shares whose cost is unknown.
        """
        self._arm(mock_alpaca, mock_market_data, candidate_strike=105.0)
        position = self._stock_position()
        position.pop('avg_entry_price', None)

        with patch('src.strategy.call_roller.logger') as mock_logger:
            result = roller.evaluate_roll_opportunity(self._call_position(), position)

        assert result is None
        # The chain was never even scanned — fail closed, not "scan and hope".
        mock_market_data.find_suitable_calls.assert_not_called()
        mock_alpaca.place_option_order.assert_not_called()

        skips = [c.kwargs for c in mock_logger.info.call_args_list
                 if c.kwargs.get('event_type')
                 == 'call_roll_skipped_cost_basis_unresolved']
        assert len(skips) == 1
        assert skips[0]['event_category'] == 'trade'
        assert skips[0]['underlying'] == 'AMD'
        assert skips[0]['success'] is False
        assert skips[0]['skip_reason'] == 'cost_basis_unresolved'
        assert skips[0]['cost_basis_source'] == 'unresolved'

    def test_a_zero_avg_entry_price_blocks_the_roll(self, roller, mock_alpaca,
                                                    mock_market_data):
        """FC-029 observed Alpaca reporting zero for assigned positions. A
        regression to that must halt rolling, not roll unprotected."""
        self._arm(mock_alpaca, mock_market_data, candidate_strike=105.0)

        result = roller.evaluate_roll_opportunity(
            self._call_position(), self._stock_position(avg_entry_price='0'))

        assert result is None
        mock_market_data.find_suitable_calls.assert_not_called()

    def test_a_divergent_cross_check_blocks_the_roll(self, roller, mock_alpaca,
                                                     mock_market_data):
        """The broker gave a number and the assignment history contradicts it.

        ``resolve_detailed`` returns a zero basis for that verdict too, so the
        same fail-closed branch catches it — but under its **own** event name.
        "Resolved and vetoed" is not "unresolved": labelling it so is wrong on
        its face and hides the symbol from every ``*_divergent`` taxonomy, which
        is the one that means "the broker's number may be wrong" rather than
        "the broker said nothing". Mirrors the scanner's two-event split.
        """
        self._arm(mock_alpaca, mock_market_data, candidate_strike=115.0)

        with patch.object(roller.cost_basis_resolver, '_lookup_assignment_basis',
                          return_value={'expected_basis_per_share': 90.00,
                                        'reconstructed_shares': 100, 'lots': []}):
            with patch('src.strategy.call_roller.logger') as mock_logger:
                result = roller.evaluate_roll_opportunity(
                    self._call_position(),
                    self._stock_position(avg_entry_price='110.00'))

        assert result is None
        mock_market_data.find_suitable_calls.assert_not_called()

        skips = [c.kwargs for c in mock_logger.info.call_args_list
                 if c.kwargs.get('event_type')
                 == 'call_roll_skipped_cost_basis_divergent']
        assert len(skips) == 1
        assert skips[0]['skip_reason'] == 'cost_basis_divergent'
        assert skips[0]['cost_basis_source'] == 'divergent'
        assert skips[0]['broker_basis'] == 110.00
        assert skips[0]['expected_basis'] == 90.00
        assert skips[0]['basis_delta'] == pytest.approx(20.00)
        assert skips[0]['cross_check_reason'] == 'basis_mismatch'

        # ...and it does NOT also fire the unresolved event. The two are
        # distinct failures and a divergence must not be double-counted as one.
        assert not [c.kwargs for c in mock_logger.info.call_args_list
                    if c.kwargs.get('event_type')
                    == 'call_roll_skipped_cost_basis_unresolved']

    def test_an_unresolved_basis_is_not_labelled_divergent(self, roller,
                                                           mock_alpaca,
                                                           mock_market_data):
        """The other side of the split: nothing to floor against is not a
        contradicted floor. Swapping the two labels fails here and in the
        divergent test above."""
        self._arm(mock_alpaca, mock_market_data, candidate_strike=105.0)

        with patch('src.strategy.call_roller.logger') as mock_logger:
            result = roller.evaluate_roll_opportunity(
                self._call_position(), self._stock_position(avg_entry_price='0'))

        assert result is None
        events = [c.kwargs.get('event_type') for c in mock_logger.info.call_args_list]
        assert 'call_roll_skipped_cost_basis_unresolved' in events
        assert 'call_roll_skipped_cost_basis_divergent' not in events

    def test_the_fallback_re_floor_still_honours_the_basis(self, roller,
                                                          mock_alpaca,
                                                          mock_market_data):
        """FC-065 Phase 2 (review, R1 LOW): ``_attempt_stc`` re-derives the floor
        when both direct STO attempts fail, and that is the **second** live
        application of the basis floor on the roll path — untested until now.

        Basis $110.00 against a $100 old strike, so the basis term is the one
        that must win the ``max()``. Dropping it floors the fallback search at
        $100.01 and lets the retry sell strikes below what the shares cost —
        precisely the hole the evaluation-time floor was fixed to close.
        """
        opportunity = {'cost_basis_per_share': 110.00, 'old_strike': 100.0}
        # Both direct attempts fail, so the fallback re-floor runs. A rejected
        # order returns immediately — no polling, no sleep.
        mock_alpaca.place_option_order.return_value = {'success': False}
        mock_market_data.find_suitable_calls.return_value = []

        roller._attempt_stc('AMD260424C00105000', 'AMD', 1, 1.40, opportunity, {})

        mock_market_data.find_suitable_calls.assert_called_once_with(
            'AMD', min_strike_price=110.00)

    def test_the_resolved_basis_is_the_strike_floor(self, roller, mock_alpaca,
                                                    mock_market_data):
        """The positive case, and the one that pins *which* number is used.

        Alpaca says $110.00/share; ``cost_basis / qty`` says $95.00. The floor
        handed to the chain scan must be the resolver's $110.00 — a revert to
        the old derivation floors at $95.00 and admits strikes between the two.
        """
        self._arm(mock_alpaca, mock_market_data, candidate_strike=112.0)

        result = roller.evaluate_roll_opportunity(
            self._call_position(), self._stock_position(avg_entry_price='110.00'))

        mock_market_data.find_suitable_calls.assert_called_once_with(
            'AMD', min_strike_price=110.00)
        assert result is not None
        assert result['cost_basis_per_share'] == 110.00
        assert result['new_strike'] == 112.0

    def test_the_roll_up_rule_still_floors_a_low_basis(self, roller, mock_alpaca,
                                                       mock_market_data):
        """Below-basis protection is a floor, not the only floor: a basis under
        the call being closed must not let the roll go sideways or down."""
        self._arm(mock_alpaca, mock_market_data, candidate_strike=105.0)

        result = roller.evaluate_roll_opportunity(
            self._call_position(), self._stock_position(avg_entry_price='90.00'))

        mock_market_data.find_suitable_calls.assert_called_once_with(
            'AMD', min_strike_price=100.01)
        assert result is not None
        assert result['cost_basis_per_share'] == 90.00


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


class TestRollerEarningsGateUnchanged:
    """FC-013 test 14 — the operator decided the roller keeps its gate as-is.

    FC-013 introduces fail-CLOSED tri-state semantics for the scanner's gate.
    Those must not leak here: the roll path still consumes the boolean
    `is_earnings_within_n_days` surface and still fails OPEN. Two different
    postures on one service object, deliberately (FC-069 item 4 sign-off,
    unification handed to FC-066's pre-revival checklist).
    """

    def test_the_roller_still_calls_the_boolean_surface_not_the_tristate(
            self, roller, mock_earnings):
        today = datetime.now().strftime('%y%m%d')
        call_pos = {'symbol': f'AMD{today}C00100000', 'qty': '-1'}
        stock_pos = {'symbol': 'AMD', 'qty': '100', 'cost_basis': '9500'}

        roller.should_roll(call_pos, stock_pos, 105.0)

        assert mock_earnings.is_earnings_within_n_days.called
        assert not mock_earnings.next_earnings_info.called
        assert not mock_earnings.earnings_within.called

    def test_it_still_uses_the_rolling_knob_not_the_scanner_gates(
            self, roller, mock_earnings, rolling_config):
        """Two knobs stay separate (DD-5). Unifying them would reach into the
        roller's config surface while FC-069 item 13 holds all `rolling.*`
        keys for FC-066."""
        today = datetime.now().strftime('%y%m%d')
        call_pos = {'symbol': f'AMD{today}C00100000', 'qty': '-1'}
        stock_pos = {'symbol': 'AMD', 'qty': '100', 'cost_basis': '9500'}

        roller.should_roll(call_pos, stock_pos, 105.0)

        _, kwargs = mock_earnings.is_earnings_within_n_days.call_args
        args, _ = mock_earnings.is_earnings_within_n_days.call_args
        assert args[1] == rolling_config.rolling_earnings_blackout_days == 2

    def test_a_real_service_still_fails_open_for_the_roller(self):
        """The live service's boolean surface must keep allowing the roll when
        the calendar cannot answer — the exact case FC-013 makes the scanner
        BLOCK on. If this flips, FC-013 changed the roller against the
        operator's decision.
        """
        from unittest.mock import patch as _patch
        from src.api.earnings_calendar import (
            EARNINGS_UNKNOWN, EarningsCalendarService)

        cfg = Mock()
        cfg.finnhub_api_key = "test_finnhub_key"
        cfg.earnings_enabled = True
        cfg.earnings_cache_ttl_hours = 24
        cfg.earnings_lookahead_days = 90
        cfg.opportunity_bucket = "test-bucket"

        with _patch.object(EarningsCalendarService, "_fetch_earnings",
                           lambda self, symbol: None):
            svc = EarningsCalendarService(cfg)

            assert svc.next_earnings_info("AMD") == (EARNINGS_UNKNOWN, None)
            assert svc.earnings_within("AMD", 2) is None       # scanner: block
            assert svc.is_earnings_within_n_days("AMD", 2) is False  # roller: allow
