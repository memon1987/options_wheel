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

from contextlib import contextmanager
from datetime import datetime
from typing import Optional

_frozen_now: Optional[datetime] = None


def now() -> datetime:
    """Current time — real wall clock in production, simulated time under a freeze."""
    return _frozen_now if _frozen_now is not None else datetime.now()


def set_now(dt: Optional[datetime]) -> None:
    """Freeze ``now()`` to ``dt`` (or clear the freeze with None)."""
    global _frozen_now
    _frozen_now = dt


def is_frozen() -> bool:
    """True when a simulated time is currently in effect."""
    return _frozen_now is not None


@contextmanager
def frozen(dt: datetime):
    """Temporarily freeze ``now()`` to ``dt``, restoring the prior state on exit."""
    global _frozen_now
    prev = _frozen_now
    _frozen_now = dt
    try:
        yield
    finally:
        _frozen_now = prev
