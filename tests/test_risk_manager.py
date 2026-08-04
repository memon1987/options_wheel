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


# =========================================================================== #
# FC-078 — validate_roll, rewritten (T-7)
#
# Plan: docs/plans/fc-078.md DD-3. Three of the five checks changed, and each
# change undoes a specific way the as-built gate made the flagship credit roll
# illegal.
# =========================================================================== #

from datetime import date, timedelta  # noqa: E402


class TestValidateRoll:

    OLD_EXPIRY = date(2026, 8, 7)
    HORIZON = date(2026, 8, 21)          # old expiry + 14

    def _config(self, max_delta=0.60):
        config = Mock(spec=Config)
        config.rolling_max_replacement_delta = max_delta
        # Present but must NOT be consulted on this path any more.
        config.call_delta_range = [0.15, 0.25]
        config.min_call_premium = 0.30
        config.call_target_dte = 7
        return config

    def _call(self, strike=375.0, delta=0.45, expiry=None, mid=8.0):
        expiry = expiry or self.HORIZON
        return {'symbol': 'GOOGL260821C00375000', 'strike_price': strike,
                'delta': delta, 'mid_price': mid,
                'expiration_date': expiry.isoformat(),
                'dte': (expiry - self.OLD_EXPIRY).days}

    def _rm(self, **kw):
        return RiskManager(self._config(**kw))

    # --- roll-up and the floor: unchanged, and still load-bearing ---------- #

    def test_roll_up_only(self):
        valid, reason = self._rm().validate_roll(
            self._call(strike=365.0), 370.0, 300.0, self.HORIZON)
        assert valid is False
        assert 'not above current' in reason

    def test_below_cost_basis_is_rejected(self):
        valid, reason = self._rm().validate_roll(
            self._call(strike=375.0), 370.0, 380.0, self.HORIZON)
        assert valid is False
        assert 'cost basis' in reason

    def test_a_strike_exactly_at_the_floor_is_allowed(self):
        """FC-065 doctrine: floor = Alpaca avg_entry_price, so an at-floor
        call-away books >= $0 equity. Every floor gate rejects only
        ``strike < floor``."""
        valid, reason = self._rm().validate_roll(
            self._call(strike=375.0), 370.0, 375.0, self.HORIZON)
        assert valid is True, reason

    # --- delta: entry band exempt, upper rail applies ---------------------- #

    def test_a_near_money_replacement_is_accepted(self):
        """The entry band [0.15, 0.25] is the trap that made shallow-ITM rescue
        illegal — it forces far-OTM replacements exactly when the position
        needs near-money strikes.

        *Mutation:* restore entry-band reuse in validate_roll → this fails.
        """
        valid, reason = self._rm().validate_roll(
            self._call(delta=0.45), 370.0, 300.0, self.HORIZON)
        assert valid is True, reason

    def test_a_deep_itm_replacement_is_blocked_by_the_rail(self):
        """Pinning shares under a near-certain-assignment cap for another two
        weeks in exchange for pennies delays the wheel's recycle."""
        valid, reason = self._rm().validate_roll(
            self._call(delta=0.70), 370.0, 300.0, self.HORIZON)
        assert valid is False
        assert 'rail' in reason

    def test_the_rail_is_inclusive_at_its_bound(self):
        valid, reason = self._rm().validate_roll(
            self._call(delta=0.60), 370.0, 300.0, self.HORIZON)
        assert valid is True, reason

    # --- horizon: expiry-relative, not evaluation-relative ----------------- #

    def test_a_candidate_at_old_expiry_plus_fourteen_is_accepted(self):
        valid, reason = self._rm().validate_roll(
            self._call(expiry=self.HORIZON), 370.0, 300.0, self.HORIZON)
        assert valid is True, reason

    def test_a_candidate_at_old_expiry_plus_fifteen_is_rejected(self):
        valid, reason = self._rm().validate_roll(
            self._call(expiry=self.HORIZON + timedelta(days=1)),
            370.0, 300.0, self.HORIZON)
        assert valid is False
        assert 'horizon' in reason

    def test_the_bound_is_anchored_to_the_OLD_EXPIRY_not_the_evaluation_date(self):
        """The B-1 pin. GOOGL C370 8/07 rolled to 8/21 is 17-18 DTE from an
        8/04 evaluation but exactly old-expiry + 14 — the frame the
        investigation's "~14 DTE" numbers actually used. An eval-relative
        ``max_replacement_dte = 14`` would have excluded the flagship trade and
        logged ``no_credit_candidate`` while +$248/contract sat on the screen.

        *Mutation:* re-anchor the bound to the evaluation date → this fails.
        """
        candidate = self._call(expiry=self.HORIZON)
        assert candidate['dte'] == 14      # from the OLD EXPIRY

        valid, reason = self._rm().validate_roll(
            candidate, 370.0, 300.0, self.HORIZON)

        assert valid is True, reason
        # And the proof that no DTE-from-today rule survives: the same
        # candidate is legal even though it is well past call_target_dte (7).
        assert candidate['dte'] > 7

    def test_an_unparseable_expiry_fails_closed(self):
        """"We could not tell how far out this expires" must not resolve to
        "sell it"."""
        candidate = self._call()
        candidate['expiration_date'] = 'not-a-date'
        valid, reason = self._rm().validate_roll(
            candidate, 370.0, 300.0, self.HORIZON)
        assert valid is False
        assert 'unparseable' in reason

    # --- premium floor: gone ---------------------------------------------- #

    def test_a_sub_min_premium_replacement_is_accepted(self):
        """What a roll must clear is the NET credit against the contract being
        closed, which the roller enforces on the placed limits. A standalone
        premium floor answers a question nobody asked on this path.

        *Mutation:* apply the premium floor in the roll profile → this fails.
        """
        valid, reason = self._rm().validate_roll(
            self._call(mid=0.10), 370.0, 300.0, self.HORIZON)
        assert valid is True, reason