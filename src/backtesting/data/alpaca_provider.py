"""Alpaca implementation of OptionsDataProvider.

Sources, all confirmed against alpaca-py and Alpaca's docs (July 2026):

  * Contract discovery: Trading API ``get_option_contracts`` (paginated). We
    query BOTH ``status=active`` and ``status=inactive`` and merge, because for
    any historical ``as_of`` date the contracts that existed then are, by now,
    mostly expired (``inactive``) — and a known Alpaca bug leaves some
    same-day-expired contracts stuck ``active``, so querying only one status
    silently drops contracts around expiration.

  * Option bars: Data API ``get_option_bars`` (``OptionBarsRequest`` takes NO
    feed parameter — historical option bars are OPRA-sourced and free on the
    Basic plan). Bars are trade aggregates, so illiquid contracts have gaps.

  * Stock bars: ``get_stock_bars`` daily. With no feed parameter the SDK defaults
    to SIP, which the Basic plan serves only on a 15-minute delay. The provider
    exposes ``stock_feed`` so a caller may force 'iex'.

Both data endpoints gate *recent* data behind entitlements we do not hold: SIP
stock bars ("subscription does not permit querying recent SIP data") and
real-time OPRA option bars ("OPRA agreement is not signed"). Requests are
therefore clamped to a delayed cutoff, mirroring the live client's buffer.

There is deliberately NO historical-quote path: Alpaca has none, so bid/ask is
modeled downstream (see spread_model.py), never fetched.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional

import structlog

from alpaca.data.historical import (
    OptionHistoricalDataClient,
    StockHistoricalDataClient,
)
from alpaca.data.requests import OptionBarsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetStatus, ContractType
from alpaca.trading.requests import GetOptionContractsRequest

from .provider import OptionBar, OptionContract, OptionsDataProvider, StockBar

logger = structlog.get_logger(__name__)

# Alpaca historical option data does not exist before this date; requests for
# earlier windows return empty and should be reported as "no coverage", not
# silently treated as a data gap.
ALPACA_OPTIONS_HISTORY_START = date(2024, 2, 1)

# Free-tier data is delayed 15 minutes; a request whose end timestamp reaches
# into that window is rejected outright (403) rather than truncated. The live
# client uses the same 20-minute buffer (src/api/alpaca_client.py).
REALTIME_DELAY_MINUTES = 20

# A standard OCC symbol: 1-5 char alpha root, YYMMDD, C/P, 8-digit strike. This
# mirrors the pattern Alpaca's market-data API enforces — it rejects anything
# else outright ('invalid symbol: "1AAPL240429P00170000" does not match ...'),
# and one such symbol 400s the whole bars request it rides in.
#
# The contracts endpoint nonetheless returns them. They are adjusted contracts:
# after a corporate action OCC re-roots the series, and the deliverable is no
# longer 100 shares of the underlying. Excluding them is therefore correct on
# the merits and not merely a workaround — the wheel cannot sell a put whose
# assignment delivers something other than 100 shares.
_STANDARD_OCC = re.compile(r"^[A-Z]{1,5}\d{6}[CP]\d{8}$")


def is_standard_occ(symbol: str) -> bool:
    """Whether ``symbol`` is a standard-deliverable OCC contract."""
    return bool(_STANDARD_OCC.match(symbol))


# NOTE: the two helpers below deliberately read the real wall clock, never
# src.utils.clock.now(). They answer "what is Alpaca entitled to serve at this
# instant", which is independent of the simulated time a replay has frozen. Were
# they to honor the freeze, a backtest of June 2024 would treat every later bar
# as unsettled and fetch nothing.


def _delayed_end(end: date) -> datetime:
    """Clamp a request's end timestamp out of the real-time window."""
    return min(
        datetime.combine(end, time.max),
        datetime.now() - timedelta(minutes=REALTIME_DELAY_MINUTES),
    )


# A one-day move this extreme is a corporate action, not a market move. NVDA's
# 10:1 split shows up as 1208.88 -> 121.79 (0.101x) on 2024-06-10.
SPLIT_RATIO_LOW = 0.6
SPLIT_RATIO_HIGH = 1.6


class UnadjustedCorporateAction(RuntimeError):
    """The underlying series contains a split the engine does not model."""


