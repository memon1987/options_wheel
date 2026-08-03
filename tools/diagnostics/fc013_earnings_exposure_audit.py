#!/usr/bin/env python3
"""FC-013 earnings-exposure audit: what did the book actually trade into earnings?

Purpose
-------
Two jobs, one script:

1. **Pre-build gate for FC-013** (`docs/plans/fc-013.md` §Approach 6). No earnings
   gate has ever existed on any path that opens a position, so the blackout window
   value ``earnings.blackout_days`` has to be chosen on evidence rather than
   inherited. This joins every historical option sell-to-open fill against the
   committed point-in-time earnings table and reports, for each candidate window
   N, how many fills it would have blocked, what those fills earned, and whether
   it blocks the two incidents on record (DD-3's binding acceptance criterion).
2. **Recurring detective query.** Once the gate ships, re-running this answers
   "did anything trade inside a window this week?" — which matters because the
   log sink to BigQuery is dead and Cloud Logging events age out in 30 days.

How to re-run
-------------
    python tools/diagnostics/fc013_earnings_exposure_audit.py
    python tools/diagnostics/fc013_earnings_exposure_audit.py --csv /tmp/fills.csv

Needs BigQuery read access (ADC or GOOGLE_APPLICATION_CREDENTIALS) to
``options_wheel.trades_from_activities`` and ``options_wheel.trades_with_outcomes``.
Read-only: it issues SELECTs and writes nothing back.

The earnings side comes from the committed table
(``src/backtesting/data/earnings_dates.json``) via ``HistoricalEarningsCalendar``,
not Finnhub — reproducible, no network, and point-in-time correct for old fills.
**Refresh the table before trusting a run** (``tools/backtesting/fetch_earnings_table.py``):
a symbol whose table dates have all gone past answers "no earnings" and would
silently undercount exposure. The script reports past-horizon fills for exactly
this reason.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from typing import Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.backtesting.engine.historical_earnings import (  # noqa: E402
    EARNINGS_TABLE_PATH,
    HistoricalEarningsCalendar,
)
from src.utils import clock  # noqa: E402

DEFAULT_PROJECT = "gen-lang-client-0607444019"
DEFAULT_DATASET = "options_wheel"

# The candidate blackout windows on the operator's menu (FC-013 DD-3). N=7 is
# included because for a uniform 7-DTE book "earnings within 7 days" and
# "expiry >= earnings date" converge — N=7 is the span predicate as a knob value.
N_BUCKETS = (1, 2, 3, 5, 7)

# The two incidents FC-013 exists to prevent. The chosen configuration must block
# both (DD-3 acceptance criterion), so a run that cannot find them is a broken
# join, not an absence of incidents.
# An incident is identified by (underlying, leg, the earnings event it was opened
# ahead of) — NOT by a calendar window around the fill. Windowing alone sweeps in
# post-earnings fills from the same week, whose next earnings is a quarter out;
# those are deliberately allowed (DD-3: post-earnings is IV-crush territory) and
# would corrupt the "smallest N that blocks this" arithmetic.
INCIDENTS = (
    {
        "name": "GOOGL put, opened ahead of 2026-04-29 earnings",
        "underlying": "GOOGL",
        "option_type": "put",
        "earnings_date": date(2026, 4, 29),
        "window": (date(2026, 4, 20), date(2026, 4, 29)),
    },
    {
        "name": "AAPL covered call, opened ahead of 2026-07-30 earnings",
        "underlying": "AAPL",
        "option_type": "call",
        "earnings_date": date(2026, 7, 30),
        "window": (date(2026, 7, 20), date(2026, 7, 30)),
    },
)

FILLS_SQL = """
SELECT activity_id, symbol, underlying, option_type, side, qty, price,
       premium_total, strike_price, expiration,
       DATE(transaction_time, 'America/New_York') AS fill_date
FROM `{project}.{dataset}.trades_from_activities`
WHERE activity_type = 'FILL'
  AND option_type IS NOT NULL
  AND side IN ('sell_short', 'sell')
