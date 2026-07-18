"""Cycle analytics, fitness scorecard, and report rendering (FC-032 Phase 4).

These numbers are what a human reads to decide whether a symbol stays in the
universe, so the tests are about *not misleading*: attribution must stay split,
an unfinished cycle must not vanish, and a win rate must never appear without
its tail.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.backtesting.engine.broker import LedgerEvent
from src.backtesting.engine.simulator import DailyState
from src.backtesting.metrics.cycles import build_cycles, count_rolls
from src.backtesting.metrics.fitness import compute_fitness
from src.backtesting.reporting.report import render_json, render_markdown

D = date


def _ev(day, kind, underlying="XYZ", symbol="", **kw):
    return LedgerEvent(event_date=day, kind=kind, underlying=underlying,
                       symbol=symbol, **kw)


def _states(days, equities, shares=None):
    return [
        DailyState(day=d, equity=e, cash=e, reserved_collateral=0.0,
                   open_options=0, shares_held=(shares or {}).get(d, {}))
        for d, e in zip(days, equities)
    ]


# --------------------------------------------------------------------------- #
# Cycles
# --------------------------------------------------------------------------- #
class TestCycles:
    def test_put_expiring_worthless_is_one_closed_cycle(self):
        ledger = [
            _ev(D(2025, 1, 6), "sell_put_open", symbol="P1", contracts=1,
                cash_delta=100.0, fees=0.04, detail={"collateral": 9000.0}),
            _ev(D(2025, 1, 10), "expire_worthless", symbol="P1", contracts=1),
        ]
        cycles = build_cycles(ledger)
        assert len(cycles) == 1
        c = cycles[0]
        assert not c.is_open and c.outcome() == "expired_worthless"
        assert c.option_pnl == pytest.approx(100.0)
        assert c.stock_pnl == 0.0
        assert c.days == 4
        assert c.capital_at_risk == pytest.approx(9000.0)

    def test_full_wheel_turn_splits_option_and_stock_pnl(self):
        """Put -> assigned at 90 -> call sold -> called away at 95."""
        ledger = [
            _ev(D(2025, 1, 6), "sell_put_open", symbol="P1", contracts=1,
                cash_delta=100.0, detail={"collateral": 9000.0}),
            _ev(D(2025, 1, 10), "put_assignment", symbol="P1", contracts=1,
                shares=100, price=90.0, cash_delta=-9000.0),
            _ev(D(2025, 1, 13), "sell_call_open", symbol="C1", contracts=1,
                cash_delta=80.0),
            _ev(D(2025, 1, 17), "call_assignment", symbol="C1", contracts=1,
                shares=100, price=95.0, cash_delta=9500.0),
        ]
        c = build_cycles(ledger)[0]
        assert c.assigned and c.called_away
        assert c.outcome() == "called_away"
        assert c.option_pnl == pytest.approx(180.0)      # both premiums
        assert c.stock_pnl == pytest.approx(500.0)       # (95-90)*100
        assert c.total_pnl == pytest.approx(680.0)
        assert c.cost_basis == 90.0 and c.exit_price == 95.0

    def test_cycle_still_open_at_window_end_is_reported_not_dropped(self):
        """Holding shares at the end is a real state; hiding it flatters the result."""
        ledger = [
            _ev(D(2025, 1, 6), "sell_put_open", symbol="P1", contracts=1,
                cash_delta=100.0, detail={"collateral": 9000.0}),
            _ev(D(2025, 1, 10), "put_assignment", symbol="P1", contracts=1,
                shares=100, price=90.0, cash_delta=-9000.0),
        ]
        cycles = build_cycles(ledger)
        assert len(cycles) == 1
        assert cycles[0].is_open and cycles[0].outcome() == "open"
        assert cycles[0].end is None

    def test_two_sequential_cycles_on_one_symbol_are_separate(self):
        ledger = [
            _ev(D(2025, 1, 6), "sell_put_open", symbol="P1", contracts=1,
                cash_delta=100.0, detail={"collateral": 9000.0}),
            _ev(D(2025, 1, 10), "expire_worthless", symbol="P1", contracts=1),
            _ev(D(2025, 1, 13), "sell_put_open", symbol="P2", contracts=1,
                cash_delta=120.0, detail={"collateral": 9100.0}),
            _ev(D(2025, 1, 17), "expire_worthless", symbol="P2", contracts=1),
        ]
        cycles = build_cycles(ledger)
        assert len(cycles) == 2
        assert [c.option_pnl for c in cycles] == [100.0, 120.0]

    def test_two_symbols_do_not_bleed_into_each_others_cycles(self):
        ledger = [
            _ev(D(2025, 1, 6), "sell_put_open", "AAA", "A1", contracts=1,
                cash_delta=100.0, detail={"collateral": 9000.0}),
            _ev(D(2025, 1, 7), "sell_put_open", "BBB", "B1", contracts=1,
                cash_delta=200.0, detail={"collateral": 5000.0}),
            _ev(D(2025, 1, 10), "expire_worthless", "AAA", "A1", contracts=1),
            _ev(D(2025, 1, 10), "expire_worthless", "BBB", "B1", contracts=1),
        ]
        cycles = build_cycles(ledger)
        assert {c.underlying for c in cycles} == {"AAA", "BBB"}
        assert {c.underlying: c.option_pnl for c in cycles} == {"AAA": 100.0, "BBB": 200.0}

    def test_buyback_reduces_option_pnl(self):
        ledger = [
            _ev(D(2025, 1, 6), "sell_put_open", symbol="P1", contracts=1,
                cash_delta=100.0, detail={"collateral": 9000.0}),
            _ev(D(2025, 1, 8), "buy_to_close", symbol="P1", contracts=1,
                cash_delta=-30.0),
        ]
        c = build_cycles(ledger)[0]
        assert c.option_pnl == pytest.approx(70.0)

    def test_dividends_are_counted_but_kept_out_of_option_and_stock_legs(self):
        ledger = [
            _ev(D(2025, 1, 6), "sell_put_open", symbol="P1", contracts=1,
                cash_delta=100.0, detail={"collateral": 9000.0}),
            _ev(D(2025, 1, 10), "put_assignment", symbol="P1", contracts=1,
                shares=100, price=90.0, cash_delta=-9000.0),
            _ev(D(2025, 1, 15), "dividend", shares=100, price=0.5, cash_delta=50.0),
            _ev(D(2025, 1, 17), "call_assignment", symbol="C1", contracts=1,
                shares=100, price=90.0, cash_delta=9000.0),
        ]
        c = build_cycles(ledger)[0]
        assert c.dividends == pytest.approx(50.0)
        assert c.stock_pnl == pytest.approx(0.0)
        assert c.total_pnl == pytest.approx(150.0)

    def test_roll_is_a_same_day_close_and_reopen(self):
        ledger = [
            _ev(D(2025, 1, 6), "sell_put_open", symbol="P1", contracts=1,
                cash_delta=100.0, detail={"collateral": 9000.0}),
            _ev(D(2025, 1, 10), "put_assignment", symbol="P1", contracts=1,
                shares=100, price=90.0, cash_delta=-9000.0),
            _ev(D(2025, 1, 13), "sell_call_open", symbol="C1", contracts=1,
                cash_delta=80.0),
            _ev(D(2025, 1, 17), "buy_to_close", symbol="C1", contracts=1, cash_delta=-120.0),
            _ev(D(2025, 1, 17), "sell_call_open", symbol="C2", contracts=1, cash_delta=140.0),
            _ev(D(2025, 1, 24), "call_assignment", symbol="C2", contracts=1,
                shares=100, price=95.0, cash_delta=9500.0),
        ]
        cycles = build_cycles(ledger)
        assert count_rolls(cycles) == 1

    def test_annualized_return_is_linear_not_compounded(self):
        """A 3-day cycle compounded to a year is a number about the exponent."""
        ledger = [
            _ev(D(2025, 1, 6), "sell_put_open", symbol="P1", contracts=1,
                cash_delta=90.0, detail={"collateral": 9000.0}),
            _ev(D(2025, 1, 9), "expire_worthless", symbol="P1", contracts=1),
        ]
        c = build_cycles(ledger)[0]
        assert c.return_on_capital == pytest.approx(0.01)
        assert c.annualized_return == pytest.approx(0.01 * 365 / 3)


# --------------------------------------------------------------------------- #
# Fitness
# --------------------------------------------------------------------------- #
class TestFitness:
    def _report(self, equities=(100_000, 100_500, 101_000), **kw):
        days = [D(2025, 1, 6), D(2025, 1, 7), D(2025, 1, 8)]
        ledger = [
            _ev(days[0], "sell_put_open", symbol="P1", contracts=1,
                cash_delta=1000.0, detail={"collateral": 9000.0}),
            _ev(days[-1], "expire_worthless", symbol="P1", contracts=1),
        ]
        return compute_fitness("XYZ", _states(days, list(equities)),
                               build_cycles(ledger), 100_000.0, **kw)

    def test_attribution_is_never_collapsed(self):
        r = self._report()
        assert r.option_pnl == pytest.approx(1000.0)
        assert r.stock_pnl == 0.0
        assert r.option_pnl_share == pytest.approx(1.0)

    def test_attribution_share_is_none_when_legs_have_opposite_signs(self):
        """+500 premium against -5000 stock is not '10% from options'."""
        days = [D(2025, 1, 6), D(2025, 1, 8)]
        ledger = [
            _ev(days[0], "sell_put_open", symbol="P1", contracts=1,
                cash_delta=500.0, detail={"collateral": 9000.0}),
            _ev(days[0], "put_assignment", symbol="P1", contracts=1,
                shares=100, price=100.0, cash_delta=-10000.0),
            _ev(days[1], "call_assignment", symbol="C1", contracts=1,
                shares=100, price=50.0, cash_delta=5000.0),
        ]
        r = compute_fitness("XYZ", _states(days, [100_000, 95_500]),
                            build_cycles(ledger), 100_000.0)
        assert r.option_pnl > 0 and r.stock_pnl < 0
        assert r.option_pnl_share is None

    def test_open_assigned_position_counts_in_attribution(self):
        """Regression: NVDA finished holding shares assigned at 177.50 whose

        ~$2,000 gain was inside final_equity but absent from attribution, so the
        report totalled $1,009 against a headline of $3,018 and claimed "100%
        from the option leg" for a result that was two-thirds long stock.
        """
        days = [D(2025, 1, 6), D(2025, 1, 7)]
        ledger = [
            _ev(days[0], "sell_put_open", symbol="P1", contracts=1,
                cash_delta=1000.0, detail={"collateral": 17750.0}),
            _ev(days[0], "put_assignment", symbol="P1", contracts=1,
                shares=100, price=177.50, cash_delta=-17750.0),
        ]
        held = {days[0]: {"XYZ": 100}, days[1]: {"XYZ": 100}}
        # Final close 197.50 -> 100 shares * $20 = $2,000 unrealized.
        prices = {days[0]: 177.50, days[1]: 197.50}
        states = _states(days, [100_000.0, 103_000.0], shares=held)
        r = compute_fitness("XYZ", states, build_cycles(ledger), 100_000.0,
                            benchmark_prices=prices)

        assert r.unrealized_stock_pnl == pytest.approx(2000.0)
        assert r.total_stock_pnl == pytest.approx(2000.0)
        assert r.attribution_total == pytest.approx(3000.0)
        # And the share is now honest: option leg is the minority.
        # Was 100% before the fix; now honestly a minority of the result.
        assert r.option_pnl_share == pytest.approx(1000.0 / 3000.0)

    def test_attribution_reconciles_with_the_equity_change(self):
        days = [D(2025, 1, 6), D(2025, 1, 7)]
        ledger = [
            _ev(days[0], "sell_put_open", symbol="P1", contracts=1,
                cash_delta=1000.0, detail={"collateral": 17750.0}),
            _ev(days[0], "put_assignment", symbol="P1", contracts=1,
                shares=100, price=177.50, cash_delta=-17750.0),
        ]
        held = {d: {"XYZ": 100} for d in days}
        prices = {days[0]: 177.50, days[1]: 197.50}
        # Equity moved exactly premium + unrealized.
        states = _states(days, [100_000.0, 103_000.0], shares=held)
        r = compute_fitness("XYZ", states, build_cycles(ledger), 100_000.0,
                            benchmark_prices=prices)
        assert r.reconciliation_gap == pytest.approx(0.0, abs=0.01)

    def test_report_flags_a_reconciliation_gap_instead_of_hiding_it(self):
        days = [D(2025, 1, 6), D(2025, 1, 7)]
        ledger = [
            _ev(days[0], "sell_put_open", symbol="P1", contracts=1,
                cash_delta=1000.0, detail={"collateral": 9000.0}),
            _ev(days[1], "expire_worthless", symbol="P1", contracts=1),
        ]
        # Equity claims +5,000 while only 1,000 is attributable.
        r = compute_fitness("XYZ", _states(days, [100_000.0, 105_000.0]),
                            build_cycles(ledger), 100_000.0)
        assert r.reconciliation_gap == pytest.approx(-4000.0)
        md = render_markdown(r)
        assert "Attribution does not reconcile" in md

    def test_assignment_rate_includes_an_open_assigned_cycle(self):
        """0% assignment next to 'days holding shares below basis' is nonsense."""
        days = [D(2025, 1, 6), D(2025, 1, 7)]
        ledger = [
            _ev(days[0], "sell_put_open", symbol="P1", contracts=1,
                cash_delta=100.0, detail={"collateral": 9000.0}),
            _ev(days[0], "put_assignment", symbol="P1", contracts=1,
                shares=100, price=90.0, cash_delta=-9000.0),
        ]
        held = {d: {"XYZ": 100} for d in days}
        r = compute_fitness("XYZ", _states(days, [100_000, 100_100], shares=held),
                            build_cycles(ledger), 100_000.0)
        assert r.closed_cycles == []
        assert r.assignment_rate == 1.0

    def test_beats_buy_and_hold_is_measured_not_assumed(self):
        prices = {D(2025, 1, 6): 100.0, D(2025, 1, 7): 100.0, D(2025, 1, 8): 90.0}
        r = self._report(benchmark_prices=prices)
        assert r.benchmark is not None
        assert r.benchmark.shares == 1000
        assert r.benchmark.total_return == pytest.approx(-0.10)
        assert r.excess_return == pytest.approx(r.total_return + 0.10)

    def test_max_drawdown_is_peak_to_trough(self):
        days = [D(2025, 1, i) for i in (6, 7, 8, 9)]
        ledger = [_ev(days[0], "sell_put_open", symbol="P1", contracts=1,
                      cash_delta=0.0, detail={"collateral": 1.0}),
                  _ev(days[-1], "expire_worthless", symbol="P1", contracts=1)]
        r = compute_fitness("XYZ", _states(days, [100.0, 120.0, 90.0, 110.0]),
                            build_cycles(ledger), 100.0)
        assert r.max_drawdown == pytest.approx(-0.25)  # 120 -> 90

    def test_verdict_blocks_when_no_cycle_completed(self):
        days = [D(2025, 1, 6), D(2025, 1, 8)]
        r = compute_fitness("XYZ", _states(days, [100_000, 100_000]), [], 100_000.0)
        assert r.verdict() == "unfit"
        assert any("no completed wheel cycle" in x for x in r.verdict_reasons())

    def test_verdict_blocks_on_a_loss(self):
        r = self._report(equities=(100_000, 99_000, 98_000))
        assert r.verdict() == "unfit"
        assert any(x.startswith("BLOCK") and "lost money" in x
                   for x in r.verdict_reasons())

    def test_verdict_warns_when_premium_is_a_minority_of_pnl(self):
        """The flagship caveat: mostly-stock returns must be called out."""
        days = [D(2025, 1, 6), D(2025, 1, 8)]
        ledger = [
            _ev(days[0], "sell_put_open", symbol="P1", contracts=1,
                cash_delta=100.0, detail={"collateral": 9000.0}),
            _ev(days[0], "put_assignment", symbol="P1", contracts=1,
                shares=100, price=90.0, cash_delta=-9000.0),
            _ev(days[1], "call_assignment", symbol="C1", contracts=1,
                shares=100, price=110.0, cash_delta=11000.0),
        ]
        r = compute_fitness("XYZ", _states(days, [100_000, 102_100]),
                            build_cycles(ledger), 100_000.0)
        assert r.option_pnl_share < 0.25
        assert any("mostly a long-stock position" in x for x in r.verdict_reasons())

    def test_days_underwater_counts_only_days_held_below_basis(self):
        days = [D(2025, 1, 6), D(2025, 1, 7), D(2025, 1, 8), D(2025, 1, 9)]
        ledger = [
            _ev(days[0], "sell_put_open", symbol="P1", contracts=1,
                cash_delta=100.0, detail={"collateral": 9000.0}),
            _ev(days[0], "put_assignment", symbol="P1", contracts=1,
                shares=100, price=90.0, cash_delta=-9000.0),
            _ev(days[3], "call_assignment", symbol="C1", contracts=1,
                shares=100, price=95.0, cash_delta=9500.0),
        ]
        held = {d: {"XYZ": 100} for d in days[:3]}
        held[days[3]] = {"XYZ": 0}
        states = _states(days, [100_000] * 4, shares=held)
        # Below the $90 basis on the 7th and 8th only.
        prices = {days[0]: 92.0, days[1]: 85.0, days[2]: 88.0, days[3]: 95.0}
        r = compute_fitness("XYZ", states, build_cycles(ledger), 100_000.0,
                            benchmark_prices=prices)
        assert r.days_underwater == 2

    def test_days_underwater_does_not_double_count_across_symbols(self):
        """Regression: keying by day alone let one symbol's basis clobber another's."""
        days = [D(2025, 1, 6), D(2025, 1, 7)]
        ledger = [
            _ev(days[0], "sell_put_open", "AAA", "A1", contracts=1,
                cash_delta=10.0, detail={"collateral": 9000.0}),
            _ev(days[0], "put_assignment", "AAA", "A1", contracts=1,
                shares=100, price=90.0, cash_delta=-9000.0),
            _ev(days[0], "sell_put_open", "BBB", "B1", contracts=1,
                cash_delta=10.0, detail={"collateral": 5000.0}),
            _ev(days[0], "put_assignment", "BBB", "B1", contracts=1,
                shares=100, price=50.0, cash_delta=-5000.0),
        ]
        held = {d: {"AAA": 100, "BBB": 100} for d in days}
        states = _states(days, [100_000, 100_000], shares=held)
        prices = {days[0]: 40.0, days[1]: 40.0}  # below BOTH bases
        r = compute_fitness("AAA", states, build_cycles(ledger), 100_000.0,
                            benchmark_prices=prices)
        # Two underlyings underwater on two days = 4 (symbol, day) pairs,
        # not 2 collapsed by date.
        assert r.days_underwater == 4

    def test_untradeable_symbol_is_unfit_not_marginal(self):
        """KMI's real shape: one 8-day cycle in 273 days, +138% annualized on it.

        Scoring that as 'marginal' would flatter a symbol the strategy simply
        cannot trade. Low utilization must block the verdict outright.
        """
        # 20 decision days, in a position for 2 of them (10%) — KMI's real
        # shape was 8 of 273 (3%).
        days = [D(2025, 1, 6) + __import__("datetime").timedelta(days=i) for i in range(20)]
        ledger = [
            _ev(days[0], "sell_put_open", symbol="P1", contracts=1,
                cash_delta=64.0, detail={"collateral": 2700.0}),
            _ev(days[2], "expire_worthless", symbol="P1", contracts=1),
        ]
        states = [
            DailyState(day=d, equity=100_064.0, cash=100_064.0,
                       reserved_collateral=0.0,
                       open_options=(1 if i < 2 else 0), shares_held={})
            for i, d in enumerate(days)
        ]
        r = compute_fitness("KMI", states, build_cycles(ledger), 100_000.0,
                            data_quality={"decision_days": len(days)})
        assert r.days_in_position == 2
        assert r.days_in_position_fraction == pytest.approx(0.10)
        assert r.verdict() == "unfit"
        assert any("cannot consistently trade this symbol" in x
                   for x in r.verdict_reasons())

    def test_a_continuously_traded_symbol_passes_the_activity_gate(self):
        days = [D(2025, 1, i) for i in (6, 7, 8, 9)]
        ledger = [
            _ev(days[0], "sell_put_open", symbol="P1", contracts=1,
                cash_delta=1000.0, detail={"collateral": 9000.0}),
            _ev(days[3], "expire_worthless", symbol="P1", contracts=1),
        ]
        states = [
            DailyState(day=d, equity=100_000.0 + 250 * i, cash=0.0,
                       reserved_collateral=9000.0, open_options=1, shares_held={})
            for i, d in enumerate(days)
        ]
        prices = {d: 100.0 for d in days}
        r = compute_fitness("XYZ", states, build_cycles(ledger), 100_000.0,
                            benchmark_prices=prices,
                            data_quality={"decision_days": len(days)})
        assert r.days_in_position_fraction == 1.0
        assert not any("cannot consistently trade" in x for x in r.verdict_reasons())

    def test_max_drawdown_never_renders_as_negative_zero(self):
        days = [D(2025, 1, 6), D(2025, 1, 7)]
        ledger = [_ev(days[0], "sell_put_open", symbol="P1", contracts=1,
                      cash_delta=1.0, detail={"collateral": 1.0}),
                  _ev(days[1], "expire_worthless", symbol="P1", contracts=1)]
        r = compute_fitness("XYZ", _states(days, [100.0, 100.0]),
                            build_cycles(ledger), 100.0)
        assert r.max_drawdown == 0.0
        assert f"{r.max_drawdown:.2%}" == "0.00%"

    def test_sub_risk_free_result_is_blocked_even_if_it_beat_buy_and_hold(self):
        """A relative gate alone let +2.46%/yr read FIT because B&H did worse.

        Beating buy-and-hold over a short window is close to a coin flip; without
        an absolute floor the verdict selects on noise.
        """
        days = [D(2025, 1, 6) + __import__("datetime").timedelta(days=i) for i in range(40)]
        ledger = [
            _ev(days[0], "sell_put_open", symbol="P1", contracts=1,
                cash_delta=20.0, detail={"collateral": 9000.0}),
            _ev(days[-1], "expire_worthless", symbol="P1", contracts=1),
        ]
        states = [
            DailyState(day=d, equity=100_000.0 + 20.0, cash=91_020.0,
                       reserved_collateral=9000.0, open_options=1, shares_held={})
            for d in days
        ]
        prices = {d: 100.0 for d in days}
        prices[days[-1]] = 90.0  # buy-and-hold loses, so the relative gate passes
        r = compute_fitness("XYZ", states, build_cycles(ledger), 100_000.0,
                            benchmark_prices=prices,
                            data_quality={"decision_days": len(days)})
        assert r.excess_return > 0, "should have beaten buy-and-hold"
        aroc = r.annualized_return_on_collateral
        assert aroc is not None and aroc < 0.04
        assert r.verdict() == "unfit"
        assert any("risk-free rate" in x for x in r.verdict_reasons())

    def test_return_on_collateral_is_not_diluted_by_idle_cash(self):
        """The account figure is dominated by the arbitrary starting-cash choice."""
        days = [D(2025, 1, 6) + __import__("datetime").timedelta(days=i) for i in range(365)]
        ledger = [
            _ev(days[0], "sell_put_open", symbol="P1", contracts=1,
                cash_delta=900.0, detail={"collateral": 9000.0}),
            _ev(days[-1], "expire_worthless", symbol="P1", contracts=1),
        ]
        states = [
            DailyState(day=d, equity=100_900.0, cash=91_900.0,
                       reserved_collateral=9000.0, open_options=1, shares_held={})
            for d in days
        ]
        r = compute_fitness("XYZ", states, build_cycles(ledger), 100_000.0,
                            data_quality={"decision_days": len(days)})
        assert r.total_return == pytest.approx(0.009)          # 0.9% on the account
        assert r.return_on_collateral == pytest.approx(0.10)   # 10% on capital at risk
        assert r.avg_collateral == pytest.approx(9000.0)

    def test_win_rate_needs_closed_cycles(self):
        days = [D(2025, 1, 6), D(2025, 1, 8)]
        r = compute_fitness("XYZ", _states(days, [100_000, 100_000]), [], 100_000.0)
        assert r.win_rate is None and r.assignment_rate is None

    def test_empty_equity_curve_refuses_rather_than_reporting_zeros(self):
        with pytest.raises(ValueError, match="empty equity curve"):
            compute_fitness("XYZ", [], [], 100_000.0)


# --------------------------------------------------------------------------- #
# Report rendering
# --------------------------------------------------------------------------- #
class TestReport:
    def _report(self):
        days = [D(2025, 1, 6), D(2025, 1, 7), D(2025, 1, 8)]
        ledger = [
            _ev(days[0], "sell_put_open", symbol="P1", contracts=1,
                cash_delta=1000.0, detail={"collateral": 9000.0}),
            _ev(days[-1], "expire_worthless", symbol="P1", contracts=1),
        ]
        prices = {d: 100.0 for d in days}
        return compute_fitness("XYZ", _states(days, [100_000, 100_500, 101_000]),
                               build_cycles(ledger), 100_000.0,
                               benchmark_prices=prices)

    def test_markdown_shows_both_legs_and_the_benchmark(self):
        md = render_markdown(self._report())
        assert "Option premium" in md
        assert "Stock — realized" in md and "Stock — unrealized" in md
        assert "Buy & hold" in md
        assert "Attribution" in md

    def test_markdown_always_carries_the_bias_footer(self):
        """An unlisted caveat is one the reader assumes does not exist."""
        md = render_markdown(self._report())
        assert "Known biases" in md
        assert "Premium understated" in md
        assert "Bid/ask is modeled" in md
        assert "Taxes not modeled" in md

    def test_json_round_trips_and_matches_the_markdown_numbers(self):
        import json

        r = self._report()
        payload = json.loads(render_json(r))
        assert payload["symbol"] == "XYZ"
        assert payload["verdict"] == r.verdict()
        assert payload["attribution"]["option_pnl"] == pytest.approx(r.option_pnl)
        assert payload["benchmark"]["total_return"] == pytest.approx(
            r.benchmark.total_return)
        assert len(payload["cycles"]["table"]) == len(r.cycles)
        assert payload["known_biases"]

    def test_json_is_serializable_with_an_open_cycle(self):
        import json

        days = [D(2025, 1, 6), D(2025, 1, 8)]
        ledger = [
            _ev(days[0], "sell_put_open", symbol="P1", contracts=1,
                cash_delta=100.0, detail={"collateral": 9000.0}),
            _ev(days[0], "put_assignment", symbol="P1", contracts=1,
                shares=100, price=90.0, cash_delta=-9000.0),
        ]
        r = compute_fitness("XYZ", _states(days, [100_000, 100_100]),
                            build_cycles(ledger), 100_000.0)
        payload = json.loads(render_json(r))
        assert payload["cycles"]["open"] == 1
        assert payload["cycles"]["table"][0]["end"] is None
