"""Tests for the roll-leg risk validator.

FC-069 item 7 shrank `RiskManager` to `validate_roll`, deleting six methods
that had zero production call sites ever recorded. The `TestRiskManager` class
that covered them went with them: it was the only thing in the repo asserting
that `validate_new_position` behaved, and what it actually pinned was the
behavior of code no entry point could reach — including two OCC-substring bugs
(`underlying_symbol in p['symbol']`, `'PUT' in pos['symbol']`) that it happily
asserted around rather than caught.

The live pre-trade controls are tested where they live: scanner filters
(`test_options_scanner.py`), selection ledgers (`test_execution_engine.py`),
the execute-time cost-basis floor (`test_cost_basis_resolver.py` and the FC-065
suites), and the hourly detective mirrors (`test_regression_monitor_risk.py`).
"""

import pytest
from unittest.mock import Mock

from src.risk.risk_manager import RiskManager
from src.utils.config import Config


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