"""Unit tests for GapDetector's execution gap gate (Stage 4).

FC-036: `_get_previous_close` compared `df.index < current_time`. Alpaca stamps
daily bars at midnight ET (04:00 UTC EDT / 05:00 UTC EST), so at any intraday
decision time the session's OWN partial bar satisfies that filter and gets
returned as "previous close". The gate then compared a live quote against
today's own partial bar — measuring ~20 minutes of pre-market drift rather than
the overnight gap. It did not read as 0.0%, which is why it looked healthy.

GapDetector had no unit tests before this file; that is why the bug survived.
"""

import pandas as pd
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock

from src.risk.gap_detector import GapDetector
from src.utils.config import Config


def _frame(rows):
    """Build a daily-bar frame stamped like Alpaca's (midnight ET).

    rows: list of (iso_timestamp, close) — open/high/low derived from close.
    """
    idx = pd.DatetimeIndex([pd.Timestamp(ts) for ts, _ in rows])
    closes = [c for _, c in rows]
    return pd.DataFrame(
        {
            'open': closes,
            'high': [c * 1.01 for c in closes],
            'low': [c * 0.99 for c in closes],
            'close': closes,
            'volume': [1_000_000] * len(closes),
        },
        index=idx,
    )


def _detector(df=None, quote=None, threshold=1.5):
    config = Mock(spec=Config)
    config.execution_gap_threshold = threshold   # PERCENT units, as settings.yaml
    config.premarket_gap_threshold = 2.0
    config.gap_lookback_days = 30
    alpaca = Mock()
    if df is not None:
        alpaca.get_stock_bars.return_value = df
    if quote is not None:
        alpaca.get_stock_quote.return_value = quote
    return GapDetector(config, alpaca), alpaca


class TestPreviousCloseExcludesTodaysBar:
    """The FC-036 regression: today's own bar must never be 'previous close'."""

    def test_edt_midnight_stamp_returns_yesterday(self):
        # 04:00 UTC stamps = midnight ET under EDT.
        df = _frame([
            ("2026-07-27 04:00:00+00:00", 196.51),
            ("2026-07-28 04:00:00+00:00", 197.01),   # today's own (partial) bar
        ])
        gd, _ = _detector(df)
        decision = datetime(2026, 7, 28, 13, 35, tzinfo=timezone.utc)  # 9:35 ET

        assert gd._get_previous_close("NVDA", decision) == 196.51, \
            "must return the PRIOR session's close, not today's own bar"

    def test_est_midnight_stamp_returns_yesterday(self):
        # 05:00 UTC stamps = midnight ET under EST.
        df = _frame([
            ("2026-01-14 05:00:00+00:00", 150.00),
            ("2026-01-15 05:00:00+00:00", 158.00),   # today's own bar
        ])
        gd, _ = _detector(df)
        decision = datetime(2026, 1, 15, 14, 35, tzinfo=timezone.utc)  # 9:35 EST

        assert gd._get_previous_close("NVDA", decision) == 150.00

    def test_naive_decision_time_is_supported(self):
        """Production passes clock.now() (naive, UTC on Cloud Run)."""
        df = _frame([
            ("2026-07-27 04:00:00+00:00", 196.51),
            ("2026-07-28 04:00:00+00:00", 197.01),
        ])
        gd, _ = _detector(df)

        assert gd._get_previous_close("NVDA", datetime(2026, 7, 28, 13, 35)) == 196.51


class TestDstBoundaries:
    def test_november_edt_to_est(self):
        # Fri stamped 04:00 (EDT), Mon stamped 05:00 (EST) after the transition.
        df = _frame([
            ("2026-10-30 04:00:00+00:00", 100.00),   # Friday
            ("2026-11-02 05:00:00+00:00", 104.00),   # Monday, own bar
        ])
        gd, _ = _detector(df)
        decision = datetime(2026, 11, 2, 14, 35, tzinfo=timezone.utc)  # 9:35 EST

        assert gd._get_previous_close("NVDA", decision) == 100.00

    def test_march_est_to_edt(self):
        df = _frame([
            ("2026-03-06 05:00:00+00:00", 100.00),   # Friday, EST
            ("2026-03-09 04:00:00+00:00", 104.00),   # Monday, EDT, own bar
        ])
        gd, _ = _detector(df)
        decision = datetime(2026, 3, 9, 13, 35, tzinfo=timezone.utc)  # 9:35 EDT

        assert gd._get_previous_close("NVDA", decision) == 100.00


