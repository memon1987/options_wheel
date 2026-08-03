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
from typing import Dict, List, Optional, Tuple

import structlog

from ...api.earnings_calendar import (
    EARNINGS_CLEAR,
    EARNINGS_KNOWN,
    EARNINGS_UNKNOWN,
)
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
        # FC-013: symbols the table *has* but has run out of dates for. Without
        # this they answer exactly like a genuinely-clear symbol — silent
        # fail-open at the table's edge, and the 2026-07-18 table had most
        # reporters' last dates already in the past by 08-01. ETFs never land
        # here: they are present-with-empty by design, which `horizon_for`
        # reports as None rather than as an exhausted horizon.
        self.symbols_past_horizon: set = set()

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
    # FC-013 — the tri-state surface the scanner gate consumes
    # ------------------------------------------------------------------ #
    def next_earnings_info(self, symbol: str) -> Tuple[str, Optional[date]]:
        """Same contract as ``EarningsCalendarService.next_earnings_info``.

        **This class never returns ``'unknown'``, and that asymmetry with live
        is deliberate.** Live fails closed because an outage means the risk is
        unverifiable while real money is at stake. A replay "outage" is not a
        live risk — it is a table gap, and returning ``'unknown'`` (block)
        for a symbol missing from the table would silently zero out that
        symbol's entire replay: a pessimistic measurement bias that corrupts
        the verdict rather than protecting anything. So the replay fails OPEN
        and *reports* instead: ``symbols_without_data`` for absent symbols,
        ``symbols_past_horizon`` for present ones whose dates have run out.
        The simulator surfaces both, so the operator refreshes the table
        rather than reading a biased number.
        """
        nxt = self.next_earnings_date(symbol)
        if nxt is None:
            self._note_horizon_exhaustion(symbol)
            return (EARNINGS_CLEAR, None)
        return (EARNINGS_KNOWN, nxt)

    def earnings_within(self, symbol: str, n_days: int) -> Optional[bool]:
        """The put leg's tri-state predicate — never ``None`` here, per above."""
        status, nxt = self.next_earnings_info(symbol)
        if status == EARNINGS_UNKNOWN:  # unreachable by construction; kept honest
            return None
        if status == EARNINGS_CLEAR:
            return False
        return 0 <= (nxt - self._today()).days <= n_days

    def horizon_for(self, symbol: str) -> Optional[date]:
        """The last date the table covers for ``symbol``.

        ``None`` for an absent symbol and for a present-but-empty one (the
        ETFs), so a caller can tell "we have no coverage to compare against"
        from "coverage ended on this date".
        """
        dates = self._earnings.get(symbol)
        return dates[-1] if dates else None

    def _note_horizon_exhaustion(self, symbol: str) -> None:
        """Flag a present symbol whose dates are all in the past."""
        horizon = self.horizon_for(symbol)
        if horizon is not None and horizon < self._today():
            self.symbols_past_horizon.add(symbol)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _today() -> date:
        if not clock.is_frozen():
            raise RuntimeError(
                "HistoricalEarningsCalendar used outside a frozen clock: it would "
                "answer with the wall-clock date during a historical replay."
            )
        return clock.now().date()
