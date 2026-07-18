"""Point-in-time earnings calendar + rolling wiring (FC-032 Phase 3).

The earnings gate is small in blast radius (it blocks Friday rolls within
``rolling_earnings_blackout_days``) but it is a place where a replay can quietly
become more permissive than production, so it gets the same treatment as the
other seams: answer from the frozen clock, or refuse.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from unittest.mock import Mock

import pytest

from src.backtesting.engine.historical_earnings import (
    EARNINGS_TABLE_PATH,
    HistoricalEarningsCalendar,
)
from src.strategy.wheel_engine import WheelEngine
from src.strategy.wheel_state_manager import WheelStateManager
from src.utils import clock


def _at(day: date):
    return clock.frozen(datetime.combine(day, time(16, 0)))


CAL = {"XYZ": [date(2025, 2, 20), date(2025, 5, 21), date(2025, 8, 27)]}


class TestPointInTime:
    def test_next_earnings_is_relative_to_the_simulated_date(self):
        cal = HistoricalEarningsCalendar(CAL)
        with _at(date(2025, 1, 10)):
            assert cal.next_earnings_date("XYZ") == date(2025, 2, 20)
        with _at(date(2025, 3, 1)):
            assert cal.next_earnings_date("XYZ") == date(2025, 5, 21)
        with _at(date(2025, 9, 1)):
            assert cal.next_earnings_date("XYZ") is None  # past the table

    def test_earnings_on_the_simulated_day_counts_as_today(self):
        cal = HistoricalEarningsCalendar(CAL)
        with _at(date(2025, 2, 20)):
            assert cal.next_earnings_date("XYZ") == date(2025, 2, 20)
            assert cal.get_earnings_proximity("XYZ")["days_until"] == 0

    def test_blackout_window_is_inclusive_of_both_ends(self):
        cal = HistoricalEarningsCalendar(CAL)
        # Blackout of 2 days: 18th is 2 days out -> blocked; 17th is 3 -> clear.
        with _at(date(2025, 2, 18)):
            assert cal.is_earnings_within_n_days("XYZ", 2) is True
        with _at(date(2025, 2, 17)):
            assert cal.is_earnings_within_n_days("XYZ", 2) is False
        with _at(date(2025, 2, 20)):
            assert cal.is_earnings_within_n_days("XYZ", 2) is True

    def test_unknown_symbol_fails_open_like_the_live_service(self):
        cal = HistoricalEarningsCalendar(CAL)
        with _at(date(2025, 2, 18)):
            assert cal.is_earnings_within_n_days("NOPE", 2) is False
        assert "NOPE" in cal.symbols_without_data

    def test_etf_with_no_earnings_is_known_not_missing(self):
        """An empty list is a real answer; it must not be reported as missing data."""
        cal = HistoricalEarningsCalendar({"SPY": []})
        with _at(date(2025, 2, 18)):
            assert cal.is_earnings_within_n_days("SPY", 2) is False
        assert "SPY" not in cal.symbols_without_data

    def test_refuses_to_answer_without_a_frozen_clock(self):
        cal = HistoricalEarningsCalendar(CAL)
        assert not clock.is_frozen()
        with pytest.raises(RuntimeError, match="frozen clock"):
            cal.next_earnings_date("XYZ")

    def test_proximity_dict_matches_the_live_services_keys(self):
        cal = HistoricalEarningsCalendar(CAL)
        with _at(date(2025, 2, 18)):
            got = cal.get_earnings_proximity("XYZ")
        assert set(got) == {"next_earnings_date", "days_until", "earnings_hour"}
        assert got["next_earnings_date"] == "2025-02-20"
        assert got["days_until"] == 2


class TestCommittedTable:
    def test_table_loads_and_covers_the_traded_universe(self):
        cal = HistoricalEarningsCalendar.from_table()
        traded = ["NVDA", "AMD", "AMZN", "GOOGL", "UNH", "AAPL", "MSFT", "IWM"]
        for symbol in traded:
            assert symbol in cal._earnings, f"{symbol} missing from the earnings table"

    def test_table_spans_the_alpaca_options_window(self):
        with open(EARNINGS_TABLE_PATH) as fh:
            payload = json.load(fh)
        nvda = payload["earnings"]["NVDA"]
        assert nvda[0] <= "2024-02-01", "table must start before Alpaca's history floor"
        assert nvda[-1] >= "2026-01-01"

    def test_etfs_are_present_with_empty_lists(self):
        with open(EARNINGS_TABLE_PATH) as fh:
            payload = json.load(fh)
        for etf in ("SPY", "QQQ", "IWM"):
            assert payload["earnings"].get(etf) == [], f"{etf} should be a known ETF"

    def test_known_nvda_earnings_date_is_correct(self):
        """Spot-check against reality: NVDA reported 2025-02-26."""
        cal = HistoricalEarningsCalendar.from_table()
        with _at(date(2025, 2, 1)):
            assert cal.next_earnings_date("NVDA") == date(2025, 2, 26)


class TestRollingSeam:
    def test_injected_calendar_is_used_by_the_rolling_cycle(self):
        sentinel = Mock(name="HistoricalEarningsCalendar")
        engine = WheelEngine(Mock(), alpaca_client=Mock(),
                             wheel_state=WheelStateManager(),
                             earnings_calendar=sentinel)
        assert engine._injected_earnings_calendar is sentinel

    def test_default_still_constructs_the_live_service(self, monkeypatch):
        built = {}

        class _FakeService:
            def __init__(self, config):
                built["config"] = config

        monkeypatch.setattr("src.strategy.wheel_engine.EarningsCalendarService", _FakeService)
        config = Mock()
        config.rolling_enabled = True
        config.earnings_enabled = True
        config.state_storage_bucket = None
        engine = WheelEngine(config, alpaca_client=Mock(),
                             wheel_state=WheelStateManager())
        assert engine._injected_earnings_calendar is None
        # The live service is constructed lazily inside the roll cycle.
        engine.alpaca.get_positions.return_value = []
        engine.run_rolling_cycle()
        assert built.get("config") is config