class TestCalendarEdges:
    def test_long_weekend_returns_friday(self):
        """Tuesday after a Monday holiday: no Monday bar exists."""
        df = _frame([
            ("2026-05-21 04:00:00+00:00", 90.00),    # Thursday
            ("2026-05-22 04:00:00+00:00", 91.00),    # Friday
            ("2026-05-26 04:00:00+00:00", 95.00),    # Tuesday, own bar (Mon = holiday)
        ])
        gd, _ = _detector(df)
        decision = datetime(2026, 5, 26, 13, 35, tzinfo=timezone.utc)

        assert gd._get_previous_close("NVDA", decision) == 91.00, \
            "must be the last TRADING day, not the previous calendar day"

    def test_post_close_returns_completed_session(self):
        """After the close, the most recent completed session is 'previous'."""
        df = _frame([
            ("2026-07-27 04:00:00+00:00", 196.51),
            ("2026-07-28 04:00:00+00:00", 197.01),
        ])
        gd, _ = _detector(df)
        # 21:00 ET on the 28th == 01:00 UTC on the 29th.
        decision = datetime(2026, 7, 29, 1, 0, tzinfo=timezone.utc)

        assert gd._get_previous_close("NVDA", decision) == 197.01


class TestFailsClosedOnMissingData:
    def test_only_todays_bar_returns_none(self):
        df = _frame([("2026-07-28 04:00:00+00:00", 197.01)])
        gd, _ = _detector(df)
        decision = datetime(2026, 7, 28, 13, 35, tzinfo=timezone.utc)

        assert gd._get_previous_close("NVDA", decision) is None

    def test_empty_frame_returns_none(self):
        gd, _ = _detector(pd.DataFrame())
        assert gd._get_previous_close(
            "NVDA", datetime(2026, 7, 28, 13, 35, tzinfo=timezone.utc)) is None

    def test_client_exception_returns_none_without_raising(self):
        gd, alpaca = _detector()
        alpaca.get_stock_bars.side_effect = Exception("Alpaca 503")

        assert gd._get_previous_close(
            "NVDA", datetime(2026, 7, 28, 13, 35, tzinfo=timezone.utc)) is None

    def test_can_execute_trade_blocks_when_previous_close_missing(self):
        df = _frame([("2026-07-28 04:00:00+00:00", 197.01)])   # today only
        gd, _ = _detector(df, quote={'bid': 197.0, 'ask': 197.1})
        result = gd.can_execute_trade(
            "NVDA", datetime(2026, 7, 28, 13, 35, tzinfo=timezone.utc))

        assert result['can_execute'] is False
        assert result['reason'] == 'no_previous_close_data'


class TestGateBehaviorInPercentUnits:
    """Threshold is PERCENT (settings.yaml uses 1.5 == 1.5%), not a fraction."""

    def _setup(self, quote_mid, threshold=1.5):
        df = _frame([
            ("2026-07-27 04:00:00+00:00", 100.00),
            ("2026-07-28 04:00:00+00:00", 100.00),
        ])
        gd, _ = _detector(
            df, quote={'bid': quote_mid - 0.01, 'ask': quote_mid + 0.01},
            threshold=threshold)
        return gd.can_execute_trade(
            "NVDA", datetime(2026, 7, 28, 13, 35, tzinfo=timezone.utc))

    def test_two_percent_gap_blocks(self):
        result = self._setup(102.00)
        assert result['can_execute'] is False
        assert result['reason'] == 'execution_gap_exceeded'
        assert result['current_gap_percent'] == pytest.approx(2.0, abs=0.01)

    def test_one_percent_gap_passes(self):
        result = self._setup(101.00)
        assert result['can_execute'] is True
        assert result['current_gap_percent'] == pytest.approx(1.0, abs=0.01)

    def test_gap_measured_against_prior_close_not_todays_bar(self):
        """The whole point of FC-036: a real overnight gap is now visible.

        Today's own bar sits at 102 (a 2% gap up from yesterday's 100). Before
        the fix, previous_close resolved to 102 and the gap read ~0%; now it
        resolves to 100 and the true 2% gap is measured.
        """
        df = _frame([
            ("2026-07-27 04:00:00+00:00", 100.00),
            ("2026-07-28 04:00:00+00:00", 102.00),   # gapped-up session
        ])
        gd, _ = _detector(df, quote={'bid': 101.99, 'ask': 102.01})
        result = gd.can_execute_trade(
            "NVDA", datetime(2026, 7, 28, 13, 35, tzinfo=timezone.utc))

        assert result['current_gap_percent'] == pytest.approx(2.0, abs=0.01)
        assert result['can_execute'] is False

    def test_shadow_threshold_never_blocks(self):
        """Phase A safety property: at 999 the fixed gate blocks nothing."""
        result = self._setup(150.00, threshold=999)   # a 50% gap
        assert result['can_execute'] is True


