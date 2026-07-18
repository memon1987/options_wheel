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
    ("Bid/ask is modeled", (
        "Alpaca sells no historical option quotes at any price, so spreads come "
        "from a calibrated model, not observation. Fills use mid minus a haircut; "
        "see the fill-sensitivity section for the bid-fill worst case.")),
    ("Greeks are computed", (
        "IV and delta are Black-Scholes inversions from the bar close, not "
        "published values.")),
    ("One decision per day", (
        "The live bot scans three times daily; the replay decides once at the "
        "close. Intraday profit-target touches are taken late, which is "
        "conservative.")),
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
    a(f"Annualized: {report.annualized_return:+.2%}")
    a("")

    # ---- Attribution: the flagship number ----------------------------------
    a("## Attribution — where the money came from")
    a("")
    a("| leg | P&L |")
    a("|---|---:|")
    a(f"| Option premium (net of buybacks) | ${report.option_pnl:+,.2f} |")
    a(f"| Stock (realized) | ${report.stock_pnl:+,.2f} |")
    a(f"| Dividends | ${report.dividends:+,.2f} |")
    a(f"| Fees | ${-report.fees:,.2f} |")
    a(f"| **Total** | **${report.total_pnl:+,.2f}** |")
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
        a(f"- Capital deployed on **{report.days_in_position} of "
          f"{report.decision_days}** decision days (**{report.utilization:.0%}** "
          f"utilization)")
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
    a(f"- Max drawdown: **{report.max_drawdown:.2%}**")
    a(f"- Sharpe {report.sharpe:.2f} · Sortino {report.sortino:.2f}")
    underwater_pct = (report.days_underwater / report.days) if report.days else 0.0
    a(f"- Days holding shares below cost basis: **{report.days_underwater}** "
      f"({underwater_pct:.0%} of the window) — the wheel's signature failure mode")
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
            "stock_pnl": report.stock_pnl,
            "dividends": report.dividends,
            "fees": report.fees,
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
            "utilization": report.utilization,
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