def detect_split(bars: List[StockBar]) -> Optional[tuple]:
    """Return ``(date, ratio)`` of the first split-sized move, else None.

    Bars are deliberately fetched RAW (unadjusted), because historical option
    strikes are as-listed-at-the-time and are never retroactively adjusted: on
    2024-06-05 NVDA's raw close of 1224.40 sits against strikes 1220/1225/1230,
    and post-split its raw close of 125.20 sits against 124.5/125/125.5. Raw is
    therefore the *correct* input for point-in-time chain building — switching
    to adjusted bars would price a ~122 stock against ~1225 strikes and produce
    garbage deltas on every pre-split day.

    What raw bars cannot survive is a split *inside* the window: the equity
    curve, the buy-and-hold benchmark and GapDetector's gap frequency all read a
    -90% crash that never happened. Modelling the corporate action properly
    (share multiplication plus OCC contract adjustment) is real work; until then
    the honest move is to refuse the window rather than emit a confident
    fabrication.
    """
    for prev, curr in zip(bars, bars[1:]):
        if prev.close <= 0:
            continue
        ratio = curr.close / prev.close
        if ratio < SPLIT_RATIO_LOW or ratio > SPLIT_RATIO_HIGH:
            return curr.bar_date, ratio
    return None


def _is_settled(bar_date: date) -> bool:
    """Whether a daily bar is a completed session.

    Today's daily bar is still forming while the market is open, so its close is
    not the close. The backtest consumes settled sessions only; admitting a
    partial bar would feed the simulator a price that never existed at any
    decision point. Dropping it costs at most the current day.
    """
    return bar_date < date.today()


