"""BacktestAlpacaClient — the seam between live strategy code and the simulator.

`WheelEngine` and everything it builds consume a single object, `AlpacaClient`.
This module implements that object's *consumed surface* against historical data
and `BacktestBroker`, so the live `PutSeller`/`CallSeller`/`CallRoller`/
`MarketDataManager` run unmodified over history.

Three principles, each a defense against a specific way a replay can lie:

**No lookahead.** Every read is served as of the simulator's current date, which
is taken from the frozen `clock`. `get_stock_bars` never returns a bar dated
after that day. A backtest that can peek at tomorrow's close is worthless.

**Fail loud.** Live code reaches for the network in places the plan did not
enumerate. Any attribute this adapter does not implement raises
`UnsupportedBacktestCall` rather than falling through to a real client, so an
unmocked call halts the run instead of quietly hitting production.

**Mirror live, don't improve on it.** Where the live client returns a degenerate
value, so do we. `get_options_chain` hardcodes `open_interest: 0` exactly as
`AlpacaClient.get_options_chain` does — which means the live liquidity filter
(`volume == 0 and open_interest < 10`) reduces to "volume must be non-zero".
Fabricating open interest here would make the backtest strictly more permissive
than production and silently inflate the opportunity set.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import structlog

from ...utils import clock
from ...utils.option_symbols import parse_option_symbol
from ..data.chain_builder import ChainSnapshot
from ..data.provider import StockBar
from .broker import BacktestBroker

logger = structlog.get_logger(__name__)


class UnsupportedBacktestCall(RuntimeError):
    """Live code reached for something the adapter does not simulate."""


# Alpaca stamps daily stock bars at MIDNIGHT ET — 04:00 UTC under EDT, 05:00 UTC
# under EST. The adapter reproduces the live stamp rather than inventing one.
# A fixed 04:00 is an hour off for winter dates, which was harmless for the
# historical consumer: the FC-036 gap gate compared CALENDAR DATES
# (``idx.date()``), and both 04:00 and 05:00 UTC on trading day D yield date D.
# (Before FC-036 it compared timestamps, and the stamp is what let the session's
# own bar pass as "previous close" — see docs/plans/fc-036.md. FC-069 has since
# deleted that gate entirely.) Kept fixed for determinism; revisit only if some
# caller ever depends on the exact hour.
_BAR_STAMP = time(4, 0)

# Ledger kinds that Alpaca reports as account activities, and their activity_type.
_LEDGER_TO_ACTIVITY = {
    "put_assignment": "OPASN",
    "call_assignment": "OPASN",
    "expire_worthless": "OPEXP",
}


class BacktestAlpacaClient:
    """Implements the AlpacaClient surface consumed by the strategy components."""

    def __init__(
        self,
        broker: BacktestBroker,
        *,
        chains: Dict[str, Dict[date, ChainSnapshot]],
        stock_bars: Dict[str, List[StockBar]],
        options_approved_level: int = 2,
    ) -> None:
        """
        Args:
            broker: the authoritative cash/position ledger.
            chains: symbol -> as_of -> ChainSnapshot, prebuilt for the run.
            stock_bars: symbol -> full ascending daily history. Reads are clipped
                to the simulator's current date, so passing the whole history is
                safe and lets one dict serve every day of the run.
            options_approved_level: mirrors the live account's approval level.
        """
        self._broker = broker
        self._chains = chains
        self._stock_bars = stock_bars
        self._options_approved_level = options_approved_level

        self._orders: Dict[str, Dict[str, Any]] = {}
        self._order_seq = 0
        # Ledger events already surfaced as activities keep stable synthetic ids,
        # because wheel_engine dedupes activities by id across reconciliation runs.
        self._activity_ids: Dict[int, str] = {}

    # ------------------------------------------------------------------ #
    # Simulator time
    # ------------------------------------------------------------------ #
    @property
    def today(self) -> date:
        """The simulated date. Reading the frozen clock keeps one source of truth."""
        if not clock.is_frozen():
            raise UnsupportedBacktestCall(
                "BacktestAlpacaClient used outside a frozen clock: the adapter "
                "would serve wall-clock data into a historical replay."
            )
        return clock.now().date()

    def _snapshot(self, underlying: str) -> Optional[ChainSnapshot]:
        return self._chains.get(underlying, {}).get(self.today)

    def _underlying_close(self, underlying: str) -> Optional[float]:
        snap = self._snapshot(underlying)
        if snap is not None:
            return snap.underlying_price
        for bar in reversed(self._stock_bars.get(underlying, [])):
            if bar.bar_date <= self.today:
                return bar.close
        return None

    # ------------------------------------------------------------------ #
    # Account & positions
    # ------------------------------------------------------------------ #
    def get_account(self) -> Dict[str, Any]:
        equity = self._equity()
        # Cash-secured only: buying power is uncommitted cash, never the old
        # engine's fictional 2:1 margin.
        available = self._broker.available_cash
        return {
            "buying_power": available,
            "cash": self._broker.cash,
            "portfolio_value": equity,
            "equity": equity,
            "options_buying_power": available,
            "options_approved_level": self._options_approved_level,
        }

    def _equity(self) -> float:
        stock_marks: Dict[str, float] = {}
        for underlying in self._broker.stock_lots:
            px = self._underlying_close(underlying)
            if px is not None:
                stock_marks[underlying] = px

        option_marks: Dict[str, float] = {}
        for symbol, pos in self._broker.options.items():
            snap = self._snapshot(pos.underlying)
            quote = _find_quote(snap, symbol) if snap else None
            if quote is not None:
                option_marks[symbol] = quote.mark
            else:
                # No trade that day: fall back to intrinsic against the underlying.
                px = self._underlying_close(pos.underlying)
                if px is None:
                    continue
                intrinsic = (
                    max(0.0, pos.strike - px)
                    if pos.option_type == "put"
                    else max(0.0, px - pos.strike)
                )
                option_marks[symbol] = intrinsic
        return self._broker.equity(stock_marks, option_marks)

    def get_positions(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []

        for underlying, lots in self._broker.stock_lots.items():
            shares = sum(lot.shares for lot in lots)
            if shares <= 0:
                continue
            px = self._underlying_close(underlying)
            basis = self._broker.average_cost_basis(underlying) or 0.0
            market_value = (px or 0.0) * shares
            out.append(
                {
                    "symbol": underlying,
                    "qty": float(shares),
                    "side": "long",
                    "market_value": market_value,
                    "cost_basis": basis * shares,
                    # FC-065: the covered-call floor reads this field, so the
                    # simulated broker has to emit it too. FC-068 closed the
                    # interim gap: `_assign_put` now books the lot at
                    # `strike − put premium`, matching Alpaca's own
                    # `avg_entry_price` semantics, so the simulated floor is
                    # the production floor rather than one premium above it.
                    "avg_entry_price": basis,
                    "unrealized_pl": market_value - basis * shares,
                    "asset_class": "us_equity",
                }
            )

        for symbol, pos in self._broker.options.items():
            snap = self._snapshot(pos.underlying)
            quote = _find_quote(snap, symbol) if snap else None
            mark = quote.mark if quote is not None else 0.0
            # Short options: negative qty and negative market value, as Alpaca reports.
            market_value = -mark * 100 * pos.contracts
            cost_basis = -pos.entry_price * 100 * pos.contracts
            out.append(
                {
                    "symbol": symbol,
                    "qty": float(-pos.contracts),
                    "side": "short",
                    "market_value": market_value,
                    "cost_basis": cost_basis,
                    # Per-contract-share premium received, as Alpaca reports it
                    # for a short option (positive, unlike cost_basis).
                    "avg_entry_price": pos.entry_price,
                    # Short premium: profit as the option decays toward zero.
                    "unrealized_pl": (pos.entry_price - mark) * 100 * pos.contracts,
                    "asset_class": "us_option",
                }
            )
        return out

    # ------------------------------------------------------------------ #
    # Market data
    # ------------------------------------------------------------------ #
    def get_stock_quote(self, symbol: str) -> Dict[str, Any]:
        px = self._underlying_close(symbol)
        if px is None:
            return {}
        # EOD replay has no book; the close is both sides. MarketDataManager
        # averages bid/ask, so this yields exactly the close.
        return {
            "symbol": symbol,
            "bid": px,
            "ask": px,
            "bid_size": 0,
            "ask_size": 0,
            "timestamp": self.today.isoformat(),
        }

    def get_stock_bars(self, symbol: str, days: int = 30) -> pd.DataFrame:
        """Daily OHLCV up to and including the simulated date. Never beyond it.

        The index must be tz-aware UTC, exactly like the live client's
        (``datetime64[ns, UTC]``, bars stamped 04:00 UTC), so that replay and
        live derive identical trading dates from the index.

        ``days`` is a CALENDAR-day lookback, not a bar count — the live client
        builds ``start = end - timedelta(days=days)``. Slicing the last ``days``
        *bars* instead hands the caller ~43% more history (50 calendar days is
        ~35 sessions), which silently changes every windowed statistic computed
        on it. The illustration that established this, from the gap-frequency
        filter FC-069 later deleted: it was a ratio over exactly this window,
        and with the longer window NVDA measured 18.6% against a 15% limit and
        was blocked for all of Nov 2025, while live traded it on 7 days.
        """
        cutoff = self.today - timedelta(days=days) if days else None
        bars = [
            b
            for b in self._stock_bars.get(symbol, [])
            if b.bar_date <= self.today and (cutoff is None or b.bar_date > cutoff)
        ]
        if not bars:
            return pd.DataFrame()
        index = pd.DatetimeIndex(
            [datetime.combine(b.bar_date, _BAR_STAMP) for b in bars], name="timestamp"
        ).tz_localize("UTC")
        return pd.DataFrame(
            {
                "open": [b.open for b in bars],
                "high": [b.high for b in bars],
                "low": [b.low for b in bars],
                "close": [b.close for b in bars],
                "volume": [b.volume for b in bars],
            },
            index=index,
        )

    def get_options_chain(self, underlying_symbol: str) -> List[Dict[str, Any]]:
        snap = self._snapshot(underlying_symbol)
        if snap is None:
            return []

        out: List[Dict[str, Any]] = []
        for quote in snap.all_quotes():
            # A contract whose IV would not solve has no delta. Live code does
            # abs(opt.get('delta', 0)) and would raise TypeError on None, so such
            # contracts are dropped: unpriceable means not a candidate.
            if quote.delta is None:
                continue
            out.append(
                {
                    "symbol": quote.symbol,
                    "underlying_symbol": underlying_symbol,
                    "option_type": quote.option_type,
                    "strike_price": quote.strike,
                    "expiration_date": quote.expiration.isoformat(),
                    "bid": quote.bid,
                    "ask": quote.ask,
                    "bid_size": 0,
                    "ask_size": 0,
                    "last_price": quote.mark,
                    "volume": quote.volume,
                    # Mirrors live exactly; see module docstring.
                    "open_interest": 0,
                    "implied_volatility": quote.implied_volatility or 0.0,
                    "delta": quote.delta,
                    "gamma": 0.0,
                    "theta": 0.0,
                    "vega": 0.0,
                }
            )
        return out

    def get_option_quote(self, option_symbol: str) -> Dict[str, Any]:
        parsed = parse_option_symbol(option_symbol)
        snap = self._snapshot(parsed.get("underlying", ""))
        quote = _find_quote(snap, option_symbol) if snap else None
        if quote is None:
            return {}
        return {
            "symbol": option_symbol,
            "bid": quote.bid,
            "ask": quote.ask,
            "mid_price": (quote.bid + quote.ask) / 2,
            "bid_size": 0,
            "ask_size": 0,
        }

    # ------------------------------------------------------------------ #
    # Orders
    # ------------------------------------------------------------------ #
    def place_option_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str = "limit",
        limit_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Fill immediately at the broker's haircut price (EOD convention).

        The strategy's limit_price is recorded but not enforced: at one decision
        point per day there is no intraday path along which to decide whether a
        limit would have been touched. The broker's mid-minus-haircut fill is the
        documented convention, and Phase 4 reports the bid-fill worst case.
        """
        parsed = parse_option_symbol(symbol)
        underlying = parsed.get("underlying", "")
        option_type = parsed.get("option_type", "unknown")
        strike = float(parsed.get("strike_price", 0.0))
        expiration = _parse_expiration(parsed)

        snap = self._snapshot(underlying)
        quote = _find_quote(snap, symbol) if snap else None
        if quote is None:
            return self._order_error(
                symbol, qty, side, "no_quote",
                f"No {symbol} bar on {self.today}: contract did not trade.",
            )

        if side == "sell":
            if option_type == "put":
                fill = self._broker.sell_put_to_open(
                    symbol, underlying, strike, expiration, qty,
                    quote.mark, quote.bid, self.today,
                )
                if fill is None:
                    return self._order_error(
                        symbol, qty, side, "insufficient_collateral",
                        f"Need ${strike * 100 * qty:,.0f} collateral, "
                        f"${self._broker.available_cash:,.0f} available.",
                    )
            else:
                fill = self._broker.sell_call_to_open(
                    symbol, underlying, strike, expiration, qty,
                    quote.mark, quote.bid, self.today,
                )
                if fill is None:
                    return self._order_error(
                        symbol, qty, side, "insufficient_shares",
                        f"Need {qty * 100} uncovered shares of {underlying}; "
                        f"hold {self._broker.shares(underlying)}, of which "
                        f"{self._broker.pledged_shares(underlying)} already back "
                        f"open calls.",
                    )
        elif side == "buy":
            # Capture the reason BEFORE attempting, so a rejection is diagnosed
            # correctly. buy_to_close returns None for two different causes, and
            # reporting a cash shortfall as "no position" would mislead exactly
            # the rejection analysis this feeds.
            position = self._broker.options.get(symbol)
            fill = self._broker.buy_to_close(
                symbol, qty, quote.mark, quote.ask, self.today
            )
            if fill is None:
                if position is None or qty > position.contracts:
                    return self._order_error(
                        symbol, qty, side, "no_position",
                        f"No open short position in {symbol} to close "
                        f"({qty} contracts requested).",
                    )
                cost = self._broker.buy_fill(quote.mark, quote.ask) * 100 * qty
                return self._order_error(
                    symbol, qty, side, "insufficient_cash",
                    f"Buy-to-close needs ${cost:,.2f} but only "
                    f"${self._broker.available_cash:,.2f} is available.",
                )
        else:
            raise UnsupportedBacktestCall(f"Unsupported order side: {side!r}")

        return self._order_success(symbol, qty, side, limit_price, fill)

    def _order_success(self, symbol, qty, side, limit_price, fill) -> Dict[str, Any]:
        self._order_seq += 1
        order_id = f"bt-{self._order_seq:06d}"
        stamp = clock.now().isoformat()
        record = {
            "order_id": order_id,
            "client_order_id": order_id,
            "symbol": symbol,
            "qty": int(qty),
            "filled_qty": int(qty),
            "remaining_qty": 0,
            "is_partial_fill": False,
            "side": side,
            "status": "filled",
            "order_type": "limit",
            "limit_price": limit_price,
            "filled_avg_price": fill,
            "submitted_at": stamp,
            "filled_at": stamp,
            "expired_at": None,
            "canceled_at": None,
        }
        self._orders[order_id] = record
        return {"success": True, **{k: record[k] for k in (
            "order_id", "client_order_id", "symbol", "qty", "side",
            "limit_price", "status", "submitted_at")}}

    @staticmethod
    def _order_error(symbol, qty, side, error_type, message) -> Dict[str, Any]:
        # Live returns (never raises) on rejection; strategy code checks success.
        return {
            "success": False,
            "error_type": error_type,
            "error_message": message,
            "non_retryable": True,
            "symbol": symbol,
            "qty": qty,
            "side": side,
        }

    def get_orders(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        orders = list(self._orders.values())
        if status:
            orders = [o for o in orders if o["status"] == status]
        return orders

    def get_order_by_id(self, order_id: str) -> Dict[str, Any]:
        return dict(self._orders.get(order_id, {}))

    # ------------------------------------------------------------------ #
    # Account activities (assignment / expiration reconciliation)
    # ------------------------------------------------------------------ #
    def get_account_activities(
        self,
        activity_types: str = "OPASN,OPEXP",
        after: Optional[str] = None,
        page_size: int = 100,
        page_token: Optional[str] = None,
        direction: str = "desc",
    ) -> List[Dict[str, Any]]:
        """Synthesize Alpaca activities from the broker's ledger.

        wheel_engine dedupes by ``id`` across reconciliation runs, so ids must be
        stable for a given ledger event — hence keying on the event's index.
        """
        wanted = {t.strip() for t in activity_types.split(",") if t.strip()}
        after_date = _parse_iso_date(after) if after else None

        out: List[Dict[str, Any]] = []
        for idx, ev in enumerate(self._broker.ledger):
            activity_type = _LEDGER_TO_ACTIVITY.get(ev.kind)
            if activity_type is None or activity_type not in wanted:
                continue
            if after_date and ev.event_date < after_date:
                continue
            if ev.event_date > self.today:
                continue  # no lookahead, even into our own future ledger
            out.append(
                {
                    "id": self._activity_ids.setdefault(idx, f"bt-act-{idx:06d}"),
                    "activity_type": activity_type,
                    "symbol": ev.symbol,
                    "qty": float(ev.contracts),
                    "price": ev.price,
                    "net_amount": ev.cash_delta,
                    "date": ev.event_date.isoformat(),
                    "transaction_time": ev.event_date.isoformat(),
                }
            )
        out.sort(key=lambda a: a["date"], reverse=(direction == "desc"))
        return out[:page_size]

    # ------------------------------------------------------------------ #
    # Fail loud on anything else
    # ------------------------------------------------------------------ #
    def __getattr__(self, name: str) -> Any:
        raise UnsupportedBacktestCall(
            f"Live code called AlpacaClient.{name!r}, which the backtest adapter "
            "does not simulate. Implement it or the replay is silently reaching "
            "for production."
        )


def _find_quote(snap: Optional[ChainSnapshot], symbol: str):
    if snap is None:
        return None
    for quote in snap.all_quotes():
        if quote.symbol == symbol:
            return quote
    return None


def _parse_expiration(parsed: Dict[str, Any]) -> date:
    raw = parsed.get("expiration_date")
    if isinstance(raw, date):
        return raw
    return datetime.strptime(str(raw), "%Y-%m-%d").date()


def _parse_iso_date(value: str) -> date:
    return datetime.strptime(value[:10], "%Y-%m-%d").date()
