"""The day loop — drives the live strategy over history.

Each simulated trading day:

    freeze the clock  ->  wheel_engine.run_strategy_cycle()   (find opportunities)
                      ->  ExecutionEngine: filter -> rank -> select -> execute
                      ->  Friday only: wheel_engine.run_rolling_cycle()
                      ->  settle expirations against today's close
                      ->  record equity

Two orderings here were learned the hard way, and both are load-bearing.

**Execution is a second phase.** ``run_strategy_cycle()`` only *finds*
opportunities; production executes them separately (cloud_run_server's
``/execute`` → ``ExecutionEngine``). A day loop that stops after the scan places
no trades at all and reports a flawless zero-trade backtest.

**Settlement runs after the decision.** A contract expiring today is still held
when the strategy looks at its book — that is what the live bot sees at 3:45pm —
and resolves against today's official close. Settling first removes the expiring
position before the scan, so the engine's stage-6 "already have a position" guard
waves through a fresh put on the same underlying, expiring the same day, which
then never settles.

Nothing in here reimplements strategy logic. If a rule is wrong, it is wrong in
production too — which is the entire point of FC-032.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence

import structlog

from ...data import analytics_writer as analytics_module
from ...strategy.execution_engine import ExecutionEngine
from ...strategy.wheel_engine import WheelEngine
from ...strategy.wheel_state_manager import WheelStateManager
from ...utils.config import Config
from ..data.chain_builder import ChainBuilder, ChainSnapshot
from ..data.alpaca_provider import UnadjustedCorporateAction, detect_split
from ..data.provider import OptionsDataProvider, StockBar
from .alpaca_adapter import BacktestAlpacaClient
from .broker import BacktestBroker
from .clock import SimClock
from .historical_earnings import HistoricalEarningsCalendar
from .no_op_analytics import NoOpAnalyticsWriter, NoOpTradeJournal
from .rejections import RejectionTally

logger = structlog.get_logger(__name__)


def restrict_symbols(config: Config, symbols: Sequence[str]) -> Config:
    """A copy of ``config`` whose universe is ``symbols``.

    ``evaluate`` mode runs one symbol at a time, but WheelEngine scans
    ``config.stock_symbols``. Deep-copied so the caller's config is untouched.
    """
    narrowed = copy.deepcopy(config)
    narrowed._config["stocks"]["symbols"] = list(symbols)
    return narrowed


@dataclass
class DailyState:
    """One row of the equity curve."""

    day: date
    equity: float
    cash: float
    reserved_collateral: float
    open_options: int
    shares_held: Dict[str, int] = field(default_factory=dict)


@dataclass
class SimulationResult:
    symbols: List[str]
    start: date
    end: date
    starting_cash: float
    daily: List[DailyState]
    broker: BacktestBroker
    rejections: Dict[str, int] = field(default_factory=dict)
    candidate_days: int = 0

    @property
    def final_equity(self) -> float:
        return self.daily[-1].equity if self.daily else self.starting_cash

    @property
    def total_return(self) -> float:
        if not self.starting_cash:
            return 0.0
        return (self.final_equity - self.starting_cash) / self.starting_cash


class Simulator:
    """Replays the live wheel strategy over a historical window."""

    def __init__(
        self,
        config: Config,
        provider: OptionsDataProvider,
        builder: ChainBuilder,
        symbols: Sequence[str],
        start: date,
        end: date,
        *,
        starting_cash: float = 100_000.0,
        max_dte: int = 7,
        fill_haircut: float = 0.25,
        fees_per_contract: float = 0.04,
        warmup_calendar_days: int = 60,
        earnings_calendar: Optional[object] = None,
        roll_weekday: int = 4,
    ) -> None:
        self.config = restrict_symbols(config, symbols)
        self.provider = provider
        self.builder = builder
        self.symbols = list(symbols)
        self.start = start
        self.end = end
        self.starting_cash = starting_cash
        self.max_dte = max_dte
        self.fill_haircut = fill_haircut
        self.fees_per_contract = fees_per_contract
        # GapDetector reads ~30 daily bars and indexes into them positionally; on
        # day one of a cold window it raises "single positional indexer is
        # out-of-bounds", which it converts into a conservative
        # block-everything. Load history *before* `start` so the first decision
        # day already has the lookback live would have had. 60 calendar days
        # comfortably covers the 30-session requirement.
        self.warmup_calendar_days = warmup_calendar_days
        # Live earnings gating asks Finnhub for the *next* earnings date, which
        # cannot be answered about a past decision. Default to the committed
        # point-in-time table; passing None skips the gate entirely, which makes
        # rolls more permissive than live (an optimistic bias), so that is
        # strictly opt-in and never the default.
        if earnings_calendar is None:
            earnings_calendar = HistoricalEarningsCalendar.from_table()
        self.earnings_calendar = earnings_calendar
        # Production runs the roll cycle on Fridays (weekday 4).
        self.roll_weekday = roll_weekday

    # ------------------------------------------------------------------ #
    # Data loading
    # ------------------------------------------------------------------ #
    def _load_stock_bars(self) -> Dict[str, List[StockBar]]:
        """Bars from the warm-up start, so day one has a full lookback."""
        fetch_from = self.start - timedelta(days=self.warmup_calendar_days)
        return {s: self.provider.get_stock_bars(s, fetch_from, self.end) for s in self.symbols}

    def _trading_days(self, stock_bars: Dict[str, List[StockBar]]) -> List[date]:
        """Union of session dates inside the *decision* window, ascending.

        Warm-up bars are loaded and visible to the strategy (the adapter clips
        them to the simulated date), but they are never decision days.
        """
        days = {
            b.bar_date
            for bars in stock_bars.values()
            for b in bars
            if self.start <= b.bar_date <= self.end
        }
        return sorted(days)

    def _build_chains(
        self, stock_bars: Dict[str, List[StockBar]], days: Sequence[date]
    ) -> Dict[str, Dict[date, ChainSnapshot]]:
        chains: Dict[str, Dict[date, ChainSnapshot]] = {}
        for symbol in self.symbols:
            closes = {b.bar_date: b.close for b in stock_bars.get(symbol, [])}
            ceiling, floor = self._strike_anchors(stock_bars.get(symbol, []))
            per_day: Dict[date, ChainSnapshot] = {}
            for day in days:
                if day not in closes:
                    continue  # symbol did not trade that session
                snap = self.builder.build(
                    symbol,
                    day,
                    self.max_dte,
                    underlying_price=closes[day],
                    cost_basis=ceiling,
                    low_anchor=floor,
                )
                if snap is not None:
                    per_day[day] = snap
            chains[symbol] = per_day
        return chains

    def _strike_anchors(
        self, bars: Sequence[StockBar]
    ) -> "tuple[Optional[float], Optional[float]]":
        """``(cost_basis_ceiling, low_anchor)`` for this symbol's strike window.

        Chains are built for the whole window *before* the day loop starts, so
        at build time there is no position to read a real cost basis from. What
        we can do is bound the prices any position can be struck against:

        * **Ceiling** — shares only ever arrive by put assignment, and the wheel
          only sells puts struck at or below spot, so no lot this run acquires
          can cost more than the highest close (assignment at strike K <= the
          close on the day it was sold, less premium). This keeps the call
          ladder above cost basis fetched even for a position that goes deeply
          underwater later.
        * **Floor** — the mirror case: a short put stays on the book while the
          underlying rallies, and its strike must remain in the chain or the
          position marks at zero and cannot be closed. The lowest close bounds
          the lowest strike the run can ever be short.

        Both are computed from **decision-window bars only**. Warm-up bars are
        loaded purely to give GapDetector its lookback, and a split inside the
        warm-up buffer is explicitly tolerated (see ``run``) — for NVDA that
        means a pre-split close of 1224.40 sitting in the same series as a ~180
        spot. Including it would set the ceiling ~7x too high and silently turn
        the strike filter into a no-op for every run starting within the warm-up
        buffer of the June 2024 split.

        Using the window's later closes to widen a *fetch* is not lookahead: it
        can only grow the set of contracts offered to the strategy, never change
        any contract's point-in-time price, and the alternative — a spot-centred
        window — is the one that would alter decisions by hiding contracts the
        strategy is holding. The cost is extra strikes fetched on trending
        symbols, which grows with window length; see the plan's follow-up note
        on building chains lazily per-day instead.
        """
        closes = [
            b.close for b in bars if b.close > 0 and self.start <= b.bar_date <= self.end
        ]
        if not closes:
            return None, None
        return max(closes), min(closes)

    # ------------------------------------------------------------------ #
    # Run
    # ------------------------------------------------------------------ #
    def run(self) -> SimulationResult:
        stock_bars = self._load_stock_bars()
        days = self._trading_days(stock_bars)
        if not days:
            raise ValueError(
                f"No trading days for {self.symbols} in {self.start}..{self.end}; "
                "refusing to report a zero-trade run as a successful backtest."
            )
        # Refuse a window containing an unmodelled corporate action. Raw bars
        # are correct for point-in-time chain work but cannot span a split: the
        # benchmark, the equity curve and the gap filter would all read a -90%
        # crash that never happened.
        for symbol, bars in stock_bars.items():
            split = detect_split(bars)
            if split is not None:
                split_date, ratio = split
                # A split inside the WARM-UP buffer is survivable: those bars
                # only feed GapDetector's lookback, and no equity, benchmark or
                # settlement number is computed from them. Refusing the run
                # would reject ~2 months of otherwise-legitimate history and
                # tell the user to avoid a date their window already avoids.
                if split_date < self.start:
                    logger.warning(
                        "Split inside the warm-up window, not the decision "
                        "window: gap statistics over the first sessions read a "
                        "corporate action as a price move and will be "
                        "distorted. Decision-day results are unaffected.",
                        event_category="backtest",
                        event_type="split_in_warmup",
                        symbol=symbol, split_date=split_date.isoformat(),
                        ratio=round(ratio, 4),
                    )
                    continue
                raise UnadjustedCorporateAction(
                    f"{symbol} moved {ratio:.3f}x on {split_date} — a split or "
                    f"other corporate action the engine does not model. Prices "
                    f"before and after are in different units, so the "
                    f"buy-and-hold benchmark, equity curve and gap filter would "
                    f"all be wrong. Choose a window that does not span "
                    f"{split_date}."
                )

        chains = self._build_chains(stock_bars, days)

        broker = BacktestBroker(
            starting_cash=self.starting_cash,
            fees_per_contract=self.fees_per_contract,
            fill_haircut=self.fill_haircut,
        )
        client = BacktestAlpacaClient(broker, chains=chains, stock_bars=stock_bars)

        engine = WheelEngine(
            self.config,
            alpaca_client=client,
            wheel_state=WheelStateManager(storage_bucket=None),
            allow_bigquery_cost_basis=False,
            earnings_calendar=self.earnings_calendar,
        )
        # run_strategy_cycle() only *finds* opportunities — production executes
        # them in a second phase (cloud_run_server's /execute -> ExecutionEngine).
        # A day loop that stops after the scan places no trades at all.
        exec_engine = ExecutionEngine(
            client, self.config, logger, trade_journal=NoOpTradeJournal()
        )

        closes_by_day: Dict[date, Dict[str, float]] = {day: {} for day in days}
        for symbol, bars in stock_bars.items():
            for bar in bars:
                if bar.bar_date in closes_by_day:
                    closes_by_day[bar.bar_date][symbol] = bar.close

        daily: List[DailyState] = []
        sim_clock = SimClock(days)

        # Swap the analytics singleton for a recorder: strategy code fetches it
        # from module scope, so there is no injection point. Restored on exit.
        no_op = NoOpAnalyticsWriter()
        previous_writer = analytics_module.set_analytics_writer(no_op)
        tally = RejectionTally()
        tally.__enter__()
        try:
            for day in sim_clock.steps():
                try:
                    # Pre-trade housekeeping, exactly as production does before
                    # every cycle (cloud_run_server /run). reconcile_positions()
                    # is what teaches WheelStateManager that yesterday's put
                    # expired or was assigned — run_strategy_cycle() never calls
                    # it. Without this the state machine latches after the first
                    # trade and the replay sells one put and then nothing.
                    engine.reconcile_positions()

                    cycle = engine.run_strategy_cycle()
                    self._execute_opportunities(engine, exec_engine, cycle, client)
                    # Production runs the roll cycle Friday afternoon, after the
                    # normal cycle. CallRoller executes its own BTC/STO legs, so
                    # unlike the scan it needs no separate execution phase.
                    if day.weekday() == self.roll_weekday:
                        engine.run_rolling_cycle()
                except Exception:
                    logger.exception(
                        "Strategy cycle raised during replay",
                        event_category="backtest",
                        event_type="replay_cycle_error",
                        day=day.isoformat(),
                    )
                    raise

                # Settle *after* deciding. A contract expiring today is still held
                # when the strategy looks at its book — that is what the live bot
                # sees at 3:45pm — and it resolves against today's official close.
                #
                # Settling first instead removes the expiring position before the
                # scan, so the engine's "already have an option position" guard
                # (stage 6) waves through a brand-new put on the same underlying,
                # dated to expire the same day, which then never settles at all.
                broker.settle_expirations(day, closes_by_day[day])

                daily.append(self._snapshot_state(day, broker, client, closes_by_day[day]))
        finally:
            tally.__exit__(None, None, None)
            analytics_module.set_analytics_writer(previous_writer)

        self._analytics = no_op
        return SimulationResult(
            symbols=self.symbols,
            start=days[0],
            end=days[-1],
            starting_cash=self.starting_cash,
            daily=daily,
            broker=broker,
            rejections=tally.summary(),
            candidate_days=tally.candidate_days,
        )

    @staticmethod
    def _execute_opportunities(engine, exec_engine, cycle, client) -> None:
        """Run the same scan -> filter -> rank -> select -> execute path as prod.

        Mirrors cloud_run_server's /execute endpoint. `filter_failed_opportunities`
        is skipped: it reads the GCS opportunity store of *previous production
        failures*, which has no meaning inside a replay.
        """
        opportunities = [
            a for a in cycle.get("actions", []) if a.get("action_type") == "new_position"
        ]
        if not opportunities:
            return

        positions = client.get_positions()
        opportunities, _ = exec_engine.filter_duplicate_opportunities(opportunities, positions)
        if not opportunities:
            return

        account_info = client.get_account()
        available_bp = float(
            account_info.get("options_buying_power") or account_info["buying_power"]
        )
        ranked = exec_engine.rank_opportunities(opportunities, engine.put_seller, available_bp)
        selected, _ = exec_engine.select_batch(ranked, available_bp)
        if not selected:
            return

        exec_engine.execute_batch(selected, engine.put_seller, call_seller=engine.call_seller)

    @staticmethod
    def _snapshot_state(
        day: date,
        broker: BacktestBroker,
        client: BacktestAlpacaClient,
        closes: Dict[str, float],
    ) -> DailyState:
        # Equity comes from the adapter so the curve is marked exactly the way
        # the strategy saw its own account that day (chain marks where the
        # contract traded, intrinsic where it did not). Marking it differently
        # here would make the reported curve disagree with the decisions taken
        # against it.
        return DailyState(
            day=day,
            equity=client.get_account()["equity"],
            cash=broker.cash,
            reserved_collateral=broker.reserved_collateral,
            open_options=len(broker.options),
            shares_held={u: broker.shares(u) for u in broker.stock_lots},
        )
