"""Simulation clock — drives the time seam across a trading calendar.

The wheel makes one decision per trading day on end-of-day data (FC-032 decision:
EOD cadence). SimClock walks the trading calendar (the dates for which we have
underlying bars) and, on each step, freezes ``src.utils.clock.now()`` to that
day's decision timestamp so the replayed strategy code computes DTE, min-hold,
and blackout windows against simulated time rather than the wall clock.

Decision timestamp defaults to 16:00 on the trading date (near the close, where
EOD chain snapshots are taken). Because the live code uses naive datetimes, the
sim clock is naive too — consistency with live behavior matters more than tz
correctness for day-granular decisions.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Iterator, List, Optional

from ...utils import clock as _clock


class SimClock:
    """Iterates trading days and freezes the global time seam to each."""

    def __init__(self, trading_days: List[date], *, decision_time: time = time(16, 0)) -> None:
        """
        Args:
            trading_days: ascending list of dates the sim will step through
                (typically the dates for which underlying bars exist).
            decision_time: time-of-day used for the frozen decision timestamp.
        """
        self._days = sorted(trading_days)
        self._decision_time = decision_time
        self._idx = -1

    @property
    def current_date(self) -> Optional[date]:
        if 0 <= self._idx < len(self._days):
            return self._days[self._idx]
        return None

    @property
    def current_datetime(self) -> Optional[datetime]:
        d = self.current_date
        return datetime.combine(d, self._decision_time) if d else None

    def __len__(self) -> int:
        return len(self._days)

    def steps(self) -> Iterator[date]:
        """Yield each trading date in turn, freezing the time seam to it.

        Use as ``for day in clock.steps(): ...``. On each iteration the global
        ``now()`` is the decision timestamp for ``day``. The freeze is cleared
        when iteration completes or the loop is exited.
        """
        # Restore the prior value rather than clearing, so SimClock and
        # clock.frozen() have the same semantics; clearing made a SimClock
        # nested inside a frozen block silently drop the outer freeze.
        previous = _clock.now() if _clock.is_frozen() else None
        try:
            for i, d in enumerate(self._days):
                self._idx = i
                _clock.set_now(datetime.combine(d, self._decision_time))
                yield d
        finally:
            self._idx = len(self._days)
            _clock.set_now(previous)
