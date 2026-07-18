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

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import structlog

from . import greeks
from .provider import OptionsDataProvider
from .spread_model import SpreadModel

if TYPE_CHECKING:  # chain_store imports ChainQuote/ChainSnapshot from here
    from .chain_store import ChainStore

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

# Half-width of the strike ladder we fetch, as a fraction of the as-of close.
#
# Measured on NVDA: the 0.10-0.20 delta band the strategy trades at 7 DTE sits
# between 0.917x and 1.054x spot across five sampled sessions (2025-10-06 ..
# 2026-03-09), while the unbounded universe spans 0.27x to 2.10x. 25% is roughly
# three times the observed worst-case band edge — deliberately loose, because
# the failure mode of a too-tight window is not a slow backtest but a silently
# different one: clip the band and the strategy selects a strike it would never
# have selected live, with no error raised anywhere.
STRIKE_WINDOW_PCT = 0.25


def strike_window(
    underlying_price: float,
    cost_basis: Optional[float] = None,
    low_anchor: Optional[float] = None,
) -> Tuple[float, float]:
    """The strike range to fetch for an underlying at ``underlying_price``.

    +/-``STRIKE_WINDOW_PCT`` around spot, with each bound pushed outward to keep
    strikes the run may still be *holding* inside the window:

    * ``cost_basis`` extends the UPPER bound. A covered call must be struck
      above the cost basis of the shares it covers (the strategy refuses to
      write one that would lock in a loss on assignment), so for an underwater
      position the only *eligible* calls are the ones above cost basis — which
      is exactly where a spot-centred window stops looking. A position 30%
      underwater would find an empty call ladder and never roll, and the replay
      would show it sitting idle rather than writing the call the live bot did.

    * ``low_anchor`` extends the LOWER bound, and is the mirror-image bug. A
      short put struck near 0.93x spot leaves the window as soon as the
      underlying rallies ~24%, and the contract is then missing from the chain
      of a position that is still open. That is worse than it sounds: the
      adapter has no intrinsic fallback for options, so the position marks at
      0.00 (reporting the whole credit as profit) and any close or roll is
      rejected "no_quote" — silently converting a winning early close into a
      hold-to-expiry. Measured over 2024-07..2026-07 this clips a real position
      on 21 AMD and 13 TSLA entry days.
    """
    lo_anchor = underlying_price
    if low_anchor is not None and low_anchor < lo_anchor:
        lo_anchor = low_anchor
    hi_anchor = underlying_price
    if cost_basis is not None and cost_basis > hi_anchor:
        hi_anchor = cost_basis
    return (
        lo_anchor * (1.0 - STRIKE_WINDOW_PCT),
        hi_anchor * (1.0 + STRIKE_WINDOW_PCT),
    )


