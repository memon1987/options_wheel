"""Screen mode (FC-032 Phase 5).

Screen output feeds a decision about which symbols keep real capital, so these
tests are about the ways a screening run can quietly mislead: a symbol that
errored looking like a pass, a partial run looking complete, or a demotion
recommendation reading as an action already taken.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from src.backtesting.reporting.bq_writer import build_row, config_hash
from src.backtesting.screen import (
    ScreenResult,
    SymbolResult,
    render_screen_summary,
    run_screen,
)


class _FakeReport:
    """Minimal stand-in for FitnessReport."""

    def __init__(self, symbol="XYZ", verdict="fit", total_return=0.05):
        self.symbol = symbol
        self._verdict = verdict
        self.total_return = total_return
        self.start, self.end = date(2025, 1, 1), date(2025, 12, 31)
        self.starting_cash, self.final_equity = 100_000.0, 105_000.0
        self.annualized_return = 0.05
        self.annualized_return_on_collateral = 0.12
        self.excess_return = 0.01
        self.option_pnl, self.stock_pnl, self.unrealized_stock_pnl = 1000.0, 0.0, 0.0
        self.option_pnl_share, self.reconciliation_gap = 1.0, 0.0
        self.decision_days, self.days_in_position = 250, 200
        self.days_in_position_fraction = 0.8
        self.cycles, self.puts_sold, self.calls_sold = [], 12, 3
        self.win_rate, self.assignment_rate = 0.9, 0.1
        self.max_drawdown, self.days_underwater, self.avg_collateral = -0.03, 4, 9000.0
        self.benchmark = None
        self.data_quality = {"blocked_days_by_reason": {"gap-risk filter (stage 2)": 20}}

    @property
    def closed_cycles(self):
        return []

    def verdict(self):
        return self._verdict

    def verdict_reasons(self):
        return ["OK: profitable"] if self._verdict == "fit" else ["BLOCK: lost money"]


# --------------------------------------------------------------------------- #
class TestFailuresAreNotPasses:
    def test_a_failed_symbol_still_produces_a_row(self):
        """Dropping it makes the run look like it screened fewer symbols."""
        row = build_row(run_id="r1", symbol="BAD", report=None, sensitivity=None,
                        cfg_hash="abc", engine_version="v", error="boom")
        assert row["symbol"] == "BAD"
        assert row["verdict"] is None
        assert row["demote"] is None
        assert "boom" in row["error"]

    def test_a_failed_symbol_is_not_a_demotion_candidate(self):
        r = ScreenResult(run_id="r", start=date(2025, 1, 1), end=date(2025, 12, 31))
        r.results = [SymbolResult("BAD", error="boom"),
                     SymbolResult("UGLY", _FakeReport(verdict="unfit"))]
        assert r.demote_candidates == ["UGLY"]
        assert r.failures == ["BAD"]

    def test_summary_says_failures_were_never_checked(self):
        r = ScreenResult(run_id="r", start=date(2025, 1, 1), end=date(2025, 12, 31))
        r.results = [SymbolResult("BAD", error="boom")]
        md = render_screen_summary(r)
        assert "never checked" in md
        assert "not** implicitly fine" in md

    def test_corporate_action_is_a_skip_not_a_verdict(self):
        """A split in the window says nothing about the symbol's fitness."""
        from src.backtesting.data.alpaca_provider import UnadjustedCorporateAction

        with patch("src.backtesting.screen.evaluate_symbol",
                   side_effect=UnadjustedCorporateAction("NVDA moved 0.101x")):
            result = run_screen(symbols=["NVDA"], persist=False,
                                run_sensitivity=False,
                                start=date(2025, 1, 1), end=date(2025, 6, 30))
        assert result.demote_candidates == []
        assert result.failures == ["NVDA"]
        assert "corporate_action" in result.results[0].error


