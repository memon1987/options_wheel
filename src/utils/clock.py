"""Time seam for backtest replay.

Live strategy code decides on the current time for many things: days-to-
expiration, minimum-hold windows, entry timestamps, earnings blackouts. To
replay that code over history, the backtest must be able to make "now" a past
moment. This module is that seam.

In production nothing changes: ``now()`` returns the real wall clock. During a
backtest the simulator freezes ``now()`` to the current simulated timestamp via
``set_now`` (or the ``frozen`` context manager), advances it each simulated day,
and clears it when done.

Kept dead simple and dependency-free on purpose — it is imported by hot live
code paths. The freeze is process-global (a backtest runs single-threaded);
``frozen`` restores the previous value so nesting/cleanup is safe.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

# THREAD-LOCAL, deliberately. The freeze must never be visible to a thread that
# did not set it: deploy/cloud_run_server.py runs Flask with threaded=True, so a
# process-global freeze set by a backtest would corrupt every concurrent live
# decision — DTE, min-hold windows and entry stamps would all be computed
# against the simulated date. Today no in-process backtest entry point exists,
# but "safe because nothing calls it" is a property of the current call graph,
# not of this module. Thread-local makes it safe by construction.
_state = threading.local()


def _get_frozen() -> Optional[datetime]:
    return getattr(_state, "frozen_now", None)


def now() -> datetime:
    """Current time — real wall clock in production, simulated time under a freeze."""
    frozen = _get_frozen()
    return frozen if frozen is not None else datetime.now()


def now_utc() -> datetime:
    """Timezone-aware current time, for callers that compare against aware datetimes.

    Production is unchanged: this is ``datetime.now(timezone.utc)``. Under a
    freeze a naive simulated timestamp is stamped UTC rather than converted, so
    ``now_utc().date()`` is the simulated calendar date — which is what
    day-count logic (DTE) actually wants. Converting instead would drag the
    simulated date across a boundary and silently shift every DTE by a day.
    """
    frozen = _get_frozen()
    if frozen is None:
        return datetime.now(timezone.utc)
    if frozen.tzinfo is None:
        return frozen.replace(tzinfo=timezone.utc)
    return frozen


def set_now(dt: Optional[datetime]) -> None:
    """Freeze ``now()`` to ``dt`` (or clear the freeze with None). Thread-local."""
    _state.frozen_now = dt


def is_frozen() -> bool:
    """True when a simulated time is in effect on THIS thread."""
    return _get_frozen() is not None


@contextmanager
def frozen(dt: datetime):
    """Temporarily freeze ``now()`` to ``dt``, restoring the prior state on exit."""
    prev = _get_frozen()
    _state.frozen_now = dt
    try:
        yield
    finally:
        _state.frozen_now = prev
