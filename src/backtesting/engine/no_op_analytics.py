"""A analytics writer that records instead of writing.

Strategy code calls ``get_analytics_writer()`` from inside its methods, so there
is no constructor seam. During a replay the simulator installs this object in
place of the singleton: every call is captured in memory (useful for asserting
what a replay *would* have emitted) and nothing reaches BigQuery.

It answers to any method name, because the point is that a replay must never
write — not that we have enumerated every write method correctly. A missed
method that fell through to the real writer would put simulated rows in the
production analytics tables.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


class _Recorder:
    """Answers to any method name, records the call, returns None."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, tuple, Dict[str, Any]]] = []

    def __getattr__(self, name: str):
        # Only reached for names not found normally, so `calls` is safe.
        def _record(*args: Any, **kwargs: Any) -> None:
            self.calls.append((name, args, kwargs))
            return None

        return _record

    def calls_named(self, name: str) -> List[Tuple[str, tuple, Dict[str, Any]]]:
        return [c for c in self.calls if c[0] == name]


class NoOpAnalyticsWriter(_Recorder):
    """Swallows every analytics call, keeping a record of what was asked."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<NoOpAnalyticsWriter calls={len(self.calls)}>"


class NoOpTradeJournal(_Recorder):
    """Stands in for TradeJournal, which otherwise persists trades for real.

    ExecutionEngine constructs `TradeJournal()` by default; a replay must inject
    this instead or every simulated fill would be journaled as a real one.
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<NoOpTradeJournal calls={len(self.calls)}>"