ORDER BY transaction_time
"""

OUTCOMES_SQL = """
SELECT activity_id, outcome, realized_pnl
FROM `{project}.{dataset}.trades_with_outcomes`
"""


# --------------------------------------------------------------------------- #
# Earnings joins
# --------------------------------------------------------------------------- #
def annotate(df, calendar: HistoricalEarningsCalendar, empty_symbols: set):
    """Add days_to_next_earnings / spans_earnings / data-quality flags per fill.

    Every lookup runs under a clock frozen to the fill date, so the calendar
    answers as of that day — the same seam the replay uses, not today's answer.
    """
    days: List[Optional[int]] = []
    spans: List[Optional[bool]] = []
    next_dates: List[Optional[str]] = []
    quality: List[str] = []

    for row in df.itertuples(index=False):
        fill_date = row.fill_date
        symbol = row.underlying
        with clock.frozen(datetime(fill_date.year, fill_date.month, fill_date.day)):
            nxt = calendar.next_earnings_date(symbol)

        if nxt is None:
            days.append(None)
            spans.append(None)
            next_dates.append(None)
            if symbol in empty_symbols:
                quality.append("no_earnings_by_nature")      # ETF, legitimately clear
            elif symbol in calendar.symbols_without_data:
                quality.append("symbol_absent_from_table")   # fail-open gap
            else:
                quality.append("past_table_horizon")         # silent fail-open edge
            continue

        days.append((nxt - fill_date).days)
        # spans_earnings == any(fill_date <= e <= expiration); nxt is by
        # construction the first e >= fill_date, so comparing it suffices.
        spans.append(row.expiration is not None and nxt <= row.expiration)
        next_dates.append(nxt.isoformat())
        quality.append("ok")

    import pandas as pd

    df = df.copy()
    df["next_earnings_date"] = next_dates
    # Nullable Int64, not float: a missing day-count is missing, not NaN-as-1.0.
    df["days_to_next_earnings"] = pd.array(days, dtype="Int64")
    df["spans_earnings"] = spans
    df["earnings_data_quality"] = quality
    return df


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def _pnl_summary(sub) -> str:
    """Realized-P&L line for a subset: only closed positions carry realized P&L."""
    closed = sub[sub["realized_pnl"].notna()]
    if closed.empty:
        return f"{len(sub):>4} fills, {0:>4} closed  —  no realized P&L yet"
    total = closed["realized_pnl"].sum()
    avg = closed["realized_pnl"].mean()
    wins = (closed["realized_pnl"] > 0).sum()
    return (f"{len(sub):>4} fills, {len(closed):>4} closed  "
            f"total ${total:>10,.2f}  avg ${avg:>8,.2f}  "
            f"win rate {wins / len(closed):>5.1%}")


def report(df, calendar_meta: Dict) -> None:
    out = print
    out("=" * 86)
    out("FC-013 EARNINGS EXPOSURE AUDIT")
    out("=" * 86)
    out(f"Earnings table : {EARNINGS_TABLE_PATH}")
    out(f"  generated    : {calendar_meta.get('generated')} "
        f"(source: {calendar_meta.get('source')})")
    out(f"  symbols      : {calendar_meta['n_symbols']} "
        f"({calendar_meta['n_empty']} with no earnings by nature: "
        f"{', '.join(sorted(calendar_meta['empty_symbols'])) or '—'})")
    out(f"Fills          : {len(df)} option sell-to-open fills, "
        f"{df['fill_date'].min()} -> {df['fill_date'].max()}")
    out(f"  by leg       : " + ", ".join(
        f"{k}={v}" for k, v in sorted(df["option_type"].value_counts().items())))
    out(f"  by side      : " + ", ".join(
        f"{k}={v}" for k, v in sorted(df["side"].value_counts().items())))

    # ---- data quality -----------------------------------------------------
    out("")
    out("-- DATA QUALITY " + "-" * 70)
    for flag, n in sorted(df["earnings_data_quality"].value_counts().items()):
        out(f"  {flag:<26} {n:>5} fills")
    off_nominal = df[~df["earnings_data_quality"].isin(["ok", "no_earnings_by_nature"])]
    if not off_nominal.empty:
        out("  ** fills the calendar could not place (gate would fail OPEN in replay,"
            " and these are NOT counted in any bucket below):")
        for underlying, sub in off_nominal.groupby("underlying"):
            out(f"     {underlying:<7} {len(sub):>4} fills  "
                f"{sub['fill_date'].min()} -> {sub['fill_date'].max()}")
    unclosed = df["realized_pnl"].isna().sum()
    out(f"  fills with no outcome row (still open / unmatched): {unclosed}")

    # ---- exposure buckets -------------------------------------------------
    placed = df[df["days_to_next_earnings"].notna()]
    out("")
    out("-- EXPOSURE BY BLACKOUT WINDOW N (0 <= days_until <= N) " + "-" * 30)
    out(f"  BOOK BASELINE            {_pnl_summary(df)}")
    out("")
    for leg in ("all", "put", "call"):
        scope = placed if leg == "all" else placed[placed["option_type"] == leg]
        out(f"  [{leg}]  {len(scope)} fills the calendar could place")
        for n in N_BUCKETS:
            sub = scope[scope["days_to_next_earnings"] <= n]
            out(f"    N={n:<2}  {_pnl_summary(sub)}")
        span = scope[scope["spans_earnings"] == True]  # noqa: E712
        out(f"    SPAN  {_pnl_summary(span)}   (expiry >= next earnings date)")
        out("")

    # ---- the incidents ----------------------------------------------------
    out("-- INCIDENTS ON RECORD (DD-3 acceptance criterion) " + "-" * 35)
    blocking_ns: List[set] = []
    for incident in INCIDENTS:
        lo, hi = incident["window"]
        sub = df[(df["underlying"] == incident["underlying"])
                 & (df["option_type"] == incident["option_type"])
                 & (df["fill_date"] >= lo) & (df["fill_date"] <= hi)
                 & (df["next_earnings_date"] == incident["earnings_date"].isoformat())]
        if sub.empty:
            raise SystemExit(
                f"FATAL: incident not found in the fills pull — {incident['name']}. "
                "A missing incident means the join is wrong, not that it did not "
                "happen. Fix the query before reading any number above."
            )
        # The pinned incident fill is the one closest to the event; any other
        # fills ahead of the same event are printed as context.
        sub = sub.sort_values("days_to_next_earnings")
        pinned = sub.iloc[0]
        out(f"  {incident['name']}")
        for i, row in enumerate(sub.itertuples(index=False)):
            pnl = ("n/a" if row.realized_pnl != row.realized_pnl
                   else f"${row.realized_pnl:,.2f}")
            out(f"    {'*' if i == 0 else ' '} {row.symbol:<22} filled {row.fill_date}  "
                f"earnings {row.next_earnings_date}  "
                f"days_until={row.days_to_next_earnings:>2}  "
                f"expiry {row.expiration}  spans={row.spans_earnings}  "
                f"premium ${row.premium_total:>8,.2f}  realized {pnl}")
        pinned_days = int(pinned["days_to_next_earnings"])
        blocking_ns.append({n for n in N_BUCKETS if n >= pinned_days})
        out(f"    -> pinned fill (*) at days_until={pinned_days}: blocked by N >= "
            f"{pinned_days}   (span predicate blocks it: {bool(pinned['spans_earnings'])})")
        if len(sub) > 1:
            widest = int(sub["days_to_next_earnings"].max())
            out(f"    -> blocking EVERY fill opened ahead of this event needs "
                f"N >= {widest} ({len(sub)} fills)")

    both = set.intersection(*blocking_ns) if blocking_ns else set()
    out("")
    out(f"  N values from {list(N_BUCKETS)} that block BOTH incidents: "
        f"{sorted(both) if both else 'NONE — escalate to the span predicate'}")
    out("=" * 86)


# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--table", default=EARNINGS_TABLE_PATH,
                        help="Committed earnings table to join against.")
    parser.add_argument("--csv", help="Optional path to dump the annotated fills "
                                      "(keep it out of the repo).")
    args = parser.parse_args()

    import pandas as pd
    from google.cloud import bigquery  # imported late: not needed to read --help

    client = bigquery.Client(project=args.project)

    def frame(sql: str):
        # Rows are materialized by hand rather than via to_dataframe(): the
        # latter needs the optional db-dtypes package for DATE columns, which
        # this repo does not carry. Native date objects are what the join wants
        # anyway.
        rows = client.query(sql.format(project=args.project,
                                       dataset=args.dataset)).result()
        return pd.DataFrame([dict(r.items()) for r in rows])

    fills = frame(FILLS_SQL)
    outcomes = frame(OUTCOMES_SQL)

    if fills.empty:
        print("FATAL: no option sell fills returned.", file=sys.stderr)
        return 1

    # Every matched row should be a sell-to-OPEN: this strategy holds no long
    # options to sell-to-close. Report rather than silently miscount.
    odd = fills[fills["side"] != "sell_short"]
    if not odd.empty:
        print(f"WARNING: {len(odd)} fill(s) with side != 'sell_short' — verify these "
              f"are opens, not closes: {sorted(set(odd['symbol']))[:10]}",
              file=sys.stderr)

    fills = fills.merge(outcomes, on="activity_id", how="left")

    with open(args.table) as fh:
        payload = json.load(fh)
    empty_symbols = {s for s, d in payload["earnings"].items() if not d}
    calendar = HistoricalEarningsCalendar.from_table(args.table)

    annotated = annotate(fills, calendar, empty_symbols)
    report(annotated, {
        "generated": payload.get("generated"),
        "source": payload.get("source"),
        "n_symbols": len(payload["earnings"]),
        "n_empty": len(empty_symbols),
        "empty_symbols": empty_symbols,
    })

    if args.csv:
        annotated.to_csv(args.csv, index=False)
        print(f"\nAnnotated fills written to {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
