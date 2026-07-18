"""Point-in-time earnings calendar for replay.

Live gating goes through ``EarningsCalendarService``, which asks Finnhub "when is
the *next* earnings date" — a question that can only be answered about now. A
replay standing in 2024 needs the answer as of 2024, so it reads a static table
instead (built by ``tools/backtesting/fetch_earnings_table.py``).

This class implements the surface ``CallRoller`` actually consumes —
``is_earnings_within_n_days`` and ``get_earnings_proximity`` — and answers both
strictly from the frozen clock. It never reaches the network.

Injecting ``None`` instead would skip the gate entirely, making the replay *more*
permissive than live: it would roll on days the live bot refuses to. That is a
silent optimistic bias, which is exactly the class of defect this FC exists to
remove — so the simulator wires this in by default and only falls back to
no-gating when a symbol is genuinely absent from the table, which it reports.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Dict, List, Optional

import structlog

from ...utils import clock

logger = structlog.get_logger(__name__)

EARNINGS_TABLE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "earnings_dates.json"
)


class HistoricalEarningsCalendar:
    """Serves earnings proximity as of the simulated date."""

    def __init__(self, earnings_by_symbol: Dict[str, List[date]]) -> None:
        self._earnings = {
            symbol: sorted(dates) for symbol, dates in earnings_by_symbol.items()
        }
        self.symbols_without_data: set = set()

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    @classmethod
    def from_table(cls, path: str = EARNINGS_TABLE_PATH) -> "HistoricalEarningsCalendar":
        """Load the committed table. Raises if it is missing or malformed."""
        with open(path) as fh:
            payload = json.load(fh)
        raw = payload.get("earnings", {})
        if not raw:
            raise ValueError(f"{path} contains no earnings data")
        return cls(
            {
                symbol: [datetime.strptime(d, "%Y-%m-%d").date() for d in dates]
                for symbol, dates in raw.items()
            }
        )

    # ------------------------------------------------------------------ #
    # The surface CallRoller consumes
    # ------------------------------------------------------------------ #
    def next_earnings_date(self, symbol: str) -> Optional[date]:
        """The first earnings date on or after the simulated date."""
        today = self._today()
        for d in self._earnings.get(symbol, []):
            if d >= today:
                return d
        if symbol not in self._earnings:
            self.symbols_without_data.add(symbol)
        return None

    def is_earnings_within_n_days(self, symbol: str, n_days: int) -> bool:
        """Whether earnings falls within ``n_days`` of the simulated date."""
        nxt = self.next_earnings_date(symbol)
        if nxt is None:
            return False  # fail open, matching the live service's behavior
        return 0 <= (nxt - self._today()).days <= n_days

    def get_earnings_proximity(self, symbol: str) -> Dict:
        """Log-enrichment dict, same keys as the live service."""
        result = {"next_earnings_date": None, "days_until": None, "earnings_hour": None}
        nxt = self.next_earnings_date(symbol)
        if nxt is not None:
            result["next_earnings_date"] = nxt.isoformat()
            result["days_until"] = (nxt - self._today()).days
        return result

    # ------------------------------------------------------------------ #
    @staticmethod
    def _today() -> date:
        if not clock.is_frozen():
            raise RuntimeError(
                "HistoricalEarningsCalendar used outside a frozen clock: it would "
                "answer with the wall-clock date during a historical replay."
            )
        return clock.now().date()
