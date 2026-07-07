"""Unit tests for the FC-032 simulation kernel: broker accounting/assignment
rules and the simulation clock time-seam.

(The old file of this name — which tested the never-working legacy engine — was
removed in Phase 0. This is the rebuilt kernel's suite.)
"""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from src.backtesting.engine.broker import BacktestBroker
from src.backtesting.engine.clock import SimClock
from src.utils import clock as time_seam


D0 = date(2025, 1, 6)
EXP = date(2025, 1, 10)


def _broker(cash=100_000.0, **kw):
    return BacktestBroker(cash, **kw)


# --------------------------------------------------------------------------- #
# Fill pricing
# --------------------------------------------------------------------------- #
class TestFills:
    def test_sell_fill_interpolates_toward_bid(self):
        b = _broker(fill_haircut=0.25)
        # mark 1.00, bid 0.80 -> 1.00 - 0.25*0.20 = 0.95
        assert b.sell_fill(1.00, 0.80) == pytest.approx(0.95)

    def test_buy_fill_interpolates_toward_ask(self):
        b = _broker(fill_haircut=0.25)
        # mark 1.00, ask 1.20 -> 1.00 + 0.25*0.20 = 1.05
        assert b.buy_fill(1.00, 1.20) == pytest.approx(1.05)

    def test_haircut_zero_is_mid(self):
        b = _broker(fill_haircut=0.0)
        assert b.sell_fill(1.0, 0.8) == 1.0
        assert b.buy_fill(1.0, 1.2) == 1.0

    def test_haircut_one_is_far_quote(self):
        b = _broker(fill_haircut=1.0)
        assert b.sell_fill(1.0, 0.8) == pytest.approx(0.8)
        assert b.buy_fill(1.0, 1.2) == pytest.approx(1.2)


# --------------------------------------------------------------------------- #
# Cash-secured put lifecycle
# --------------------------------------------------------------------------- #
class TestPutLifecycle:
    def test_sell_put_reserves_collateral_and_credits_premium(self):
        b = _broker(100_000.0, fees_per_contract=0.04, fill_haircut=0.0)
        fill = b.sell_put_to_open("XYZ_P90", "XYZ", 90.0, EXP, 1, mark=1.00, bid=0.90, opened=D0)
        assert fill == 1.00
        # cash += 100*1.00 - 0.04 = +99.96 ; collateral reserved = 9000
        assert b.cash == pytest.approx(100_000 + 99.96)
        assert b.reserved_collateral == pytest.approx(9000.0)
        assert b.available_cash == pytest.approx(100_000 + 99.96 - 9000)

    def test_sell_put_rejected_when_collateral_exceeds_available(self):
        b = _broker(5_000.0)
        # 90 strike -> 9000 collateral > 5000 available
        assert b.sell_put_to_open("XYZ_P90", "XYZ", 90.0, EXP, 1, 1.0, 0.9, D0) is None
        assert not b.options
        assert b.cash == 5_000.0

    def test_put_expires_worthless_keeps_premium_releases_collateral(self):
        b = _broker(100_000.0, fill_haircut=0.0)
        b.sell_put_to_open("XYZ_P90", "XYZ", 90.0, EXP, 1, 1.0, 0.9, D0)
        cash_after_open = b.cash
        b.settle_expirations(EXP, {"XYZ": 95.0})  # close above strike -> OTM
        assert not b.options  # position gone
        assert b.reserved_collateral == 0.0
        assert b.cash == cash_after_open  # premium kept, no assignment cash move
        assert b.shares("XYZ") == 0

    def test_put_assigned_buys_shares_at_strike(self):
        b = _broker(100_000.0, fill_haircut=0.0)
        b.sell_put_to_open("XYZ_P90", "XYZ", 90.0, EXP, 1, 1.0, 0.9, D0)
        cash_after_open = b.cash
        b.settle_expirations(EXP, {"XYZ": 85.0})  # below strike -> assigned
        assert not b.options
        assert b.shares("XYZ") == 100
        assert b.average_cost_basis("XYZ") == pytest.approx(90.0)
        assert b.cash == pytest.approx(cash_after_open - 9000.0)  # bought 100 @ 90
        assert b.reserved_collateral == 0.0

    def test_itm_threshold_penny(self):
        # Exactly 1 cent ITM -> assigned; 0.9 cent ITM -> worthless.
        b = _broker(100_000.0, fill_haircut=0.0)
        b.sell_put_to_open("A", "A", 90.0, EXP, 1, 1.0, 0.9, D0)
        b.settle_expirations(EXP, {"A": 89.99})  # 0.01 ITM
        assert b.shares("A") == 100

        b2 = _broker(100_000.0, fill_haircut=0.0)
        b2.sell_put_to_open("A", "A", 90.0, EXP, 1, 1.0, 0.9, D0)
        b2.settle_expirations(EXP, {"A": 89.991})  # 0.009 ITM -> not assigned
        assert b2.shares("A") == 0


