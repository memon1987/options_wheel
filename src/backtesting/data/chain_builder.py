"""Point-in-time option chain construction.

Assembles, for one underlying on one ``as_of`` date, the chain the strategy
would have seen: every contract that existed and traded that day, priced from
its daily bar close, with implied vol and delta computed via Black-Scholes and
bid/ask modeled by the spread model.

Correctness contract (enforced by tests):
  * No lookahead — only the ``as_of`` day's bars and the underlying's ``as_of``
    close are used; a contract listed/traded only on a later date must not
    appear (the provider's expiration-window filter plus "must have an as_of
    bar" guarantee this).
  * Every derived field (iv, delta, bid, ask) is flagged ``modeled`` so the
    report can never present it as a real quote/greek.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

import structlog

from . import greeks
from .provider import OptionsDataProvider
from .spread_model import SpreadModel

logger = structlog.get_logger(__name__)

# The universe is fetched one calendar day wider than the strategy's DTE window.
#
# Live computes ``dte = (expiration - now).days`` (market_data.py) where the
# expiration is midnight and ``now`` is intraday, so the timedelta FLOORS: a
# contract 8 calendar days out reads as DTE 7 and passes a ``dte <= 7`` filter.
# 50 of 241 real put fills (21%) were exactly those contracts.
#
# Filtering the universe by calendar days would hide them from the chain
# entirely, making the replay structurally blind to a fifth of the trades live
# actually made. So the data layer supplies everything live could see and the
# strategy's own filter — flooring included — decides what qualifies. One day is
# the exact buffer: a 9-calendar-day contract floors to DTE 8 and live rejects it.
UNIVERSE_DTE_BUFFER = 1


@dataclass(frozen=True)
class ChainQuote:
    """One priced contract in a point-in-time chain."""

    symbol: str
    underlying: str
    as_of: date
    expiration: date
    strike: float
    option_type: str  # 'put' | 'call'
    dte: int
    underlying_price: float
    mark: float  # from the option's daily bar close (a trade print)
    bid: float  # modeled
    ask: float  # modeled
    implied_volatility: Optional[float]  # computed via BS inversion; may be None
    delta: Optional[float]  # computed via BS; may be None if IV unsolved
    volume: int
    modeled_spread: bool = True
    modeled_greeks: bool = True


@dataclass(frozen=True)
class ChainSnapshot:
    """A full point-in-time chain for one underlying on ``as_of``."""

    underlying: str
    as_of: date
    underlying_price: float
    puts: List[ChainQuote] = field(default_factory=list)
    calls: List[ChainQuote] = field(default_factory=list)

    def all_quotes(self) -> List[ChainQuote]:
        return [*self.puts, *self.calls]


class ChainBuilder:
    """Builds ChainSnapshots from a data provider + spread model."""

    def __init__(
        self,
        provider: OptionsDataProvider,
        *,
        spread_model: Optional[SpreadModel] = None,
        risk_free_rate: float = 0.04,
        dividend_yields: Optional[Dict[str, float]] = None,
    ) -> None:
        """
        Args:
            provider: historical data source.
            spread_model: bid/ask model; defaults to SpreadModel().
            risk_free_rate: continuous risk-free rate for BS.
            dividend_yields: optional per-symbol continuous dividend yield; a
                symbol absent from the map is treated as non-dividend-paying.
        """
        self._provider = provider
        self._spread = spread_model or SpreadModel()
        self._r = risk_free_rate
        self._div = dividend_yields or {}

    def build(
        self,
        underlying: str,
        as_of: date,
        max_dte: int,
        *,
        underlying_price: Optional[float] = None,
    ) -> Optional[ChainSnapshot]:
        """Construct the chain for ``underlying`` on ``as_of``.

        Args:
            underlying: ticker.
            as_of: decision date.
            max_dte: the strategy's DTE window. The universe is fetched one day
                wider — see ``UNIVERSE_DTE_BUFFER``.
            underlying_price: the underlying's ``as_of`` close; fetched from the
                provider if not supplied (the simulator supplies it to avoid a
                redundant fetch).

        Returns:
            A ChainSnapshot, or None if the underlying price is unavailable for
            ``as_of`` (e.g. a non-trading day or before data coverage).
        """
        if underlying_price is None:
            underlying_price = self._underlying_close(underlying, as_of)
        if underlying_price is None or underlying_price <= 0:
            return None

        contracts = self._provider.get_contract_universe(
            underlying, as_of, max_dte + UNIVERSE_DTE_BUFFER
        )
        if not contracts:
            return ChainSnapshot(underlying, as_of, underlying_price)

        symbols = [c.symbol for c in contracts]
        bars_by_symbol = self._provider.get_option_bars(symbols, as_of, as_of)

        q = self._div.get(underlying, 0.0)
        puts: List[ChainQuote] = []
        calls: List[ChainQuote] = []

        for c in contracts:
            day_bars = bars_by_symbol.get(c.symbol)
            if not day_bars:
                continue  # no trade that day -> no usable price -> not in chain
            bar = day_bars[0]
            mark = bar.close
            if mark <= 0:
                continue

            dte = (c.expiration - as_of).days
            if dte < 0:
                continue
            T = greeks.year_fraction(dte)
            iv = greeks.implied_vol(
                mark, underlying_price, c.strike, T, self._r, q, c.option_type
            )
            delta = (
                greeks.bs_delta(
                    underlying_price, c.strike, T, self._r, iv, q, c.option_type
                )
                if iv is not None
                else None
            )
            moneyness = abs(1.0 - c.strike / underlying_price)
            bid, ask = self._spread.bid_ask(mark, moneyness)

            quote = ChainQuote(
                symbol=c.symbol,
                underlying=underlying,
                as_of=as_of,
                expiration=c.expiration,
                strike=c.strike,
                option_type=c.option_type,
                dte=dte,
                underlying_price=underlying_price,
                mark=mark,
                bid=bid,
                ask=ask,
                implied_volatility=iv,
                delta=delta,
                volume=bar.volume,
            )
            (puts if c.option_type == "put" else calls).append(quote)

        puts.sort(key=lambda x: x.strike)
        calls.sort(key=lambda x: x.strike)
        return ChainSnapshot(underlying, as_of, underlying_price, puts, calls)

    def _underlying_close(self, underlying: str, as_of: date) -> Optional[float]:
        bars = self._provider.get_stock_bars(underlying, as_of, as_of)
        for b in bars:
            if b.bar_date == as_of:
                return b.close
        return None
