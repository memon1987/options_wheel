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
        exp_gte = as_of
        exp_lte = as_of + timedelta(days=max_dte)
        contracts: Dict[str, OptionContract] = {}

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

        return list(contracts.values())

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