# --------------------------------------------------------------------------- #
# Covered call lifecycle
# --------------------------------------------------------------------------- #
class TestCallLifecycle:
    def _with_shares(self, strike_basis=90.0):
        b = _broker(100_000.0, fill_haircut=0.0)
        b.sell_put_to_open("P", "XYZ", strike_basis, EXP, 1, 1.0, 0.9, D0)
        b.settle_expirations(EXP, {"XYZ": strike_basis - 5})  # assign -> 100 shares
        return b

    def test_sell_call_requires_shares(self):
        b = _broker(100_000.0)
        assert b.sell_call_to_open("C", "XYZ", 100.0, EXP, 1, 0.5, 0.4, D0) is None

    def test_covered_call_expires_worthless_keeps_shares(self):
        b = self._with_shares()
        exp2 = date(2025, 1, 17)
        b.sell_call_to_open("C", "XYZ", 100.0, exp2, 1, 0.5, 0.4, date(2025, 1, 13))
        cash_after = b.cash
        b.settle_expirations(exp2, {"XYZ": 95.0})  # below call strike -> OTM
        assert b.shares("XYZ") == 100
        assert not b.options
        assert b.cash == cash_after

    def test_covered_call_assigned_sells_shares_at_strike(self):
        b = self._with_shares()
        exp2 = date(2025, 1, 17)
        b.sell_call_to_open("C", "XYZ", 100.0, exp2, 1, 0.5, 0.4, date(2025, 1, 13))
        cash_after = b.cash
        b.settle_expirations(exp2, {"XYZ": 105.0})  # above strike -> called away
        assert b.shares("XYZ") == 0
        assert not b.options
        assert b.cash == pytest.approx(cash_after + 10_000.0)  # sold 100 @ 100

    def test_early_assignment(self):
        b = self._with_shares()
        exp2 = date(2025, 1, 17)
        b.sell_call_to_open("C", "XYZ", 100.0, exp2, 1, 0.5, 0.4, date(2025, 1, 13))
        cash_after = b.cash
        assert b.assign_call_early("C", date(2025, 1, 15), reason="ex_dividend")
        assert b.shares("XYZ") == 0
        assert b.cash == pytest.approx(cash_after + 10_000.0)


# --------------------------------------------------------------------------- #
# Buy-to-close, dividends, equity
# --------------------------------------------------------------------------- #
class TestCloseDividendEquity:
    def test_buy_to_close_releases_collateral(self):
        b = _broker(100_000.0, fees_per_contract=0.0, fill_haircut=0.0)
        b.sell_put_to_open("P", "XYZ", 90.0, EXP, 1, 1.00, 0.90, D0)
        assert b.reserved_collateral == 9000.0
        b.buy_to_close("P", 1, mark=0.30, ask=0.35, close_date=date(2025, 1, 8))
        assert not b.options
        assert b.reserved_collateral == 0.0
        # net premium: +100 (open) -30 (close) = +70
        assert b.cash == pytest.approx(100_000 + 70.0)

    def test_partial_close_releases_proportional_collateral(self):
        b = _broker(100_000.0, fees_per_contract=0.0, fill_haircut=0.0)
        b.sell_put_to_open("P", "XYZ", 90.0, EXP, 2, 1.00, 0.90, D0)
        assert b.reserved_collateral == 18_000.0
        b.buy_to_close("P", 1, 0.30, 0.35, date(2025, 1, 8))
        assert b.options["P"].contracts == 1
        assert b.reserved_collateral == pytest.approx(9000.0)

    def test_dividend_credit(self):
        b = _broker(100_000.0, fill_haircut=0.0)
        b.sell_put_to_open("P", "XYZ", 90.0, EXP, 1, 1.0, 0.9, D0)
        b.settle_expirations(EXP, {"XYZ": 85.0})  # 100 shares
        cash = b.cash
        credited = b.credit_dividend("XYZ", 0.50, date(2025, 1, 15))
        assert credited == pytest.approx(50.0)
        assert b.cash == pytest.approx(cash + 50.0)

    def test_equity_marks_shares_and_short_options(self):
        b = _broker(100_000.0, fees_per_contract=0.0, fill_haircut=0.0)
        b.sell_put_to_open("P", "XYZ", 90.0, EXP, 1, 1.0, 0.9, D0)  # cash +100
        # equity with the short put marked at 0.60: cash - 0.60*100
        eq = b.equity({"XYZ": 88.0}, {"P": 0.60})
        assert eq == pytest.approx(100_100 - 60.0)


# --------------------------------------------------------------------------- #
# Simulation clock / time seam
# --------------------------------------------------------------------------- #
class TestSimClock:
    def test_steps_freeze_and_clear_now(self):
        days = [date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)]
        clock = SimClock(days, decision_time=time(16, 0))
        seen = []
        assert not time_seam.is_frozen()
        for d in clock.steps():
            assert time_seam.is_frozen()
            assert time_seam.now() == datetime.combine(d, time(16, 0))
            seen.append(d)
        assert seen == days
        assert not time_seam.is_frozen()  # cleared after iteration
        assert clock.current_date == days[-1] or clock.current_date is None

    def test_seam_default_is_wall_clock(self):
        time_seam.set_now(None)
        assert not time_seam.is_frozen()
        # now() returns a real datetime close to wall clock
        assert isinstance(time_seam.now(), datetime)

    def test_frozen_context_restores(self):
        time_seam.set_now(None)
        with time_seam.frozen(datetime(2024, 6, 1, 10, 0)):
            assert time_seam.now() == datetime(2024, 6, 1, 10, 0)
        assert not time_seam.is_frozen()
