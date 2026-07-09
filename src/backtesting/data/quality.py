"""Data-coverage report — the Phase 1 gate.

Before trusting any backtest, we must know whether the historical data can even
support the strategy's decisions. The strategy sells puts in a narrow delta band
(0.10-0.20) at ~7 DTE with a premium floor; if, on most decision days, Alpaca's
trade-derived bars contain no contract in that band with a real price, then a
backtest on this data is measuring data gaps, not the strategy.

``evaluate_coverage`` walks a symbol's history at the strategy's decision cadence
and, for each decision day, asks: did the underlying price exist, did any
contracts exist in the DTE window, did they have same-day bars, and was there at
least one *usable* put candidate (in the delta band, above the premium floor)?
The aggregate "% of decision days with a usable put candidate" is the number the
data-source decision (stay on free Alpaca vs buy ThetaData/ORATS) turns on.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import List, Optional, Tuple

import structlog

from .chain_builder import ChainBuilder
from .provider import OptionsDataProvider

logger = structlog.get_logger(__name__)


@dataclass
class DayCoverage:
    """Coverage facts for a single decision day."""

    as_of: date
    had_underlying_price: bool
    contracts_in_window: int
    contracts_with_bar: int
    puts_in_delta_band: int
    usable_put_candidate: bool  # in band AND premium >= floor
    best_put_premium: Optional[float] = None
    best_put_delta: Optional[float] = None


@dataclass
class CoverageReport:
    """Aggregate coverage over a symbol's evaluation window."""

    symbol: str
    start: date
    end: date
    decision_days: int
    days_with_underlying: int
    days_with_any_contract: int
    days_with_bar: int
    days_with_usable_put: int
    put_delta_band: Tuple[float, float]
    min_put_premium: float
    max_dte: int
    per_day: List[DayCoverage] = field(default_factory=list)

    @property
    def usable_fraction(self) -> float:
        """Fraction of decision days with >=1 usable put candidate (the gate)."""
        return self.days_with_usable_put / self.decision_days if self.decision_days else 0.0

    @property
    def bar_fraction(self) -> float:
        """Fraction of decision days where in-window contracts had same-day bars."""
        if not self.days_with_any_contract:
            return 0.0
        return self.days_with_bar / self.days_with_any_contract

    def verdict(self, *, good_threshold: float = 0.90, marginal_threshold: float = 0.70) -> str:
        """Coverage verdict driving the data-source decision.

        ``no-data`` is distinct from ``poor``: measuring zero decision days (bad
        ticker, empty API response) is not evidence of bad coverage, and must
        never be read as one — "poor" is the verdict that argues for paying a
        vendor. Absence of measurement is not measurement of absence.
        """
        if self.decision_days == 0:
            return "no-data"
        f = self.usable_fraction
        if f >= good_threshold:
            return "good"
        if f >= marginal_threshold:
            return "marginal"
        return "poor"

    def summary(self) -> dict:
        """Compact, serializable summary (per-day detail excluded)."""
        d = asdict(self)
        d.pop("per_day", None)
        d["usable_fraction"] = round(self.usable_fraction, 4)
        d["bar_fraction"] = round(self.bar_fraction, 4)
        d["verdict"] = self.verdict()
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat()
        return d


def evaluate_coverage(
    provider: OptionsDataProvider,
    builder: ChainBuilder,
    symbol: str,
    start: date,
    end: date,
    *,
    max_dte: int = 7,
    put_delta_band: Tuple[float, float] = (0.10, 0.20),
    min_put_premium: float = 0.50,
    sample_every_trading_days: int = 5,
) -> CoverageReport:
    """Walk ``symbol`` from ``start`` to ``end`` and measure decision-day coverage.

    Sampling: the wheel makes ~weekly decisions, so by default we sample every
    5th trading day (roughly weekly) rather than every session — representative
    of the decision cadence and far cheaper on API calls. Set
    ``sample_every_trading_days=1`` for an exhaustive pass.

    Args:
        provider: data source (for the trading-day calendar via stock bars).
        builder: ChainBuilder used to construct each day's chain.
        symbol: ticker.
        start, end: evaluation window.
        max_dte: DTE window for candidate contracts (strategy default 7).
        put_delta_band: absolute delta band for a usable put (strategy default).
        min_put_premium: premium floor per share (strategy default 0.50).
        sample_every_trading_days: decision-day sampling stride.

    Returns:
        A CoverageReport with per-day detail and aggregates.
    """
    stock_bars = provider.get_stock_bars(symbol, start, end)
    trading_days = [b.bar_date for b in stock_bars]
    closes = {b.bar_date: b.close for b in stock_bars}
    sampled = trading_days[::sample_every_trading_days]

    lo, hi = put_delta_band
    per_day: List[DayCoverage] = []

    for as_of in sampled:
        # Hand the builder the close we already fetched. Otherwise it re-queries
        # the underlying once per decision day — a request we cannot spare on a
        # 200 req/min tier.
        snap = builder.build(symbol, as_of, max_dte, underlying_price=closes.get(as_of))
        if snap is None:
            per_day.append(DayCoverage(as_of, False, 0, 0, 0, False))
            continue

        # Contracts-in-window count comes from the provider directly (chain only
        # keeps contracts that had a same-day bar, so we query the universe too).
        window_contracts = provider.get_contract_universe(symbol, as_of, max_dte)
        n_window = len(window_contracts)
        n_with_bar = len(snap.all_quotes())

        in_band = [
            qt
            for qt in snap.puts
            if qt.delta is not None and lo <= abs(qt.delta) <= hi
        ]
        usable = [qt for qt in in_band if qt.mark >= min_put_premium]
        best = max(usable, key=lambda x: x.mark) if usable else None

        per_day.append(
            DayCoverage(
                as_of=as_of,
                had_underlying_price=True,
                contracts_in_window=n_window,
                contracts_with_bar=n_with_bar,
                puts_in_delta_band=len(in_band),
                usable_put_candidate=bool(usable),
                best_put_premium=best.mark if best else None,
                best_put_delta=best.delta if best else None,
            )
        )

    return CoverageReport(
        symbol=symbol,
        start=start,
        end=end,
        decision_days=len(per_day),
        days_with_underlying=sum(1 for d in per_day if d.had_underlying_price),
        days_with_any_contract=sum(1 for d in per_day if d.contracts_in_window > 0),
        days_with_bar=sum(1 for d in per_day if d.contracts_with_bar > 0),
        days_with_usable_put=sum(1 for d in per_day if d.usable_put_candidate),
        put_delta_band=put_delta_band,
        min_put_premium=min_put_premium,
        max_dte=max_dte,
        per_day=per_day,
    )
