"""Point-in-time dividend schedule for replay.

The engine deliberately replays against **unadjusted** underlying bars (see
``alpaca_provider.detect_split``): historical option strikes are as-listed at the
time and are never retroactively adjusted, so adjusted bars would price a
post-split underlying against pre-split strikes. That choice constrains this
table too — the dividend amounts here must be **as-declared on the ex-date**, in
the same share units as the bars and the strikes.

That is why the table is built from Alpaca's corporate-actions endpoint rather
than yfinance, even though yfinance already backs the earnings table. yfinance
back-adjusts dividends through later splits: it reports NVDA's 2023-03-07
dividend as $0.004 because of the June 2024 10:1 split, when the amount actually
paid per share held that day was $0.04. Against unadjusted bars and unadjusted
share counts, that is off by the split ratio. Alpaca reports $0.04 — the rate as
declared. Verified on all 14 universe symbols; see
``tools/backtesting/fetch_dividend_table.py``.

**ETF distributions are included and are not quite equity dividends.** SPY, QQQ
and IWM appear here because Alpaca classifies fund distributions as
``cash_dividends``, and for our purposes — cash credited to whoever held shares
before the ex-date — they settle identically. They differ in *composition*: a
fund distribution bundles dividend income passed through from the fund's holdings
with, at year end, short- and long-term capital-gains distributions. That matters
for tax treatment (which this engine does not model anyway) and it makes the
per-quarter amount lumpier than an equity's declared rate. It does not change the
cash flow, which is all the broker ledger cares about.

Nothing here touches the network: the table is committed, exactly like
``earnings_dates.json``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

import structlog

logger = structlog.get_logger(__name__)

DIVIDEND_TABLE_PATH = os.path.join(
    os.path.dirname(__file__), "dividend_history.json"
)

# OCC exercise-by-exception: in the money by >= 1 cent. Deliberately a local
# constant rather than an import from ``engine.broker`` — ``data`` sits below
# ``engine`` and must not import upward. ``test_backtest_dividends`` asserts the
# two stay equal so the duplication cannot silently drift.
ITM_THRESHOLD = 0.01


@dataclass(frozen=True)
class Dividend:
    """One cash distribution, as declared."""

    ex_date: date
    amount: float  # per share, in the same units as the unadjusted bars
    special: bool = False


class DividendSchedule:
    """Serves per-share dividend amounts by ex-date.

    Unlike ``HistoricalEarningsCalendar`` this takes the date as an argument
    rather than reading the frozen clock. It is queried from two places that sit
    on opposite sides of the clock: the simulator day loop (inside the freeze)
    and the buy-and-hold benchmark (outside it, after the run). A clock-reading
    implementation would work in the first and silently answer with the
    wall-clock date in the second.
    """

    def __init__(
        self,
        by_symbol: Dict[str, List[Dividend]],
        *,
        loaded: bool = True,
        covers_through: Optional[date] = None,
    ) -> None:
        self._by_symbol: Dict[str, List[Dividend]] = {
            symbol: sorted(divs, key=lambda d: d.ex_date)
            for symbol, divs in by_symbol.items()
        }
        self.symbols_without_data: set = set()
        # Whether a real table was read. False means every query returns 0.0,
        # which is indistinguishable from "pays nothing" at the call site — so
        # the flag travels with the object and is surfaced in the report.
        self.loaded = loaded
        # Last ex-date the table can possibly know about. A window running past
        # this credits nothing after it, silently, on both legs.
        self.covers_through = covers_through

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    @classmethod
    def from_table(cls, path: str = DIVIDEND_TABLE_PATH) -> "DividendSchedule":
        """Load the committed table. Raises if it is missing or malformed."""
        with open(path) as fh:
            payload = json.load(fh)
        raw = payload.get("dividends")
        if not raw:
            raise ValueError(f"{path} contains no dividend data")
        until = payload.get("until")
        return cls(
            {
                symbol: [
                    Dividend(
                        ex_date=datetime.strptime(row["ex_date"], "%Y-%m-%d").date(),
                        amount=float(row["amount"]),
                        special=bool(row.get("special", False)),
                    )
                    for row in rows
                ]
                for symbol, rows in raw.items()
            },
            loaded=True,
            covers_through=(
                datetime.strptime(until, "%Y-%m-%d").date() if until else None
            ),
        )

    @classmethod
    def empty(cls) -> "DividendSchedule":
        """A schedule that pays nothing — the pre-FC-042 behavior, for tests."""
        return cls({}, loaded=False)

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    def has_symbol(self, symbol: str) -> bool:
        return symbol in self._by_symbol

    def all_for(self, symbol: str) -> List[Dividend]:
        return list(self._by_symbol.get(symbol, []))

    def amount_on(self, symbol: str, day: date) -> float:
        """Per-share cash going ex on ``day``. 0.0 if none, or if unknown.

        Summed rather than first-match: a symbol can take a regular and a special
        dividend ex on the same date, and paying only one of them would be a
        silent shortfall.
        """
        if symbol not in self._by_symbol:
            self.symbols_without_data.add(symbol)
            return 0.0
        return sum(d.amount for d in self._by_symbol[symbol] if d.ex_date == day)

    def total_between(self, symbol: str, after: date, through: date) -> float:
        """Per-share cash a continuous holder collects over ``(after, through]``.

        The interval is half-open at the start on purpose. Buy-and-hold enters at
        the *close* of ``after``, and a buyer at the close on an ex-date does not
        receive that dividend — the seller does. It is closed at the end because a
        holder who sells at the close on the ex-date still held through the prior
        close and is on the record. Getting this wrong by one day hands the
        benchmark a free quarter on exactly the high-yield names this exists to
        judge.
        """
        if symbol not in self._by_symbol:
            self.symbols_without_data.add(symbol)
            return 0.0
        return sum(
            d.amount
            for d in self._by_symbol[symbol]
            if after < d.ex_date <= through
        )

    def next_ex_date(self, symbol: str, on_or_after: date) -> Optional[date]:
        for d in self._by_symbol.get(symbol, []):
            if d.ex_date >= on_or_after:
                return d.ex_date
        return None


def describe_coverage(
    schedule: "DividendSchedule", symbol: str, start: date, end: date
) -> Dict[str, object]:
    """What the report must tell a reader about this run's dividend data.

    ``dividends_credited: 0.0`` is identically what you see when the symbol pays
    nothing, when it is absent from the table, when the table failed to load,
    and when the wheel simply never held shares. Those mean very different
    things, and the report asserting "both legs collect dividends" while any of
    the middle two is true is worse than the pre-FC-042 state — the caveat that
    used to protect the reader would have been removed without the modelling
    that justified removing it.
    """
    known = schedule.has_symbol(symbol)
    covers = schedule.covers_through
    truncated = bool(covers and end > covers)
    if not schedule.loaded:
        status = "NO TABLE LOADED — no dividends modeled on either leg"
    elif not known:
        status = (
            f"{symbol} IS NOT IN THE DIVIDEND TABLE — no dividends modeled on "
            f"either leg. If it pays one, both the wheel and the benchmark "
            f"understate it. Re-run tools/backtesting/fetch_dividend_table.py "
            f"with --symbols {symbol}."
        )
    elif truncated:
        status = (
            f"table covers ex-dates only through {covers}, but this window ends "
            f"{end} — dividends after {covers} are missing from both legs"
        )
    else:
        status = "complete for this window"
    return {
        "status": status,
        "symbol_in_table": known,
        "table_loaded": schedule.loaded,
        "table_covers_through": covers.isoformat() if covers else None,
        "window_exceeds_table": truncated,
        "known_ex_dates_in_window": (
            sum(1 for d in schedule.all_for(symbol) if start < d.ex_date <= end)
            if known else 0
        ),
    }


def should_assign_early(
    *,
    strike: float,
    underlying_price: float,
    option_mark: float,
    dividend: float,
) -> bool:
    """Whether a short call should be assigned the day before an ex-dividend.

    The rational call holder exercises early iff capturing the dividend beats the
    time value they throw away by exercising — i.e. when remaining extrinsic
    value is less than the dividend. Below that line the holder is strictly
    better off exercising; above it, holding.

    This is the one place the replay may take shares away from the wheel that
    expiration-only settlement would have kept, so it is deliberately strict:
    the call must be genuinely ITM (OCC's 1-cent line) and the dividend must be
    real. A borderline case resolves to "not assigned", which preserves the old
    behavior rather than inventing an assignment.

    Args:
        strike: short call strike.
        underlying_price: close on the day before the ex-date.
        option_mark: the call's mark that same day.
        dividend: per-share cash going ex tomorrow.
    """
    if dividend <= 0:
        return False
    intrinsic = underlying_price - strike
    if intrinsic < ITM_THRESHOLD:
        return False
    extrinsic = max(0.0, option_mark - intrinsic)
    return extrinsic < dividend


def load_default_schedule() -> DividendSchedule:
    """The committed table, or an empty schedule if it is unreadable.

    Falling back to empty rather than raising is the deliberate choice here, and
    it is the opposite of what ``HistoricalEarningsCalendar`` does. A missing
    earnings table makes the replay *more permissive than live* — it rolls on
    days production refuses to — which is a silent optimistic bias worth
    crashing over. A missing dividend table restores the pre-FC-042 behavior of
    modelling no dividends, which is survivable *only because* the resulting
    schedule carries ``loaded=False`` through to ``describe_coverage`` and the
    report says so in the attribution section. Without that it would be silent,
    and silence here is indistinguishable from a symbol that pays nothing.
    """
    try:
        return DividendSchedule.from_table()
    except (OSError, ValueError) as exc:
        logger.warning(
            "Dividend table unavailable; replaying with no dividends modeled",
            event_category="backtest",
            event_type="dividend_table_missing",
            error=str(exc),
        )
        return DividendSchedule.empty()


def summarize(schedule: DividendSchedule, symbols: Iterable[str]) -> Dict[str, int]:
    """Count of known ex-dates per symbol, for the report's data-quality block."""
    return {s: len(schedule.all_for(s)) for s in symbols}
