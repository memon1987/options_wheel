"""Parquet cache for point-in-time chains.

Cold-fetching a symbol-year of chains from Alpaca is slow (one contract-discovery
call plus a bars call per decision day, at 200 req/min on the free tier). We
persist each built ChainSnapshot to a local parquet file so re-runs — parameter
sweeps, report regeneration, the parity check — hit disk instead of the API.

Layout: ``<cache_dir>/<UNDERLYING>/<YYYY-MM-DD>.parquet``, one file per chain.
Each row is a ChainQuote; the underlying price rides along as a column (constant
within a file) so a snapshot round-trips without a sidecar.

**Why there is no TTL.** A chain for a settled past session is immutable: it is
derived from that day's final daily bars, which Alpaca does not restate. The
entry can therefore live forever. What the key ``(underlying, as_of)`` does NOT
capture is how *much* of that day was fetched — the DTE reach and the strike
window both narrow the result — so each file also records the request it
answers, and a read is a hit only when the file provably covers the new request
(``_covers``) and is narrowed back to it. Getting that wrong would not be a slow
backtest but a wrong one: a chain missing the strikes the caller asked for looks
exactly like a day on which those strikes did not trade.

Today's session is excluded from the cache upstream — see
``chain_builder._is_cacheable``.
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
    # Provenance of the *request* that produced this file, not of any one quote.
    # Constant within a file; see the coverage check in ``get``.
    "universe_dte",
    "strike_gte",
    "strike_lte",
]

# Written into the provenance columns when a caller persists a snapshot without
# declaring what window it was built under. Such a file can still be read back
# wholesale, but it can never satisfy a *bounded* request: we cannot prove it
# covers one. Fail closed — a false cache hit is a silently wrong backtest.
_UNKNOWN = float("nan")

# Strike bounds are floats recomputed per run; compare them with a tolerance
# well below one strike increment (the tightest ladders are $0.50 wide).
_BOUND_TOL = 1e-6


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


class ChainStore:
    """Local parquet cache of ChainSnapshots."""

    def __init__(self, cache_dir: str = "cache/backtest/chains") -> None:
        self._root = Path(cache_dir)

    def _path(self, underlying: str, as_of: date) -> Path:
        return self._root / underlying.upper() / f"{as_of.isoformat()}.parquet"

    def has(self, underlying: str, as_of: date) -> bool:
        return self._path(underlying, as_of).exists()

    def put(
        self,
        snapshot: ChainSnapshot,
        *,
        universe_dte: Optional[int] = None,
        strike_gte: Optional[float] = None,
        strike_lte: Optional[float] = None,
    ) -> None:
        """Persist a snapshot (overwrites any existing file for that day).

        ``universe_dte``/``strike_gte``/``strike_lte`` record the request the
        snapshot answers, so ``get`` can later prove the file covers a new
        request instead of assuming it.
        """
        path = self._path(snapshot.underlying, snapshot.as_of)
        path.parent.mkdir(parents=True, exist_ok=True)
        provenance = {
            "universe_dte": _UNKNOWN if universe_dte is None else float(universe_dte),
            "strike_gte": _UNKNOWN if strike_gte is None else float(strike_gte),
            "strike_lte": _UNKNOWN if strike_lte is None else float(strike_lte),
        }
        rows = [{**self._quote_to_row(q), **provenance} for q in snapshot.all_quotes()]
        if not rows:
            # A real "no contracts traded" day: write one sentinel row (empty
            # symbol) carrying the underlying price so a later read distinguishes
            # an empty chain from a cache miss.
            rows = [{**self._empty_row(snapshot), **provenance}]
        pd.DataFrame(rows, columns=_COLUMNS).to_parquet(path, index=False)

    def get(
        self,
        underlying: str,
        as_of: date,
        *,
        universe_dte: Optional[int] = None,
        strike_gte: Optional[float] = None,
        strike_lte: Optional[float] = None,
        underlying_price: Optional[float] = None,
    ) -> Optional[ChainSnapshot]:
        """Load a cached snapshot, or None on a cache miss.

        A file is a hit only if it *covers* the request: built with at least as
        long a DTE reach and at least as wide a strike window. A covering file
        is then narrowed to exactly the requested window, so that reading from
        cache and building from the provider return the identical chain — the
        property that makes the cache invisible to results rather than merely
        fast.

        Passing no bounds asks for the file as written, with no coverage claim.
        """
        path = self._path(underlying, as_of)
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        if df.empty:
            return None
        if not self._covers(df, universe_dte, strike_gte, strike_lte):
            return None

        cached_price = float(df["underlying_price"].iloc[0])
        if underlying_price is not None and not _close(cached_price, underlying_price):
            # The file was built against a different close for the same session
            # (a restated bar, or a raw/adjusted mix). Every delta in it was
            # computed against that price, so it cannot answer this request.
            return None

        puts, calls = [], []
        for _, r in df.iterrows():
            if not r["symbol"]:  # sentinel row for an empty chain
                continue
            if strike_gte is not None and not (strike_gte <= float(r["strike"]) <= strike_lte):
                continue
            if universe_dte is not None and int(r["dte"]) > universe_dte:
                continue
            q = self._row_to_quote(r)
            (puts if q.option_type == "put" else calls).append(q)
        puts.sort(key=lambda x: x.strike)
        calls.sort(key=lambda x: x.strike)
        return ChainSnapshot(underlying, as_of, cached_price, puts, calls)

    @staticmethod
    def _covers(
        df,
        universe_dte: Optional[int],
        strike_gte: Optional[float],
        strike_lte: Optional[float],
    ) -> bool:
        """Whether the file's build window is a superset of the request."""
        if universe_dte is not None:
            stored = df["universe_dte"].iloc[0] if "universe_dte" in df.columns else _UNKNOWN
            if pd.isna(stored) or int(stored) < universe_dte:
                return False
        if strike_gte is not None or strike_lte is not None:
            if "strike_gte" not in df.columns or "strike_lte" not in df.columns:
                return False
            lo, hi = df["strike_gte"].iloc[0], df["strike_lte"].iloc[0]
            if pd.isna(lo) or pd.isna(hi):
                return False
            # Tolerance: the bounds are recomputed from a float close each run,
            # so an exact-equality test would miss on the last bit and refetch
            # every single day for no reason.
            if strike_gte is not None and float(lo) > strike_gte + _BOUND_TOL:
                return False
            if strike_lte is not None and float(hi) < strike_lte - _BOUND_TOL:
                return False
        return True

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
