"""Vendor-agnostic historical options/stock data interface.

The backtest depends only on the ``OptionsDataProvider`` protocol, never on a
specific vendor. The default implementation is Alpaca (``alpaca_provider.py``);
if the Phase 1 coverage report shows Alpaca's trade-derived bars are too sparse
at our low-delta weekly strikes, a second provider (ThetaData/ORATS) drops in
behind the same protocol with nothing downstream changing.

All prices are point-in-time by contract: a provider must never return, for an
``as_of`` date, information that did not exist on that date (no lookahead).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class OptionContract:
    """A single listed option contract (identity only, no pricing)."""

    symbol: str  # OCC-format option symbol, e.g. "AAPL250117P00190000"
    underlying: str
    expiration: date
    strike: float
    option_type: str  # 'put' or 'call'
    style: str = "american"  # US equity options are American-style


@dataclass(frozen=True)
class OptionBar:
    """One daily OHLCV bar for an option contract (aggregated OPRA trades)."""

    symbol: str
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    trade_count: int = 0
    vwap: float = 0.0


@dataclass(frozen=True)
class StockBar:
    """One daily OHLCV bar for the underlying."""

    symbol: str
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@runtime_checkable
class OptionsDataProvider(Protocol):
    """The historical-data surface the backtest consumes.

    Implementations must be point-in-time correct: results for an ``as_of`` date
    may only reflect contracts/prices that existed on or before that date.
    """

    def get_contract_universe(
        self,
        underlying: str,
        as_of: date,
        max_dte: int,
        *,
        strike_gte: Optional[float] = None,
        strike_lte: Optional[float] = None,
    ) -> List[OptionContract]:
        """List contracts tradeable on ``as_of`` expiring within ``max_dte`` days.

        Must include contracts already expired *relative to today* (Alpaca:
        ``status=inactive``) so historical dates see the chain that existed then,
        and must exclude anything expiring before ``as_of`` (already gone) or
        after ``as_of + max_dte`` (outside the decision horizon).

        ``strike_gte``/``strike_lte``, when supplied, bound the strike ladder.
        They are a cost optimisation only: an implementation may ignore them
        (returning a superset is always correct), but must never return strikes
        outside a bound it does honour.
        """
        ...

    def get_option_bars(
        self, symbols: List[str], start: date, end: date
    ) -> Dict[str, List[OptionBar]]:
        """Daily bars per contract symbol over [start, end], inclusive.

        Symbols with no trades in the window are absent from the result (or map
        to an empty list) — callers must treat missing bars as "no data", never
        as zero price.
        """
        ...

    def get_stock_bars(self, symbol: str, start: date, end: date) -> List[StockBar]:
        """Daily underlying bars over [start, end], inclusive, ascending by date."""
        ...
