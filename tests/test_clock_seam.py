"""The clock seam (FC-032 Phase 3).

Two things must hold for the backtest to replay live strategy code faithfully:

1. Freezing ``clock.now()`` actually changes the decisions live code makes.
   A seam that production ignores is worthless — the backtest would silently
   evaluate against wall-clock time while claiming to replay history.
2. In production the seam is invisible: ``clock.now()`` is the wall clock.

The guard test at the bottom keeps ``datetime.now()`` from creeping back into
the modules whose decisions depend on time.
"""

from __future__ import annotations

import pathlib
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from src.strategy.put_seller import PutSeller
from src.utils import clock
from src.utils.config import Config
from src.utils.option_symbols import parse_option_symbol


class TestClockDrivesLiveDecisions:
    """The min-hold gate in should_close_put_early() must read simulated time.

    A real Config is used deliberately. With a Mock, _get_profit_target_for_dte
    returns a Mock, the `profit_percentage >= profit_target` comparison raises
    TypeError, and the method's blanket `except` swallows it into False — so a
    Mock-config test would "pass" the blocked branch for entirely the wrong
    reason and could never exercise the released branch at all.
    """

    # Entry, and an expiry 4 calendar days later so the DTE band is well defined.
    ENTRY = datetime(2024, 6, 3, 10, 0)
    # 90% profit: past every DTE-band target (dte 4 -> 0.45).
    POSITION = {
        "symbol": "XYZ240607P00090000",
        "unrealized_pl": 90.0,
        "market_value": -100.0,
    }

    def _put_seller(self) -> PutSeller:
        ps = PutSeller(Mock(), Mock(), Config())
        ps._entry_times[self.POSITION["symbol"]] = self.ENTRY
        return ps

    def test_dte_itself_is_computed_from_simulated_time(self):
        """parse_option_symbol drives the profit target; it must honor the freeze."""
        with clock.frozen(self.ENTRY):
            assert parse_option_symbol(self.POSITION["symbol"])["dte"] == 4
        with clock.frozen(self.ENTRY + timedelta(days=3)):
            assert parse_option_symbol(self.POSITION["symbol"])["dte"] == 1

    def test_min_hold_gate_blocks_when_simulated_time_is_too_soon(self):
        ps = self._put_seller()
        assert ps.config.profit_taking_min_hold_hours == 4
        # Two simulated hours after entry: under the 4h floor -> must not close,
        # no matter how profitable, and no matter what the wall clock says.
        with clock.frozen(self.ENTRY + timedelta(hours=2)):
            assert ps.should_close_put_early(dict(self.POSITION)) is False

    def test_min_hold_gate_releases_once_simulated_time_advances(self):
        ps = self._put_seller()
        # Ten simulated hours after entry: the hold gate no longer blocks, and a
        # 90% gain clears the DTE-band target.
        with clock.frozen(self.ENTRY + timedelta(hours=10)):
            assert ps.should_close_put_early(dict(self.POSITION)) is True

    def test_the_two_branches_differ_only_by_the_frozen_clock(self):
        """Same seller, same position, same wall clock — only sim time differs.

        This is the property the whole replay rests on.
        """
        ps = self._put_seller()
        with clock.frozen(self.ENTRY + timedelta(hours=1)):
            early = ps.should_close_put_early(dict(self.POSITION))
        with clock.frozen(self.ENTRY + timedelta(hours=9)):
            late = ps.should_close_put_early(dict(self.POSITION))
        assert (early, late) == (False, True)


class TestSeamIsInvisibleInProduction:
    def test_clock_now_is_the_wall_clock_when_unfrozen(self):
        assert not clock.is_frozen()
        before = datetime.now()
        got = clock.now()
        after = datetime.now()
        assert before <= got <= after

    def test_now_utc_is_the_aware_wall_clock_when_unfrozen(self):
        assert not clock.is_frozen()
        before = datetime.now(timezone.utc)
        got = clock.now_utc()
        after = datetime.now(timezone.utc)
        assert got.tzinfo is not None
        assert before <= got <= after

    def test_now_utc_stamps_a_naive_freeze_rather_than_converting_it(self):
        """Converting would shift the simulated calendar date, and with it every DTE."""
        naive = datetime(2024, 6, 3, 23, 30)
        with clock.frozen(naive):
            got = clock.now_utc()
        assert got.tzinfo is timezone.utc
        assert got.date() == naive.date()  # same simulated day, not dragged forward
        assert got.hour == naive.hour

    def test_freeze_is_restored_on_exit(self):
        assert not clock.is_frozen()
        with clock.frozen(datetime(2024, 1, 1)):
            assert clock.is_frozen()
        assert not clock.is_frozen()


class TestNoDirectWallClockReads:
    """Regression guard: decisions must not bypass the seam.

    src/api/alpaca_client.py and src/api/earnings_calendar.py are deliberately
    excluded — their datetime.now() calls answer "what will the API serve me
    right now" and "how stale is this cache entry", which are wall-clock
    questions independent of simulated time. Same reasoning as the
    entitlement clamp in src/backtesting/data/alpaca_provider.py.
    """

    SEAMED = [
        "src/strategy/put_seller.py",
        "src/strategy/call_seller.py",
        "src/strategy/call_roller.py",
        "src/strategy/wheel_engine.py",
        "src/api/market_data.py",
        "src/risk/risk_manager.py",
        # DTE lives here, and DTE drives every dynamic profit target.
        "src/utils/option_symbols.py",
    ]

    def test_no_wall_clock_reads_in_seamed_modules(self):
        offenders = []
        # Catches datetime.now(), datetime.now(timezone.utc) and datetime.utcnow().
        pattern = re.compile(r"\bdatetime\.now\(|\bdatetime\.utcnow\(")
        for rel in self.SEAMED:
            src = pathlib.Path(rel).read_text()
            for lineno, line in enumerate(src.splitlines(), start=1):
                if pattern.search(line):
                    offenders.append(f"{rel}:{lineno}: {line.strip()}")
        assert not offenders, (
            "these modules must call clock.now()/clock.now_utc() so a backtest "
            "can freeze time:\n" + "\n".join(offenders)
        )