def _is_cacheable(as_of: date) -> bool:
    """Whether a chain for ``as_of`` is final and safe to persist forever.

    Only settled past sessions are. Today's chain is still forming, and caching
    it would freeze a partial session as if it were final — every later run
    would read back a chain that never existed at any decision point, with no
    TTL to expire it.

    In practice the provider already refuses to serve today: ``_is_settled``
    drops any bar dated today or later, so a chain built for today comes back
    with zero quotes (verified: ``get_stock_bars(today)`` returns 0 bars, so
    ``build`` returns None before reaching this point). That makes this guard
    defence in depth rather than the primary control — but the primary control
    is one caller away from being bypassed, because a caller that supplies
    ``underlying_price`` explicitly skips the stock-bar fetch entirely and would
    otherwise persist an empty chain for today as though it were the truth.
    """
    return as_of < date.today()


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
        store: Optional["ChainStore"] = None,
    ) -> None:
        """
        Args:
            provider: historical data source.
            spread_model: bid/ask model; defaults to SpreadModel().
            risk_free_rate: continuous risk-free rate for BS.
            dividend_yields: optional per-symbol continuous dividend yield; a
                symbol absent from the map is treated as non-dividend-paying.
            store: optional parquet cache. ``None`` (the default) disables
                caching entirely — deliberately opt-in, so a unit test never
                reads a chain another test wrote. Application entry points
                (``evaluate``, the tools) pass one; see ``build``.
        """
        self._provider = provider
        self._spread = spread_model or SpreadModel()
        self._r = risk_free_rate
        self._div = dividend_yields or {}
        self._store = store

    def _model_fingerprint(self, underlying: str) -> str:
        """Identity of every model input baked into a cached quote.

        ``bid``, ``ask``, ``delta`` and ``implied_volatility`` are not fetched —
        they are computed here from the risk-free rate, the symbol's dividend
        yield and the spread model. None of that is implied by
        ``(symbol, as_of)``, so without this in the cache key a run that changes
        any of them reads back quotes computed under the OLD model and reports
        them as its own, with no error and no TTL to expire them.

        This is not a hypothetical: FC-042 Track C1 wires real dividend yields
        and Track C3 recalibrates the spread model, while Track B's studies run
        off this cache in between. A study re-run after C1/C3 would otherwise
        silently mix two different pricing models.

        Bumping ``SCHEMA`` invalidates every existing entry — do that whenever
        the *derivation* changes rather than its inputs (a new IV solver, a
        different moneyness definition).
        """
        parts = (
            "v1",  # SCHEMA
            f"r={self._r!r}",
            f"q={self._div.get(underlying, 0.0)!r}",
            f"spread={self._spread!r}",
        )
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def build(
        self,
        underlying: str,
        as_of: date,
        max_dte: int,
        *,
        underlying_price: Optional[float] = None,
        cost_basis: Optional[float] = None,
        low_anchor: Optional[float] = None,
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
            cost_basis: per-share cost basis of any shares held in this
                underlying, which extends the strike window upward so covered
                calls above cost basis stay reachable. See ``strike_window``.
            low_anchor: lowest underlying price the run may still hold a short
                option against, which extends the window downward. See
                ``strike_window``.

        Returns:
            A ChainSnapshot, or None if the underlying price is unavailable for
            ``as_of`` (e.g. a non-trading day or before data coverage).

        **Caching.** When a store is configured, a covering cache entry short-
        circuits both provider calls. Chains for a *settled past session* are
        immutable — the daily bars they are built from are final, and Alpaca
        never restates them — so there is no TTL and no invalidation policy to
        get wrong. Correctness rests on the entry being a *superset* of the
        request (same or wider strike window, same or longer DTE reach) and on
        the read path narrowing it back to exactly what was asked for, so a warm
        run and a cold run produce identical chains. The one thing that is NOT
        immutable is today's session, which is still forming; see
        ``_is_cacheable``.
        """
        universe_dte = max_dte + UNIVERSE_DTE_BUFFER
        if underlying_price is None:
            underlying_price = self._underlying_close(underlying, as_of)
        if underlying_price is None or underlying_price <= 0:
            return None

        strike_gte, strike_lte = strike_window(underlying_price, cost_basis, low_anchor)

        if self._store is not None:
            hit = self._store.get(
                underlying,
                as_of,
                universe_dte=universe_dte,
                strike_gte=strike_gte,
                strike_lte=strike_lte,
                underlying_price=underlying_price,
                model=self._model_fingerprint(underlying),
            )
            if hit is not None:
                return hit

        snapshot = self._build_uncached(
            underlying, as_of, universe_dte, underlying_price, strike_gte, strike_lte
        )
        if self._store is not None and _is_cacheable(as_of):
            self._store.put(
                snapshot,
                universe_dte=universe_dte,
                strike_gte=strike_gte,
                strike_lte=strike_lte,
                model=self._model_fingerprint(underlying),
            )
        return snapshot

    def _build_uncached(
        self,
        underlying: str,
        as_of: date,
        universe_dte: int,
        underlying_price: float,
        strike_gte: float,
        strike_lte: float,
    ) -> ChainSnapshot:
        contracts = self._provider.get_contract_universe(
            underlying,
            as_of,
            universe_dte,
            strike_gte=strike_gte,
            strike_lte=strike_lte,
        )
        # Re-apply the window locally. The provider bound is an optimisation a
        # provider is allowed to ignore (see the Protocol), and the cache read
        # path narrows to the window unconditionally — so without this the same
        # request could yield a wider chain cold than warm.
        contracts = [c for c in contracts if strike_gte <= c.strike <= strike_lte]
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