class TestPartialRunsAreVisible:
    def test_unpersisted_run_is_flagged_in_the_summary(self):
        r = ScreenResult(run_id="r", start=date(2025, 1, 1), end=date(2025, 12, 31))
        r.results = [SymbolResult("XYZ", _FakeReport())]
        r.persisted = False
        md = render_screen_summary(r)
        assert "persisted: **NO**" in md
        assert "were not persisted to BigQuery" in md
        assert "only record of the run" in md

    def test_one_bad_symbol_does_not_kill_the_run(self):
        def _side_effect(symbol, *a, **kw):
            if symbol == "BAD":
                raise RuntimeError("kaboom")
            return _FakeReport(symbol), None

        with patch("src.backtesting.screen.evaluate_symbol", side_effect=_side_effect):
            result = run_screen(symbols=["AAA", "BAD", "CCC"], persist=False,
                                run_sensitivity=False,
                                start=date(2025, 1, 1), end=date(2025, 6, 30))
        assert len(result.results) == 3
        assert result.failures == ["BAD"]
        assert result.tally()["fit"] == 2


class TestDemotionIsARecommendation:
    def test_summary_states_no_action_was_taken(self):
        r = ScreenResult(run_id="r", start=date(2025, 1, 1), end=date(2025, 12, 31))
        r.results = [SymbolResult("UGLY", _FakeReport(verdict="unfit"))]
        md = render_screen_summary(r)
        assert "recommendation for a human" in md
        assert "not an action" in md

    def test_demote_flag_tracks_the_unfit_verdict_only(self):
        for verdict, expected in [("fit", False), ("marginal", False), ("unfit", True)]:
            row = build_row(run_id="r", symbol="X", report=_FakeReport(verdict=verdict),
                            sensitivity=None, cfg_hash="h", engine_version="v")
            assert row["demote"] is expected, verdict


class TestProvenance:
    def test_config_hash_changes_when_a_threshold_changes(self):
        """A verdict is uninterpretable without the config that produced it."""
        class _Cfg:
            put_target_dte = 7
            put_delta_range = [0.10, 0.20]
            min_put_premium = 0.50

        a = _Cfg()
        h1 = config_hash(a)
        a.min_put_premium = 0.25
        h2 = config_hash(a)
        assert h1 != h2
        assert len(h1) == 16

    def test_config_hash_is_stable_for_identical_config(self):
        class _Cfg:
            put_target_dte = 7
            min_put_premium = 0.50

        assert config_hash(_Cfg()) == config_hash(_Cfg())

    def test_row_carries_known_biases(self):
        row = build_row(run_id="r", symbol="X", report=_FakeReport(),
                        sensitivity=None, cfg_hash="h", engine_version="v")
        assert row["known_biases"]
        assert any("Dividends" in b for b in row["known_biases"])

    def test_row_carries_the_binding_constraint(self):
        row = build_row(run_id="r", symbol="X", report=_FakeReport(),
                        sensitivity=None, cfg_hash="h", engine_version="v")
        assert row["binding_constraint"] == "gap-risk filter (stage 2)"

    def test_fill_sensitivity_flip_is_recorded(self):
        row = build_row(run_id="r", symbol="X", report=_FakeReport(),
                        sensitivity={"bid_return": 0.01, "verdict_flips": True},
                        cfg_hash="h", engine_version="v")
        assert row["verdict_flips_on_fill"] is True
        assert row["bid_fill_return"] == 0.01


class TestWindow:
    def test_window_is_clamped_to_alpacas_history_floor(self):
        from src.backtesting.data.alpaca_provider import ALPACA_OPTIONS_HISTORY_START

        with patch("src.backtesting.screen.evaluate_symbol",
                   return_value=(_FakeReport(), None)):
            result = run_screen(symbols=["XYZ"], persist=False, run_sensitivity=False,
                                start=date(2020, 1, 1), end=date(2025, 6, 30))
        assert result.start == ALPACA_OPTIONS_HISTORY_START
