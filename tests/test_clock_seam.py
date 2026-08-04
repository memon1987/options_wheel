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
import pytest
from unittest.mock import Mock

from src.strategy.put_seller import PutSeller
from src.utils import clock
from src.utils.config import Config
from src.utils.option_symbols import parse_option_symbol


class TestClockDrivesLiveDecisions:
    """`should_close_put_early()` must decide from *simulated* time.

    FC-069 item 6 deleted the min-hold gate that this class originally used as
    its vehicle (it read `_entry_times`, an in-process dict on a per-request
    seller, so it never ran in production). The property under test is
    unchanged and is now pinned on the control that actually carries the hold
    discipline: the DTE-banded profit target. DTE is derived from
    `clock.now()`, so freezing the clock moves the position into a different
    band and flips the close decision.

    A real Config is used deliberately. With a Mock, _get_profit_target_for_dte
    returns a Mock, the `profit_percentage >= profit_target` comparison raises
    TypeError, and the method's blanket `except` swallows it into False — so a
    Mock-config test would "pass" the blocked branch for entirely the wrong
    reason and could never exercise the released branch at all.
    """

    # A reference instant, and an expiry 4 calendar days later.
    ENTRY = datetime(2024, 6, 3, 10, 0)
    # 50% profit. It clears the DTE-4 band target (0.45) but not the DTE-2
    # one (0.60) — so the same position closes or holds purely on sim time.
    POSITION = {
        "symbol": "XYZ240607P00090000",
        "unrealized_pl": 50.0,
        "market_value": -100.0,
    }

    def _put_seller(self) -> PutSeller:
        return PutSeller(Mock(), Mock(), Config())

    def test_dte_itself_is_computed_from_simulated_time(self):
        """parse_option_symbol drives the profit target; it must honor the freeze."""
        with clock.frozen(self.ENTRY):
            assert parse_option_symbol(self.POSITION["symbol"])["dte"] == 4
        with clock.frozen(self.ENTRY + timedelta(days=3)):
            assert parse_option_symbol(self.POSITION["symbol"])["dte"] == 1

    def test_closes_when_simulated_time_puts_it_in_a_looser_band(self):
        ps = self._put_seller()
        # DTE 4 -> target 0.45; a 50% gain clears it.
        with clock.frozen(self.ENTRY):
            assert ps.should_close_put_early(dict(self.POSITION)) is True

    def test_holds_when_simulated_time_puts_it_in_a_tighter_band(self):
        ps = self._put_seller()
        # DTE 2 -> target 0.60; the same 50% gain no longer clears it, no
        # matter what the wall clock says.
        with clock.frozen(self.ENTRY + timedelta(days=2)):
            assert ps.should_close_put_early(dict(self.POSITION)) is False

    def test_the_two_branches_differ_only_by_the_frozen_clock(self):
        """Same seller, same position, same wall clock — only sim time differs.

        This is the property the whole replay rests on.
        """
        ps = self._put_seller()
        with clock.frozen(self.ENTRY):
            early = ps.should_close_put_early(dict(self.POSITION))
        with clock.frozen(self.ENTRY + timedelta(days=2)):
            late = ps.should_close_put_early(dict(self.POSITION))
        assert (early, late) == (True, False)


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


class TestFreezeNeverLeaks:
    """A leaked freeze is the scariest failure mode in this design.

    Reviewers proved the whole suite passed with SimClock's try/finally removed —
    it worked only via CPython generator GC, and conftest's reset fixture masked
    it. These pin the behavior directly.
    """

    def _clock(self):
        from datetime import date

        from src.backtesting.engine.clock import SimClock
        return SimClock([date(2024, 6, 3), date(2024, 6, 4), date(2024, 6, 5)])

    def test_exception_mid_iteration_still_clears_the_freeze(self):
        sim = self._clock()
        with pytest.raises(RuntimeError):
            for _ in sim.steps():
                assert clock.is_frozen()
                raise RuntimeError("strategy blew up mid-replay")
        assert not clock.is_frozen(), "freeze leaked after an exception"

    def test_break_mid_iteration_still_clears_the_freeze(self):
        sim = self._clock()
        for _ in sim.steps():
            assert clock.is_frozen()
            break
        assert not clock.is_frozen(), "freeze leaked after an early break"

    def test_simclock_restores_an_outer_freeze_rather_than_clearing_it(self):
        """SimClock and clock.frozen() must not have opposite semantics."""
        outer = datetime(2030, 1, 1, 12, 0)
        sim = self._clock()
        with clock.frozen(outer):
            for _ in sim.steps():
                pass
            assert clock.is_frozen(), "SimClock dropped the caller's freeze"
            assert clock.now() == outer
        assert not clock.is_frozen()

    def test_freeze_is_not_visible_to_another_thread(self):
        """cloud_run_server runs Flask threaded=True; a backtest freeze in one

        thread must never reach a live trading decision in another.
        """
        import threading

        seen = {}

        def worker():
            seen["frozen"] = clock.is_frozen()

        with clock.frozen(datetime(2024, 6, 3, 16, 0)):
            t = threading.Thread(target=worker)
            t.start()
            t.join()
        assert seen["frozen"] is False, "freeze leaked across threads"