class TestDegenerateQuoteIsBlocked:
    """FC-036 review finding: at threshold 999 nothing else catches a bad quote.

    A zero/one-sided IEX quote (routine on a halted or LULD symbol) makes the
    midpoint ~half of fair value, i.e. a fabricated 50-100% "gap". The armed
    gate blocked that only as an accident of the 1.5 threshold; during Phase A
    shadow it would pass and we would sell into a halted market.
    """

    def _result(self, bid, ask, threshold=999):
        df = _frame([
            ("2026-07-27 04:00:00+00:00", 100.00),
            ("2026-07-28 04:00:00+00:00", 100.00),
        ])
        gd, _ = _detector(df, quote={'bid': bid, 'ask': ask}, threshold=threshold)
        return gd.can_execute_trade(
            "NVDA", datetime(2026, 7, 28, 13, 35, tzinfo=timezone.utc))

    def test_zero_bid_blocks_even_in_shadow(self):
        result = self._result(0.0, 100.05)
        assert result['can_execute'] is False
        assert result['reason'] == 'bad_quote'

    def test_zero_ask_blocks_even_in_shadow(self):
        assert self._result(99.95, 0.0)['can_execute'] is False

    def test_both_sides_zero_blocks(self):
        assert self._result(0.0, 0.0)['can_execute'] is False

    def test_missing_keys_block(self):
        gd, _ = _detector(
            _frame([("2026-07-27 04:00:00+00:00", 100.0),
                    ("2026-07-28 04:00:00+00:00", 100.0)]),
            quote={}, threshold=999)
        assert gd.can_execute_trade(
            "NVDA", datetime(2026, 7, 28, 13, 35, tzinfo=timezone.utc)
        )['can_execute'] is False

    def test_healthy_quote_still_passes_in_shadow(self):
        assert self._result(99.95, 100.05)['can_execute'] is True


class TestTimezoneFrameSafety:
    """Taking .date() in the CALLER's frame reintroduces the FC-036 bug.

    An Asia/Tokyo instant equal to 15:00 ET is already 'tomorrow' in Tokyo, so
    a caller-frame date would let the session's own bar back in.
    """

    def test_tz_east_of_utc_still_excludes_todays_bar(self):
        import pytz

        df = _frame([
            ("2026-07-27 04:00:00+00:00", 196.51),
            ("2026-07-28 04:00:00+00:00", 197.01),   # today's own bar
        ])
        gd, _ = _detector(df)
        # 15:00 ET on 2026-07-28 == 04:00 JST on 2026-07-29.
        tokyo = pytz.timezone("Asia/Tokyo")
        decision = tokyo.localize(datetime(2026, 7, 29, 4, 0))

        assert gd._get_previous_close("NVDA", decision) == 196.51, \
            "caller-frame date would return 197.01 — the original bug"


class TestStage2Untouched:
    """Sentinel: the working control (_detect_current_gap) must not drift."""

    def test_detect_current_gap_unchanged(self):
        df = _frame([
            ("2026-07-27 04:00:00+00:00", 100.00),
            ("2026-07-28 04:00:00+00:00", 103.00),
        ])
        gd, _ = _detector(df)
        result = gd._detect_current_gap(
            "NVDA", datetime(2026, 7, 28, 13, 35, tzinfo=timezone.utc), df)

        assert bool(result['has_gap']) is True     # 3% open vs 2.0 threshold
        assert result['gap_percent'] == pytest.approx(3.0, abs=0.01)
        assert result['gap_direction'] == 'up'
        assert result['previous_close'] == 100.00
