"""Markdown + JSON rendering of a fitness report.

The report's job is to be *hard to misread*. Three things it always does:

- shows option-leg and stock-leg P&L apart, never only their sum;
- states the buy-and-hold result next to the strategy result;
- carries a footer of known biases, so a reader never has to guess whether a
  number is measured, modeled, or unmodeled.

Numbers come pre-computed from ``metrics.fitness``; nothing is calculated here
beyond formatting.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import List, Optional

from ..metrics.cycles import WheelCycle
from ..metrics.fitness import FitnessReport

# Biases we know about and have chosen not to model. Printed on every report:
# an unlisted caveat is one the reader will assume does not exist.
KNOWN_BIASES = [
    ("Premium understated ~7-20%", (
        "Option marks come from daily bar closes (trade prints), while the live "
        "bot fills intraday against real quotes. Measured against 202 real "
        "decisions: identical contracts price ~7% below live's fill, rising to "
        "~20% once contract selection differs. Conservative — the strategy's "
        "true premium capture is higher than reported.")),
    ("Bid/ask is modeled, not calibrated", (
        "Alpaca sells no historical option quotes at any price, so spreads come "
        "from a parametric model running on its DEFAULT parameters — "
        "SpreadModel.calibrate() exists but is never invoked on this path. "
        "Measured against 455 live OTM put quotes by "
        "tools/diagnostics/spread_model_check.py (re-runnable): median real "
        "half-spread $0.0300 vs $0.0635 modeled, i.e. the model is ~2.1x wider, "
        "and wider on 80% of contracts — which errs against the strategy. BUT "
        "that sample was taken OUTSIDE regular trading hours, when real spreads "
        "are at their widest; intraday the gap narrows and the model may not be "
        "conservative at all on the most liquid names. Treat 'conservative' as "
        "unproven intraday rather than established.")),
    ("Greeks are computed", (
        "IV and delta are Black-Scholes inversions from the bar close, not "
        "published values. Dividend yield is treated as zero for every symbol, "
        "which is immaterial at ~7 DTE but not free.")),
    ("Dividends are NOT modeled — and the bias runs BOTH ways", (
        "No dividend is credited to either leg, and the direction of that bias "
        "is not uniform; stating only one side of it is worse than stating "
        "none. It FLATTERS the wheel on the buy-and-hold comparison (a WARN): "
        "the benchmark holds shares every day and forgoes the entire dividend "
        "stream, worth ~15 points on a 6.5% yielder over 2.4 years. But it "
        "PENALISES the wheel on total return and return-on-collateral — the "
        "absolute gates that actually produce an 'unfit' verdict — because "
        "real dividends earned while holding assigned shares are simply "
        "missing. On a 5-7% yielder that alone can push annualized return "
        "under the 4% risk-free floor. So on the income names (F, PFE, KMI, "
        "VZ) the verdict is biased TOWARD unfit even though the headline "
        "benchmark line leans the other way. Do not judge a dividend payer on "
        "this engine until dividends are modeled.")),
    ("Early assignment is NOT modeled", (
        "Short ITM calls are held to expiry. A real short call whose remaining "
        "extrinsic value is less than an upcoming dividend is frequently "
        "assigned the day before the ex-date, so the replay keeps shares — and "
        "any later appreciation — that a live account would have lost. "
        "Optimistic, and concentrated on the same dividend payers as above.")),
    ("One decision per day, with zero decision-to-fill latency", (
        "The live bot scans three times daily; the replay decides once at the "
        "close. Production also splits scanning from execution across separate "
        "invocations minutes-to-hours apart, whereas the replay executes at the "
        "same instant and price it decided on — so the replay always gets the "
        "price it saw. Optimistic.")),
    ("Splits and other corporate actions are NOT modeled", (
        "Underlying bars are deliberately unadjusted, because historical option "
        "strikes are as-listed-at-the-time and never retroactively adjusted; "
        "adjusted bars would price a post-split underlying against pre-split "
        "strikes. A run whose window spans a split is REFUSED outright rather "
        "than reported.")),
    ("Single vol regime", (
        "Alpaca's option history starts 2024-02-01, so results cover one "
        "market regime. A shifted start date can flip a marginal verdict.")),
    ("Taxes not modeled", (
        "Wheel income is short-term gains; buy-and-hold defers to long-term. "
        "Published estimates put the drag at ~1-2%/yr, which the buy-and-hold "
        "comparison below does NOT deduct.")),
]


def render_markdown(report: FitnessReport) -> str:
    """Full human-readable report."""
    out: List[str] = []
    a = out.append

    a(f"# Wheel fitness: {report.symbol}")
    a("")
    a(f"**{report.start} → {report.end}** ({report.days} days) · "
      f"starting capital ${report.starting_cash:,.0f}")
    a("")

    verdict = report.verdict()
    badge = {"fit": "FIT", "marginal": "MARGINAL", "unfit": "UNFIT"}[verdict]
    a(f"## Verdict: {badge}")
    a("")
    for reason in report.verdict_reasons():
        a(f"- {reason}")
    a("")

    # Why the strategy stood down. A verdict that hides its own binding
    # constraint invites the wrong action: "this symbol is unfit" reads very
    # differently from "our gap filter excludes this symbol in high-vol regimes".
    blocked = report.data_quality.get("blocked_days_by_reason") or {}
    if blocked:
        candidates = report.data_quality.get("days_with_a_qualifying_candidate")
        a("### Why the strategy stood down")
        a("")
        a("| blocking reason | days |")
        a("|---|---:|")
        for reason, count in blocked.items():
            a(f"| {reason} | {count} |")
        a("")
        top = next(iter(blocked))
        a(f"The binding constraint was **{top}**.")
        if candidates is not None:
            a("")
            a(f"The chain was actually *examined* on **{candidates}** of "
              f"{report.decision_days} decision days and offered a qualifying "
              f"candidate on those. On the rest an earlier stage blocked first, "
              f"so this is NOT a count of days a tradeable option existed — "
              f"where the binding constraint sits upstream of stage 7, the "
              f"chain was never looked at.")
        a("")

    # ---- Headline: strategy vs the only benchmark that matters --------------
    a("## Strategy vs buy-and-hold")
    a("")
    a("| | total return | final value |")
    a("|---|---:|---:|")
    a(f"| Wheel | {report.total_return:+.2%} | ${report.final_equity:,.0f} |")
    if report.benchmark:
        b = report.benchmark
        a(f"| Buy & hold ({b.shares} sh @ ${b.entry_price:,.2f}) | "
          f"{b.total_return:+.2%} | ${b.final_value:,.0f} |")
        excess = report.excess_return or 0.0
        verdict_word = "ahead of" if excess >= 0 else "behind"
        a(f"| **Difference** | **{excess:+.2%}** | |")
        a("")
        a(f"The wheel finished **{abs(excess):.2%} {verdict_word}** simply owning "
          f"{report.symbol} over the same window.")
    else:
        a("")
        a("_Buy-and-hold benchmark unavailable (no price at window edges)._")
    a("")
    a(f"Annualized on the whole account: {report.annualized_return:+.2%}")
    aroc = report.annualized_return_on_collateral
    if aroc is not None:
        a("")
        a(f"**Annualized on committed collateral: {aroc:+.2%}** "
          f"(${report.avg_collateral:,.0f} average). This is the scale-free "
          f"number — the account figure above is diluted by the arbitrary "
          f"${report.starting_cash:,.0f} allocation and mostly measures idle cash.")
    a("")

    # ---- Attribution: the flagship number ----------------------------------
    a("## Attribution — where the money came from")
    a("")
    a("| leg | P&L |")
    a("|---|---:|")
    a(f"| Option premium (net of buybacks and fees) | ${report.option_pnl:+,.2f} |")
    a(f"| Stock — realized (called away) | ${report.stock_pnl:+,.2f} |")
    a(f"| Stock — unrealized (still held) | ${report.unrealized_stock_pnl:+,.2f} |")
    a(f"| Dividends _(not modeled — see biases)_ | ${report.dividends:+,.2f} |")
    a(f"| **Total** | **${report.attribution_total:+,.2f}** |")
    a("")
    a(f"_Memo: ${report.fees:,.2f} of fees is already deducted inside the option "
      f"row. Equity change over the window was ${report.total_pnl:+,.2f}._")
    if abs(report.reconciliation_gap) > 0.01:
        a("")
        a(f"> **Attribution does not reconcile** — the rows above sum to "
          f"${report.attribution_total:+,.2f} but equity moved "
          f"${report.total_pnl:+,.2f}, a gap of "
          f"${report.reconciliation_gap:+,.2f}. Some cash flow is unaccounted "
          f"for, so treat the split below as unreliable.")
    a("")
    share = report.option_pnl_share
    if share is None:
        a("Option and stock legs have opposite signs, so a percentage split would "
          "mislead — read the two rows above directly.")
    else:
        a(f"**{share:.0%} of gross P&L came from the option leg**, "
          f"{1 - share:.0%} from the stock leg.")
        if share < 0.25:
            a("")
            a("> This is mostly a long-stock position wearing a wheel costume. "
              "Published wheel studies find the same thing; the point of showing "
              "it is that it should change how you read the headline return.")
    a("")

    # ---- Cycles ------------------------------------------------------------
    a("## Cycles")
    a("")
    closed = report.closed_cycles
    a(f"- Completed cycles: **{len(closed)}** "
      f"({len(report.cycles) - len(closed)} still open at window end)")
    a(f"- Puts sold: {report.puts_sold} · calls sold: {report.calls_sold} · "
      f"rolls: {report.rolls}")
    if report.decision_days:
        a(f"- Held a position on **{report.days_in_position} of "
          f"{report.decision_days}** decision days "
          f"(**{report.days_in_position_fraction:.0%}**)")
        if report.avg_collateral > 0:
            a(f"- Average collateral committed while in a position: "
              f"**${report.avg_collateral:,.0f}** (peak ${report.peak_collateral:,.0f})")
    if report.win_rate is not None:
        a(f"- Win rate: **{report.win_rate:.0%}** "
          f"(expected to be high at 0.10-0.20 delta — read with the worst cycle below)")
    if report.assignment_rate is not None:
        a(f"- Assignment rate: {report.assignment_rate:.0%}")
    a("")
    a(_cycle_table(report.cycles))
    a("")

    worst = report.worst_cycle
    if worst is not None:
        a("### Worst cycle")
        a("")
        a(f"**{worst.underlying}**, {worst.start} → {worst.end} ({worst.days} days), "
          f"total **${worst.total_pnl:+,.2f}**")
        a("")
        a(f"- Option leg ${worst.option_pnl:+,.2f}, stock leg ${worst.stock_pnl:+,.2f}")
        if worst.assigned:
            a(f"- Assigned at ${worst.cost_basis:,.2f}"
              + (f", called away at ${worst.exit_price:,.2f}" if worst.called_away
                 else ", still holding at window end"))
        a("")

    # ---- Risk --------------------------------------------------------------
    a("## Risk")
    a("")
    a(f"- Max drawdown: **{report.max_drawdown:.2%}** _(of total account equity, "
      f"which is mostly idle cash — not of the position)_")
    a(f"- Sharpe {report.sharpe:.2f} · Sortino {report.sortino:.2f} "
      f"_(also on total equity; flattered by the idle-cash denominator, "
      f"so treat as relative-only)_")
    underwater_pct = (
        report.days_underwater / report.decision_days if report.decision_days else 0.0
    )
    a(f"- Days holding shares below cost basis: **{report.days_underwater}** of "
      f"{report.decision_days} decision days ({underwater_pct:.0%}) — the "
      f"wheel's signature failure mode")
    a("")

    if report.data_quality:
        a("## Data quality")
        a("")
        for key, value in sorted(report.data_quality.items()):
            a(f"- {key}: {value}")
        a("")

    # ---- Caveats -----------------------------------------------------------
    a("## Known biases in these numbers")
    a("")
    for title, detail in KNOWN_BIASES:
        a(f"- **{title}.** {detail}")
    a("")
    return "\n".join(out)


def _cycle_table(cycles: List[WheelCycle]) -> str:
    if not cycles:
        return "_No cycles._"
    rows = [
        "| # | start | end | days | puts | calls | option P&L | stock P&L | total | ann. | outcome |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for i, c in enumerate(cycles, 1):
        rows.append(
            f"| {i} | {c.start} | {c.end or '—'} | {c.days} | {c.puts_sold} | "
            f"{c.calls_sold} | ${c.option_pnl:+,.0f} | ${c.stock_pnl:+,.0f} | "
            f"${c.total_pnl:+,.0f} | {c.annualized_return:+.0%} | {c.outcome()} |"
        )
    return "\n".join(rows)


def render_json(report: FitnessReport, *, sensitivity: Optional[dict] = None) -> str:
    """Machine-readable form; the same numbers the markdown renders."""
    payload = {
        "symbol": report.symbol,
        "start": report.start.isoformat(),
        "end": report.end.isoformat(),
        "days": report.days,
        "verdict": report.verdict(),
        "verdict_reasons": report.verdict_reasons(),
        "starting_cash": report.starting_cash,
        "final_equity": report.final_equity,
        "total_pnl": report.total_pnl,
        "total_return": report.total_return,
        "annualized_return": report.annualized_return,
        "attribution": {
            "option_pnl": report.option_pnl,
            "stock_pnl_realized": report.stock_pnl,
            "stock_pnl_unrealized": report.unrealized_stock_pnl,
            "stock_pnl_total": report.total_stock_pnl,
            "dividends": report.dividends,
            "fees_memo": report.fees,
            "attribution_total": report.attribution_total,
            "reconciliation_gap": report.reconciliation_gap,
            "option_pnl_share": report.option_pnl_share,
        },
        "cycles": {
            "completed": len(report.closed_cycles),
            "open": len(report.cycles) - len(report.closed_cycles),
            "puts_sold": report.puts_sold,
            "calls_sold": report.calls_sold,
            "rolls": report.rolls,
            "win_rate": report.win_rate,
            "assignment_rate": report.assignment_rate,
            "table": [_cycle_json(c) for c in report.cycles],
        },
        "risk": {
            "max_drawdown": report.max_drawdown,
            "sharpe": report.sharpe,
            "sortino": report.sortino,
            "days_underwater": report.days_underwater,
        },
        "activity": {
            "decision_days": report.decision_days,
            "days_in_position": report.days_in_position,
            "days_in_position_fraction": report.days_in_position_fraction,
            "avg_collateral": report.avg_collateral,
            "peak_collateral": report.peak_collateral,
        },
        "benchmark": (
            {
                "shares": report.benchmark.shares,
                "entry_price": report.benchmark.entry_price,
                "exit_price": report.benchmark.exit_price,
                "total_return": report.benchmark.total_return,
                "final_value": report.benchmark.final_value,
                "excess_return": report.excess_return,
            }
            if report.benchmark
            else None
        ),
        "data_quality": report.data_quality,
        "known_biases": [{"title": t, "detail": d} for t, d in KNOWN_BIASES],
    }
    if sensitivity:
        payload["fill_sensitivity"] = sensitivity
    return json.dumps(payload, indent=2, default=_fallback)


def _cycle_json(c: WheelCycle) -> dict:
    return {
        "underlying": c.underlying,
        "start": c.start.isoformat(),
        "end": c.end.isoformat() if c.end else None,
        "days": c.days,
        "puts_sold": c.puts_sold,
        "calls_sold": c.calls_sold,
        "option_pnl": c.option_pnl,
        "stock_pnl": c.stock_pnl,
        "dividends": c.dividends,
        "total_pnl": c.total_pnl,
        "assigned": c.assigned,
        "called_away": c.called_away,
        "cost_basis": c.cost_basis,
        "exit_price": c.exit_price,
        "capital_at_risk": c.capital_at_risk,
        "annualized_return": c.annualized_return,
        "outcome": c.outcome(),
    }


def _fallback(obj):
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)
