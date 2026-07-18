"""Per-symbol fitness scorecard.

Answers the question FC-032 exists to answer: *is this symbol a good fit for the
wheel as we run it?* — and answers it against the only benchmark that matters,
buy-and-hold of the same symbol over the same window.

Two design commitments, both from the research and both easy to get wrong:

**Attribution is mandatory.** In published SPY wheel studies ~94-99% of total
return came from the stock leg, not premium. A scorecard that reports one blended
number cannot distinguish "this strategy earns premium" from "this symbol went
up". Option and stock P&L are therefore always carried separately.

**A high win rate is not evidence of skill.** Selling 15-delta puts wins ~85% of
the time by construction; the number says almost nothing beyond the delta chosen.
So win rate is reported alongside the tail — worst cycle, max drawdown, and time
spent underwater holding assigned shares — never on its own.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence

from ..engine.simulator import DailyState
from .cycles import WheelCycle

TRADING_DAYS_PER_YEAR = 252

# Below this fraction of decision days holding a position, a symbol is judged
# untradeable rather than scored. The wheel sells ~7 DTE, so a symbol it can
# actually trade sits in a position most of the time; 25% is well under a
# continuously-wheeled name (NVDA measured 76%) and well above one that traded
# once or twice (KMI measured 3%).
MIN_DAYS_IN_POSITION = 0.25

# Absolute performance floor. Beating buy-and-hold over a short window is close
# to a coin flip, so a purely relative gate lets a sub-cash result read "fit".
RISK_FREE_RATE = 0.04

# Account-equity drawdown that should draw attention. With max_position_size
# 0.35 and one open position per symbol in evaluate mode, equity simply cannot
# fall 20%, so the old gate could never fire.
MAX_DRAWDOWN_WARN = -0.08


@dataclass
class BuyAndHold:
    """The benchmark: the same capital, in the stock, for the same window."""

    shares: int
    entry_price: float
    exit_price: float
    starting_cash: float

    @property
    def final_value(self) -> float:
        return self.starting_cash + self.shares * (self.exit_price - self.entry_price)

    @property
    def total_return(self) -> float:
        if self.starting_cash <= 0:
            return 0.0
        return (self.final_value - self.starting_cash) / self.starting_cash


@dataclass
class FitnessReport:
    """Everything the evaluate-mode report needs, already computed."""

    symbol: str
    start: date
    end: date
    starting_cash: float
    final_equity: float

    # Attribution — never collapsed into one number.
    option_pnl: float = 0.0  # premium net of buybacks AND fees (fees are inside)
    stock_pnl: float = 0.0  # realized: called away or otherwise disposed
    unrealized_stock_pnl: float = 0.0  # open assigned shares, marked to the last close
    dividends: float = 0.0
    fees: float = 0.0  # memo only; already deducted inside option_pnl

    # Cycle statistics.
    cycles: List[WheelCycle] = field(default_factory=list)
    puts_sold: int = 0
    calls_sold: int = 0
    assignments: int = 0
    rolls: int = 0

    # Risk.
    max_drawdown: float = 0.0
    days_underwater: int = 0
    sharpe: float = 0.0
    sortino: float = 0.0

    # Activity. A symbol the strategy cannot actually trade produces a tiny,
    # flattering return on a handful of days; this is what exposes that.
    days_in_position: int = 0
    avg_collateral: float = 0.0  # mean reserved collateral across decision days
    peak_collateral: float = 0.0

    benchmark: Optional[BuyAndHold] = None
    data_quality: Dict = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    @property
    def total_pnl(self) -> float:
        return self.final_equity - self.starting_cash

    @property
    def total_return(self) -> float:
        if self.starting_cash <= 0:
            return 0.0
        return self.total_pnl / self.starting_cash

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    @property
    def annualized_return(self) -> float:
        """Linear annualization; short windows are not compounded into fiction."""
        if self.days <= 0:
            return 0.0
        return self.total_return * (365.0 / self.days)

    @property
    def total_stock_pnl(self) -> float:
        """Realized plus unrealized. Both are the stock leg.

        Counting only realized P&L understates the stock leg badly whenever a
        cycle is still open: an NVDA replay finished holding shares assigned at
        177.50 that had appreciated ~$2,000, which showed up in equity (and so
        in the headline return) but nowhere in attribution — the report claimed
        "100% from the option leg" for a result that was two-thirds long stock.
        """
        return self.stock_pnl + self.unrealized_stock_pnl

    @property
    def attribution_total(self) -> float:
        """What the attribution rows sum to. Must equal ``total_pnl``."""
        return self.option_pnl + self.total_stock_pnl + self.dividends

    @property
    def reconciliation_gap(self) -> float:
        """Attribution minus the actual equity change.

        Non-zero means a cash flow escaped the attribution table, which would
        make every share below a lie. Surfaced in the report rather than
        silently absorbed.
        """
        return self.attribution_total - self.total_pnl

    @property
    def option_pnl_share(self) -> Optional[float]:
        """Fraction of gross P&L from the option leg.

        None when the two legs have opposite signs — the ratio is meaningless
        then (e.g. premium +$500 against stock -$5,000 is not "10% from options"),
        and reporting a number anyway is how attribution gets misread.
        """
        stock = self.total_stock_pnl
        gross = self.option_pnl + stock
        if gross == 0 or (self.option_pnl < 0) != (stock < 0):
            return None
        return self.option_pnl / gross

    @property
    def closed_cycles(self) -> List[WheelCycle]:
        return [c for c in self.cycles if not c.is_open]

    @property
    def win_rate(self) -> Optional[float]:
        """Fraction of closed cycles with positive total P&L.

        High by construction at our deltas — read it next to worst_cycle.
        """
        closed = self.closed_cycles
        if not closed:
            return None
        return sum(1 for c in closed if c.total_pnl > 0) / len(closed)

    @property
    def assignment_rate(self) -> Optional[float]:
        """Share of ALL cycles that took assignment, open ones included.

        Counting closed cycles only reported "0% assignment" for a run that
        finished holding assigned shares — irreconcilable, next to it, with
        "12 days holding shares below cost basis".
        """
        if not self.cycles:
            return None
        return sum(1 for c in self.cycles if c.assigned) / len(self.cycles)

    @property
    def days_in_position_fraction(self) -> float:
        """Fraction of decision days on which ANY position was held.

        Named for what it measures. It is a *time* occupancy, not a capital one:
        a symbol tying up 3% of the account every single day scores 1.0 here.
        Read it beside ``avg_collateral`` / ``return_on_collateral``, which are
        the capital-weighted views.

        Its job is to expose the symbol the strategy cannot trade at all. KMI
        managed one 8-day cycle in 273 days — +138% annualized on that cycle,
        +0.06% overall — which is not a performance result, it is an absence of
        one.
        """
        if not self.decision_days:
            return 0.0
        return self.days_in_position / self.decision_days

    @property
    def return_on_collateral(self) -> Optional[float]:
        """Total P&L over average collateral committed — the plan's headline.

        ``total_return`` divides by the whole account, so it is dominated by the
        arbitrary starting-cash choice: one contract against $100k dilutes any
        result by ~5x and makes the wheel structurally lose to buy-and-hold in a
        rising market regardless of merit. Return on the capital actually put at
        risk is the scale-free number.
        """
        if self.avg_collateral <= 0:
            return None
        return self.total_pnl / self.avg_collateral

    @property
    def annualized_return_on_collateral(self) -> Optional[float]:
        roc = self.return_on_collateral
        if roc is None or self.days <= 0:
            return None
        return roc * (365.0 / self.days)

    @property
    def decision_days(self) -> int:
        return int(self.data_quality.get("decision_days") or 0)

    @property
    def worst_cycle(self) -> Optional[WheelCycle]:
        closed = self.closed_cycles
        return min(closed, key=lambda c: c.total_pnl) if closed else None

    @property
    def excess_return(self) -> Optional[float]:
        if self.benchmark is None:
            return None
        return self.total_return - self.benchmark.total_return

    def verdict(self) -> str:
        """fit | marginal | unfit, with the reasons attached via verdict_reasons."""
        reasons = self.verdict_reasons()
        if any(r.startswith("BLOCK") for r in reasons):
            return "unfit"
        if any(r.startswith("WARN") for r in reasons):
            return "marginal"
        return "fit"

    def verdict_reasons(self) -> List[str]:
        """Explicit, ordered reasons behind the verdict."""
        reasons: List[str] = []

        if not self.closed_cycles:
            reasons.append("BLOCK: no completed wheel cycle in the window")
            return reasons

        # Check activity before performance: a return earned on 3% of the days
        # is not a verdict about the strategy, it is a verdict about whether the
        # strategy can trade this symbol at all.
        if self.decision_days and self.days_in_position_fraction < MIN_DAYS_IN_POSITION:
            reasons.append(
                f"BLOCK: held a position on only {self.days_in_position} of "
                f"{self.decision_days} decision days "
                f"({self.days_in_position_fraction:.0%}) — the strategy cannot "
                f"consistently trade this symbol, so the return below is not a "
                f"meaningful sample"
            )

        if self.total_pnl <= 0:
            reasons.append(f"BLOCK: strategy lost money ({self.total_return:+.2%})")

        # An absolute floor, not just a relative one. Beating buy-and-hold over a
        # short window is close to a coin flip, so without this a symbol can read
        # FIT on a result that loses to cash.
        aroc = self.annualized_return_on_collateral
        if aroc is not None and 0 < self.total_pnl and aroc < RISK_FREE_RATE:
            reasons.append(
                f"BLOCK: {aroc:+.2%} annualized on committed collateral is below "
                f"the {RISK_FREE_RATE:.1%} risk-free rate — the capital would "
                f"have earned more sitting in T-bills"
            )

        if self.excess_return is not None and self.excess_return < 0:
            reasons.append(
                f"WARN: underperformed buy-and-hold by {abs(self.excess_return):.2%}"
            )

        share = self.option_pnl_share
        if share is not None and share < 0.25:
            reasons.append(
                f"WARN: only {share:.0%} of gross P&L came from premium — "
                "this is mostly a long-stock position"
            )

        # Threshold set against what account equity can actually move. With
        # max_position_size 0.35 and one open position per symbol, a -20% gate
        # was arithmetically unreachable — inert, not conservative.
        if self.max_drawdown < MAX_DRAWDOWN_WARN:
            reasons.append(
                f"WARN: max account drawdown {self.max_drawdown:.1%} "
                f"(on peak collateral of ${self.peak_collateral:,.0f})"
            )

        # Both sides of this ratio must be decision days; self.days is calendar
        # days, which understated the fraction by ~30% and made the gate harder
        # to trip on the wheel's self-declared signature failure mode.
        if self.decision_days:
            underwater_fraction = self.days_underwater / self.decision_days
            if underwater_fraction > 0.30:
                reasons.append(
                    f"WARN: held shares below cost basis on {self.days_underwater} "
                    f"of {self.decision_days} decision days "
                    f"({underwater_fraction:.0%})"
                )

        if not reasons:
            reasons.append("OK: profitable, beat buy-and-hold, premium-driven")
        return reasons


def compute_fitness(
    symbol: str,
    daily: Sequence[DailyState],
    cycles: Sequence[WheelCycle],
    starting_cash: float,
    *,
    benchmark_prices: Optional[Dict[date, float]] = None,
    data_quality: Optional[Dict] = None,
    rolls: int = 0,
) -> FitnessReport:
    """Assemble the scorecard from the equity curve and the cycle table."""
    if not daily:
        raise ValueError("cannot compute fitness with an empty equity curve")

    report = FitnessReport(
        symbol=symbol,
        start=daily[0].day,
        end=daily[-1].day,
        starting_cash=starting_cash,
        final_equity=daily[-1].equity,
        cycles=list(cycles),
        rolls=rolls,
        data_quality=dict(data_quality or {}),
    )

    for cycle in cycles:
        report.option_pnl += cycle.option_pnl
        report.stock_pnl += cycle.stock_pnl
        report.dividends += cycle.dividends
        report.fees += cycle.fees
        report.puts_sold += cycle.puts_sold
        report.calls_sold += cycle.calls_sold
        report.assignments += 1 if cycle.assigned else 0

    report.days_in_position = sum(
        1 for d in daily if d.open_options > 0 or any(v > 0 for v in d.shares_held.values())
    )
    report.unrealized_stock_pnl = _unrealized_stock_pnl(daily, cycles, benchmark_prices or {})
    collaterals = [d.reserved_collateral for d in daily]
    deployed = [c for c in collaterals if c > 0]
    report.avg_collateral = sum(deployed) / len(deployed) if deployed else 0.0
    report.peak_collateral = max(collaterals) if collaterals else 0.0

    equity = [d.equity for d in daily]
    report.max_drawdown = _max_drawdown(equity)
    report.sharpe, report.sortino = _risk_ratios(equity)
    report.days_underwater = _days_underwater(daily, cycles, benchmark_prices or {})

    if benchmark_prices:
        report.benchmark = _buy_and_hold(daily, benchmark_prices, starting_cash)

    return report


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #
def _max_drawdown(equity: Sequence[float]) -> float:
    """Largest peak-to-trough decline, as a negative fraction."""
    peak, worst = -math.inf, 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value - peak) / peak)
    # Collapse -0.0 (and sub-basis-point noise) to 0.0 so reports don't print
    # "-0.00%", which reads as a real but tiny loss rather than none at all.
    return 0.0 if worst > -1e-9 else worst


def _risk_ratios(equity: Sequence[float]) -> tuple:
    """Annualized Sharpe and Sortino from the daily equity curve (rf = 0)."""
    if len(equity) < 3:
        return 0.0, 0.0
    returns = [
        (equity[i] - equity[i - 1]) / equity[i - 1]
        for i in range(1, len(equity))
        if equity[i - 1] > 0
    ]
    if len(returns) < 2:
        return 0.0, 0.0

    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    stdev = math.sqrt(variance)
    scale = math.sqrt(TRADING_DAYS_PER_YEAR)
    sharpe = (mean / stdev) * scale if stdev > 0 else 0.0

    downside = [r for r in returns if r < 0]
    if downside:
        dvar = sum(r * r for r in downside) / len(downside)
        dstd = math.sqrt(dvar)
        sortino = (mean / dstd) * scale if dstd > 0 else 0.0
    else:
        sortino = 0.0
    return sharpe, sortino


def _days_underwater(
    daily: Sequence[DailyState],
    cycles: Sequence[WheelCycle],
    prices: Dict[date, float],
) -> int:
    """Days holding assigned shares while the price sits below cost basis.

    The wheel's signature failure mode: assignment converts a premium trade into
    a long position that can sit underwater for months, unable to sell calls
    above basis. AMZN's 62-day drawdown pause is the live existence proof.
    """
    if not prices:
        return 0
    # Keyed by (underlying, day), not day: a multi-symbol run holding two
    # assigned names on the same date would otherwise have one basis silently
    # overwrite the other. `prices` is single-symbol today, so only days where
    # that symbol is held can count.
    underwater_days = set()
    for cycle in cycles:
        if cycle.cost_basis is None:
            continue
        stop = cycle.end or daily[-1].day
        for state in daily:
            if not (cycle.start <= state.day <= stop):
                continue
            if state.shares_held.get(cycle.underlying, 0) <= 0:
                continue
            price = prices.get(state.day)
            if price is not None and price < cycle.cost_basis:
                underwater_days.add((cycle.underlying, state.day))

    return len(underwater_days)


def _unrealized_stock_pnl(
    daily: Sequence[DailyState],
    cycles: Sequence[WheelCycle],
    prices: Dict[date, float],
) -> float:
    """Mark still-held assigned shares to the final close.

    A cycle open at the end of the window holds real shares whose gain or loss
    is already inside ``final_equity``. Leaving it out of attribution makes the
    rows disagree with the headline return — and understates the stock leg
    exactly when it matters most.
    """
    if not prices or not daily:
        return 0.0
    final_day = daily[-1].day
    final_prices = prices
    total = 0.0
    for cycle in cycles:
        if not cycle.is_open or cycle.cost_basis is None:
            continue
        shares = daily[-1].shares_held.get(cycle.underlying, 0)
        if shares <= 0:
            continue
        price = final_prices.get(final_day)
        if price is None:
            continue
        total += (price - cycle.cost_basis) * shares
    return total


def _buy_and_hold(
    daily: Sequence[DailyState], prices: Dict[date, float], starting_cash: float
) -> Optional[BuyAndHold]:
    """Whole shares bought at the first close, held to the last."""
    entry_day, exit_day = daily[0].day, daily[-1].day
    entry = prices.get(entry_day)
    exit_ = prices.get(exit_day)
    if not entry or not exit_ or entry <= 0:
        return None
    shares = int(starting_cash // entry)
    if shares <= 0:
        return None
    return BuyAndHold(
        shares=shares, entry_price=entry, exit_price=exit_, starting_cash=starting_cash
    )