class AlpacaDataProvider(OptionsDataProvider):
    """Point-in-time historical data from Alpaca."""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        *,
        paper: bool = True,
        stock_feed: Optional[str] = None,
    ) -> None:
        """Construct the provider from raw Alpaca credentials.

        Args:
            api_key, secret_key: Alpaca credentials.
            paper: whether the trading client points at the paper endpoint (only
                affects the contracts endpoint host; data is the same).
            stock_feed: optional data feed for stock bars ('iex' or 'sip'). None
                lets the SDK default (IEX on the free plan).
        """
        self._trading = TradingClient(api_key=api_key, secret_key=secret_key, paper=paper)
        self._option_data = OptionHistoricalDataClient(api_key=api_key, secret_key=secret_key)
        self._stock_data = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)
        self._stock_feed = stock_feed
        # Contract discovery is the most expensive call we make: it paginates
        # over two statuses. Callers legitimately ask for the same (symbol,
        # as_of, max_dte) more than once per decision day — the chain builder
        # needs the contracts, the coverage report needs the count. For a past
        # date the answer is immutable, so memoize it per process.
        self._universe_cache: Dict[tuple, List[OptionContract]] = {}

    @classmethod
    def from_config(cls, config, *, stock_feed: Optional[str] = None) -> "AlpacaDataProvider":
        """Build from the repo's Config (same credentials as live trading)."""
        return cls(
            api_key=config.alpaca_api_key,
            secret_key=config.alpaca_secret_key,
            paper=getattr(config, "paper_trading", True),
            stock_feed=stock_feed,
        )

    # ------------------------------------------------------------------ #
    # Contract discovery
    # ------------------------------------------------------------------ #
    def get_contract_universe(
        self, underlying: str, as_of: date, max_dte: int
    ) -> List[OptionContract]:
        """List contracts tradeable on ``as_of`` expiring within ``max_dte`` days.

        Filters to ``as_of <= expiration <= as_of + max_dte`` and merges the
        active and inactive contract sets (deduped by OCC symbol). Contracts
        that had not yet been *listed* on ``as_of`` cannot be distinguished via
        Alpaca (it exposes no listing date), but standard weekly/monthly options
        are listed well before ``as_of``, so the expiration-window filter is the
        practical point-in-time gate.
        """
        cache_key = (underlying, as_of, max_dte)
        cached = self._universe_cache.get(cache_key)
        if cached is not None:
            return list(cached)

        exp_gte = as_of
        exp_lte = as_of + timedelta(days=max_dte)
        contracts: Dict[str, OptionContract] = {}
        n_adjusted = 0

        for status in (AssetStatus.ACTIVE, AssetStatus.INACTIVE):
            page_token: Optional[str] = None
            while True:
                req = GetOptionContractsRequest(
                    underlying_symbols=[underlying],
                    status=status,
                    expiration_date_gte=exp_gte,
                    expiration_date_lte=exp_lte,
                    limit=10_000,
                    page_token=page_token,
                )
                resp = self._trading.get_option_contracts(req)
                for c in resp.option_contracts or []:
                    if c.symbol in contracts:
                        continue
                    if not is_standard_occ(c.symbol):
                        n_adjusted += 1
                        continue
                    contracts[c.symbol] = OptionContract(
                        symbol=c.symbol,
                        underlying=underlying,
                        expiration=c.expiration_date,
                        strike=float(c.strike_price),
                        option_type="call" if c.type == ContractType.CALL else "put",
                        style="american",
                    )
                page_token = getattr(resp, "next_page_token", None)
                if not page_token:
                    break

        if n_adjusted:
            logger.info(
                "Excluded adjusted (non-standard-deliverable) contracts",
                event_category="backtest_data",
                event_type="adjusted_contracts_excluded",
                symbol=underlying,
                as_of=as_of.isoformat(),
                excluded=n_adjusted,
                kept=len(contracts),
            )

        universe = list(contracts.values())
        self._universe_cache[cache_key] = universe
        return list(universe)

    # ------------------------------------------------------------------ #
    # Option bars
    # ------------------------------------------------------------------ #
    def get_option_bars(
        self, symbols: List[str], start: date, end: date
    ) -> Dict[str, List[OptionBar]]:
        """Daily option bars for ``symbols`` over [start, end] inclusive.

        Alpaca caps symbols-per-request; we chunk to stay well under limits.
        Contracts with no trades in the window simply won't appear in the result.
        Real-time OPRA bars are not entitled, so ``end`` is clamped to the
        delayed cutoff and the current session's partial bar is dropped.
        """
        if not symbols:
            return {}

        # A single non-standard symbol rejects the entire chunk it rides in, so
        # screen them here too rather than trusting every caller.
        symbols = [s for s in symbols if is_standard_occ(s)]
        if not symbols:
            return {}

        end_dt = _delayed_end(end)
        start_dt = datetime.combine(start, time.min)
        if end_dt <= start_dt:
            return {}

        result: Dict[str, List[OptionBar]] = {}
        chunk_size = 100
        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i : i + chunk_size]
            req = OptionBarsRequest(
                symbol_or_symbols=chunk,
                timeframe=TimeFrame.Day,
                start=start_dt,
                end=end_dt,
            )
            bars = self._option_data.get_option_bars(req)
            for sym, sym_bars in (bars.data or {}).items():
                out = [
                    OptionBar(
                        symbol=sym,
                        bar_date=b.timestamp.date(),
                        open=float(b.open),
                        high=float(b.high),
                        low=float(b.low),
                        close=float(b.close),
                        volume=int(b.volume),
                        trade_count=int(getattr(b, "trade_count", 0) or 0),
                        vwap=float(getattr(b, "vwap", 0.0) or 0.0),
                    )
                    for b in sym_bars
                    if _is_settled(b.timestamp.date())
                ]
                out.sort(key=lambda x: x.bar_date)
                if out:
                    result[sym] = out
        return result

    # ------------------------------------------------------------------ #
    # Stock bars
    # ------------------------------------------------------------------ #
    def get_stock_bars(self, symbol: str, start: date, end: date) -> List[StockBar]:
        """Daily underlying bars over [start, end] inclusive, ascending.

        Recent SIP data is not entitled on the Basic plan, so ``end`` is clamped
        to the delayed cutoff and the current session's partial bar is dropped.
        """
        end_dt = _delayed_end(end)
        start_dt = datetime.combine(start, time.min)
        if end_dt <= start_dt:
            return []

        kwargs = dict(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=start_dt,
            end=end_dt,
        )
        if self._stock_feed:
            kwargs["feed"] = self._stock_feed
        req = StockBarsRequest(**kwargs)
        bars = self._stock_data.get_stock_bars(req)
        sym_bars = (bars.data or {}).get(symbol, [])
        out = [
            StockBar(
                symbol=symbol,
                bar_date=b.timestamp.date(),
                open=float(b.open),
                high=float(b.high),
                low=float(b.low),
                close=float(b.close),
                volume=int(b.volume),
            )
            for b in sym_bars
            if _is_settled(b.timestamp.date())
        ]
        out.sort(key=lambda x: x.bar_date)
        return out
