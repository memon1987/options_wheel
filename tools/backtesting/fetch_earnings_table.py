#!/usr/bin/env python3
"""Build the static historical earnings table the backtest replays against.

Live earnings gating calls Finnhub, whose tier we hold has no historical
calendar — it answers "when is the *next* earnings date", which is useless when
replaying 2024. So the backtest reads a static table instead, and this tool
builds it.

Source is yfinance (already a declared dependency), which returns quarterly
earnings dates back to ~2014 for our universe. Run it when adding a symbol or
extending the window; the table is committed, so a replay needs no network and
no yfinance import at runtime.

Known limitation, deliberately accepted: these are dates as known *today*,
including any subsequently-revised or -confirmed dates, so a replay can "know" an
earnings date slightly earlier than the live bot did. The only consumer is the
rolling blackout (``rolling_earnings_blackout_days``, currently 2), so the blast
radius is a handful of Friday roll decisions per symbol-year. Recorded in the
report footer rather than silently ignored.

Usage:
    python tools/backtesting/fetch_earnings_table.py
    python tools/backtesting/fetch_earnings_table.py --symbols NVDA AMD --since 2023-01-01
"""

import argparse
import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.backtesting.engine.historical_earnings import EARNINGS_TABLE_PATH  # noqa: E402
from src.utils.config import Config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the backtest earnings table.")
    parser.add_argument("--symbols", nargs="*", help="Default: the config universe.")
    parser.add_argument("--since", default="2023-01-01",
                        help="Drop earnings before this date (default 2023-01-01, "
                             "a year before Alpaca's options history starts).")
    parser.add_argument("--out", default=EARNINGS_TABLE_PATH)
    args = parser.parse_args()

    try:
        import yfinance as yf
    except ImportError:
        print("yfinance is required to BUILD the table (not to read it): "
              "pip install 'yfinance>=0.2.18,<1.0.0' lxml", file=sys.stderr)
        return 1

    symbols = args.symbols or Config().stock_symbols
    since = datetime.strptime(args.since, "%Y-%m-%d").date()

    table, failures, etfs = {}, [], []
    for symbol in symbols:
        ticker = yf.Ticker(symbol)
        try:
            df = ticker.get_earnings_dates(limit=60)
        except Exception as exc:  # noqa: BLE001 - operator tool
            print(f"{symbol:<7} FAILED: {str(exc)[:80]}")
            failures.append(symbol)
            continue

        if df is None or not len(df):
            # An ETF has no earnings by nature — that is a real, complete answer,
            # not a fetch failure. Recording it as an empty list lets the gate
            # correctly return "no earnings" instead of "no data, fail open".
            if _is_etf(ticker):
                table[symbol] = []
                etfs.append(symbol)
                print(f"{symbol:<7}   — ETF, no earnings (recorded as empty)")
            else:
                print(f"{symbol:<7} no earnings rows returned")
                failures.append(symbol)
            continue

        dates = sorted({d.date().isoformat() for d in df.index if d.date() >= since})
        table[symbol] = dates
        print(f"{symbol:<7} {len(dates):>3} earnings dates  "
              f"{dates[0] if dates else '—'} -> {dates[-1] if dates else '—'}")

    if not table:
        print("\nFATAL: no symbol produced earnings dates; not writing the table.",
              file=sys.stderr)
        return 1

    payload = {
        "generated": date.today().isoformat(),
        "source": "yfinance Ticker.get_earnings_dates",
        "since": since.isoformat(),
        "note": ("Dates as known at generation time; may include revisions the live "
                 "bot could not have seen. Consumer is the rolling earnings blackout."),
        "earnings": table,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)
    print(f"\nWrote {len(table)} symbols to {args.out}"
          + (f" ({len(etfs)} ETFs with no earnings: {', '.join(etfs)})" if etfs else ""))
    if failures:
        print(f"WARNING: {len(failures)} symbol(s) MISSING and will fail open "
              f"during replay: {', '.join(failures)}")
        return 1
    return 0


def _is_etf(ticker) -> bool:
    """Whether yfinance classifies this as a fund rather than an operating company."""
    try:
        quote_type = (ticker.info or {}).get("quoteType", "")
    except Exception:  # noqa: BLE001 - yfinance raises assorted things offline
        return False
    return str(quote_type).upper() in {"ETF", "MUTUALFUND", "INDEX"}


if __name__ == "__main__":
    raise SystemExit(main())
