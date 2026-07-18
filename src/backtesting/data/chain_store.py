"""Parquet cache for point-in-time chains.

Cold-fetching a symbol-year of chains from Alpaca is slow (one contract-discovery
call plus a bars call per decision day, at 200 req/min on the free tier). We
persist each built ChainSnapshot to a local parquet file so re-runs — parameter
sweeps, report regeneration, the parity check — hit disk instead of the API.

Layout: ``<cache_dir>/<UNDERLYING>/<YYYY-MM-DD>.parquet``, one file per chain.
Each row is a ChainQuote; the underlying price rides along as a column (constant
within a file) so a snapshot round-trips without a sidecar.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from .chain_builder import ChainQuote, ChainSnapshot

_COLUMNS = [
    "symbol",
    "underlying",
    "as_of",
    "expiration",
    "strike",
    "option_type",
    "dte",
    "underlying_price",
    "mark",
    "bid",
    "ask",
    "implied_volatility",
    "delta",
    "volume",
    "modeled_spread",
    "modeled_greeks",
]


class ChainStore:
    """Local parquet cache of ChainSnapshots."""

    def __init__(self, cache_dir: str = "cache/backtest/chains") -> None:
        self._root = Path(cache_dir)

    def _path(self, underlying: str, as_of: date) -> Path:
        return self._root / underlying.upper() / f"{as_of.isoformat()}.parquet"

    def has(self, underlying: str, as_of: date) -> bool:
        return self._path(underlying, as_of).exists()

    def put(self, snapshot: ChainSnapshot) -> None:
        """Persist a snapshot (overwrites any existing file for that day)."""
        path = self._path(snapshot.underlying, snapshot.as_of)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [self._quote_to_row(q) for q in snapshot.all_quotes()]
        if not rows:
            # A real "no contracts traded" day: write one sentinel row (empty
            # symbol) carrying the underlying price so a later read distinguishes
            # an empty chain from a cache miss.
            rows = [self._empty_row(snapshot)]
        pd.DataFrame(rows, columns=_COLUMNS).to_parquet(path, index=False)

    def get(self, underlying: str, as_of: date) -> Optional[ChainSnapshot]:
        """Load a cached snapshot, or None on a cache miss."""
        path = self._path(underlying, as_of)
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        underlying_price = float(df["underlying_price"].iloc[0]) if not df.empty else 0.0
        puts, calls = [], []
        for _, r in df.iterrows():
            if not r["symbol"]:  # sentinel row for an empty chain
                continue
            q = self._row_to_quote(r)
            (puts if q.option_type == "put" else calls).append(q)
        puts.sort(key=lambda x: x.strike)
        calls.sort(key=lambda x: x.strike)
        return ChainSnapshot(underlying, as_of, underlying_price, puts, calls)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _quote_to_row(q: ChainQuote) -> dict:
        return {
            "symbol": q.symbol,
            "underlying": q.underlying,
            "as_of": q.as_of.isoformat(),
            "expiration": q.expiration.isoformat(),
            "strike": q.strike,
            "option_type": q.option_type,
            "dte": q.dte,
            "underlying_price": q.underlying_price,
            "mark": q.mark,
            "bid": q.bid,
            "ask": q.ask,
            "implied_volatility": q.implied_volatility,
            "delta": q.delta,
            "volume": q.volume,
            "modeled_spread": q.modeled_spread,
            "modeled_greeks": q.modeled_greeks,
        }

    @staticmethod
    def _empty_row(snap: ChainSnapshot) -> dict:
        # Sentinel row: empty symbol marks "no contracts", carries metadata.
        return {
            "symbol": "",
            "underlying": snap.underlying,
            "as_of": snap.as_of.isoformat(),
            "expiration": snap.as_of.isoformat(),
            "strike": 0.0,
            "option_type": "",
            "dte": 0,
            "underlying_price": snap.underlying_price,
            "mark": 0.0,
            "bid": 0.0,
            "ask": 0.0,
            "implied_volatility": None,
            "delta": None,
            "volume": 0,
            "modeled_spread": True,
            "modeled_greeks": True,
        }

    @staticmethod
    def _row_to_quote(r) -> ChainQuote:
        return ChainQuote(
            symbol=r["symbol"],
            underlying=r["underlying"],
            as_of=date.fromisoformat(r["as_of"]),
            expiration=date.fromisoformat(r["expiration"]),
            strike=float(r["strike"]),
            option_type=r["option_type"],
            dte=int(r["dte"]),
            underlying_price=float(r["underlying_price"]),
            mark=float(r["mark"]),
            bid=float(r["bid"]),
            ask=float(r["ask"]),
            implied_volatility=(
                None if pd.isna(r["implied_volatility"]) else float(r["implied_volatility"])
            ),
            delta=(None if pd.isna(r["delta"]) else float(r["delta"])),
            volume=int(r["volume"]),
            modeled_spread=bool(r["modeled_spread"]),
            modeled_greeks=bool(r["modeled_greeks"]),
        )
