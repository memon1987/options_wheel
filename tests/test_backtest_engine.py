"""Unit tests for the FC-032 simulation kernel: broker accounting/assignment
rules and the simulation clock time-seam.

(The old file of this name — which tested the never-working legacy engine — was
removed in Phase 0. This is the rebuilt kernel's suite.)
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

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
        # CASH moves at the strike: 100 shares × $90.
        assert b.cash == pytest.approx(cash_after_open - 9000.0)
        assert b.reserved_collateral == 0.0
        # BASIS is premium-netted (FC-068) — see the class below.
        assert b.average_cost_basis("XYZ") == pytest.approx(89.0)

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


class TestAssignmentBasisIsPremiumNetted:
    """FC-068 §7 — the backtest floor was one put premium above production's.

    Production's covered-call floor is Alpaca's ``avg_entry_price``, which for
    an assigned lot is ``strike − the assigning put's premium`` (verified to
    the penny on all four live lots, FC-065 Phase 1). The broker booked the lot
    at the bare strike, and the adapter derives ``avg_entry_price`` from lot
    basis — so every replay gated covered calls one premium too high. On IWM's
    $1 strike grid that is a full rung, and IWM is in the six-symbol effective
    universe.

    Every test in this class FAILS against the pre-FC-068 broker.
    """

    def test_assignment_basis_is_premium_netted(self):
        b = _broker(100_000.0, fill_haircut=0.0)
        b.sell_put_to_open("XYZ_P90", "XYZ", 90.0, EXP, 1, mark=1.50, bid=1.40, opened=D0)
        b.settle_expirations(EXP, {"XYZ": 85.0})

        assert b.average_cost_basis("XYZ") == pytest.approx(88.50)   # 90 − 1.50

    def test_the_adapter_reports_the_netted_basis_as_avg_entry_price(self):
        """The floor reads `avg_entry_price` off the adapter, not the broker,
        so netting the lot without the adapter surfacing it changes nothing."""
        from src.backtesting.engine.alpaca_adapter import BacktestAlpacaClient

        b = _broker(100_000.0, fill_haircut=0.0)
        b.sell_put_to_open("XYZ_P90", "XYZ", 90.0, EXP, 1, mark=1.50, bid=1.40, opened=D0)
        b.settle_expirations(EXP, {"XYZ": 85.0})

        client = BacktestAlpacaClient(b, chains={}, stock_bars={})
        with time_seam.frozen(datetime.combine(EXP, time(16, 0))):
            equity = [p for p in client.get_positions()
                      if p["asset_class"] == "us_equity"]
        assert len(equity) == 1
        assert float(equity[0]["avg_entry_price"]) == pytest.approx(88.50)

    def test_the_haircut_premium_is_what_nets(self):
        """The netting uses the fill this engine actually modelled, not the
        mid — consistent with the cash the ledger credited at open."""
        b = _broker(100_000.0, fill_haircut=1.0)     # fill at the bid
        fill = b.sell_put_to_open("XYZ_P90", "XYZ", 90.0, EXP, 1,
                                  mark=1.50, bid=1.00, opened=D0)
        assert fill == pytest.approx(1.00)
        b.settle_expirations(EXP, {"XYZ": 85.0})

        assert b.average_cost_basis("XYZ") == pytest.approx(89.00)

    def test_multi_lot_weighting_is_the_brokers_weighted_average(self):
        """Alpaca averages across lots; so must this. Two assignments at
        different strikes and different premiums."""
        b = _broker(100_000.0, fill_haircut=0.0)
        b.sell_put_to_open("A_P90", "A", 90.0, EXP, 1, mark=1.00, bid=0.9, opened=D0)
        b.settle_expirations(EXP, {"A": 85.0})
        exp2 = EXP + timedelta(days=7)
        b.sell_put_to_open("A_P80", "A", 80.0, exp2, 2, mark=2.00, bid=1.9, opened=D0)
        b.settle_expirations(exp2, {"A": 70.0})

        assert b.shares("A") == 300
        # (100 × 89.00 + 200 × 78.00) / 300
        assert b.average_cost_basis("A") == pytest.approx((89.0 + 2 * 78.0) / 3)

    def test_the_cash_ledger_still_moves_at_the_strike(self):
        """The ledger event is the load-bearing half of the split contract:
        `metrics/cycles.py`, `metrics/fitness.py` and `reporting/report.py` all
        derive the cycle's cost basis from `event.price`, while `option_pnl`
        separately counts the put premium. Netting the premium into `price` or
        `cash_delta` double-counts it in every assigned cycle."""
        b = _broker(100_000.0, fill_haircut=0.0)
        b.sell_put_to_open("XYZ_P90", "XYZ", 90.0, EXP, 1, mark=1.50, bid=1.40, opened=D0)
        cash_after_open = b.cash
        b.settle_expirations(EXP, {"XYZ": 85.0})

        event = [e for e in b.ledger if e.kind == "put_assignment"][0]
        assert event.price == pytest.approx(90.0)
        assert event.cash_delta == pytest.approx(-9000.0)
        assert b.cash == pytest.approx(cash_after_open - 9000.0)
        # Both numbers are on the event, explicitly, so a reader never has to
        # guess which one it is holding.
        assert event.detail["strike"] == pytest.approx(90.0)
        assert event.detail["basis"] == pytest.approx(88.50)

    def test_a_premium_at_or_above_the_strike_falls_back_to_the_strike(self):
        """Not a real fill, but a zero or negative basis would silently DISABLE
        the covered-call floor: `find_suitable_calls` warns and carries on when
        `min_strike_price <= 0`. Fail toward protection."""
        b = _broker(100_000.0, fill_haircut=0.0)
        b.sell_put_to_open("XYZ_P5", "XYZ", 5.0, EXP, 1, mark=5.0, bid=5.0, opened=D0)
        b.settle_expirations(EXP, {"XYZ": 1.0})

        assert b.average_cost_basis("XYZ") == pytest.approx(5.0)


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


class TestBuyToCloseCashCheck:
    """A cash-secured account cannot take a margin loan to close a losing call.

    Regression for an adversarial-review finding: buy_to_close performed no cash
    check, so an expensive buyback drove cash to -$4,727. That matters most in
    exactly the case rolling exists for — a deep-ITM covered call, when cash is
    tight because it went into the assigned shares. Live: order rejected, shares
    called away. Sim (before this): roll succeeds, escaping the loss.
    """

    def _covered(self, cash):
        from datetime import date as _d

        from src.backtesting.engine.broker import BacktestBroker
        b = BacktestBroker(starting_cash=cash)
        b._add_stock("XYZ", 100, 10.0, _d(2025, 1, 6))
        b.sell_call_to_open("C1", "XYZ", 12.0, _d(2025, 1, 17), 1, 1.00, 0.90, _d(2025, 1, 6))
        return b

    def test_expensive_buyback_is_rejected_and_cash_stays_positive(self):
        from datetime import date as _d

        b = self._covered(1200.0)
        assert b.buy_to_close("C1", 1, 60.0, 61.0, _d(2025, 1, 10)) is None
        assert b.cash > 0
        assert "C1" in b.options, "rejected close must leave the position open"

    def test_affordable_buyback_still_works(self):
        from datetime import date as _d

        b = self._covered(50_000.0)
        assert b.buy_to_close("C1", 1, 0.50, 0.55, _d(2025, 1, 10)) is not None
        assert "C1" not in b.options

    def test_csp_buyback_may_use_its_own_released_collateral(self):
        """The reserve backing the very put being closed is not a blocker."""
        from datetime import date as _d

        from src.backtesting.engine.broker import BacktestBroker
        b = BacktestBroker(starting_cash=9_100.0)
        b.sell_put_to_open("P1", "XYZ", 90.0, _d(2025, 1, 17), 1, 1.00, 0.90, _d(2025, 1, 6))
        assert b.available_cash < 500  # nearly all cash is reserved
        assert b.buy_to_close("P1", 1, 0.40, 0.45, _d(2025, 1, 10)) is not None


class TestSplitGuard:
    """Raw bars are right for point-in-time chains but cannot span a split."""

    def _bars(self, closes):
        from datetime import date as _d, timedelta as _td

        from src.backtesting.data.provider import StockBar
        start = _d(2024, 6, 3)
        return [
            StockBar(symbol="NVDA", bar_date=start + _td(days=i), open=c, high=c,
                     low=c, close=c, volume=1)
            for i, c in enumerate(closes)
        ]

    def test_detects_a_ten_for_one_split(self):
        from src.backtesting.data.alpaca_provider import detect_split

        # NVDA's real 2024-06-10 split: 1208.88 -> 121.79
        got = detect_split(self._bars([1150.0, 1164.37, 1208.88, 121.79, 120.91]))
        assert got is not None
        _, ratio = got
        assert ratio == pytest.approx(0.101, abs=0.002)

    def test_ordinary_volatility_is_not_flagged(self):
        from src.backtesting.data.alpaca_provider import detect_split

        # A brutal but real -25% earnings gap must not be mistaken for a split.
        assert detect_split(self._bars([100.0, 75.0, 78.0, 70.0, 95.0])) is None


class TestCoverAccounting:
    """A covered call must be covered by shares nothing else has claimed.

    Regression for an adversarial-review finding: the cover check counted TOTAL
    shares, so two calls could be written against the same 100 shares. On
    settlement the broker credited proceeds for 200 shares while holding 100 and
    only logged a warning — $10,595 of phantom cash in the demonstrated case.
    """

    def _long_100(self, cash=100_000.0):
        from datetime import date as _d

        from src.backtesting.engine.broker import BacktestBroker
        b = BacktestBroker(starting_cash=cash)
        b._add_stock("XYZ", 100, 100.0, _d(2025, 1, 6))
        return b

    def test_second_call_against_the_same_shares_is_rejected(self):
        from datetime import date as _d

        b = self._long_100()
        assert b.sell_call_to_open("C1", "XYZ", 105.0, _d(2025, 1, 17), 1,
                                   1.0, 0.9, _d(2025, 1, 6)) is not None
        assert b.sell_call_to_open("C2", "XYZ", 106.0, _d(2025, 1, 17), 1,
                                   1.0, 0.9, _d(2025, 1, 6)) is None
        assert b.pledged_shares("XYZ") == 100
        assert b.uncovered_shares("XYZ") == 0

    def test_settlement_cannot_mint_cash(self):
        from datetime import date as _d

        b = self._long_100()
        b.sell_call_to_open("C1", "XYZ", 105.0, _d(2025, 1, 17), 1,
                            1.0, 0.9, _d(2025, 1, 6))
        b.settle_expirations(_d(2025, 1, 17), {"XYZ": 120.0})
        # 100k cash + 10,500 called away @105 + 97.46 premium net of $0.04 fees.
        assert b.cash == pytest.approx(110_597.46, abs=0.01)
        assert b.shares("XYZ") == 0

    def test_disposing_more_shares_than_held_raises(self):
        """Silently inventing shares is how a ledger mints money."""
        b = self._long_100()
        with pytest.raises(ValueError, match="more than held"):
            b._remove_shares_fifo("XYZ", 200)

    def test_a_second_call_is_allowed_once_shares_support_it(self):
        from datetime import date as _d

        b = self._long_100()
        b._add_stock("XYZ", 100, 100.0, _d(2025, 1, 6))  # now 200 shares
        assert b.sell_call_to_open("C1", "XYZ", 105.0, _d(2025, 1, 17), 1,
                                   1.0, 0.9, _d(2025, 1, 6)) is not None
        assert b.sell_call_to_open("C2", "XYZ", 106.0, _d(2025, 1, 17), 1,
                                   1.0, 0.9, _d(2025, 1, 6)) is not None
