#!/usr/bin/env python3
"""Build the static dividend table the backtest replays against.

Mirrors ``fetch_earnings_table.py``: an operator runs this, the output is
committed, and a replay reads the committed table with no network access.

**Source is Alpaca's corporate-actions endpoint, not yfinance** — a deliberate
departure from the earnings table, for one reason. The engine replays against
unadjusted bars and as-listed strikes, so dividend amounts must also be
as-declared. yfinance back-adjusts dividends through later splits; Alpaca does
not. Measured on NVDA, whose 10:1 split landed 2024-06-10:

    ex-date      yfinance   Alpaca   actually paid
    2023-03-07   0.004      0.04     0.04
    2024-03-05   0.004      0.04     0.04

Using yfinance would have understated pre-split NVDA dividends by 10x. NVDA's
dividend is immaterial in absolute terms, but the same mechanism applies to any
symbol that splits inside the window, and the failure is silent.

The endpoint is called over plain ``requests`` rather than through alpaca-py:
corporate actions moved between SDK versions and this is a build-time operator
tool, so pinning to the wire format is the more stable choice.

Coverage check as of 2026-07-18 over the 14-symbol universe: 12 payers
(AAPL, F, GOOGL, IWM, KMI, MSFT, NVDA, PFE, QQQ, SPY, UNH, VZ) and 2 genuine
non-payers (AMD, AMZN), both recorded as empty lists so the reader can tell
"pays nothing" apart from "not in the table".

Usage:
    python tools/backtesting/fetch_dividend_table.py
    python tools/backtesting/fetch_dividend_table.py --symbols KMI VZ --since 2023-01-01
"""

import argparse
import collections
import json
import os
import sys
from datetime import date, datetime

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.backtesting.data.dividends import DIVIDEND_TABLE_PATH  # noqa: E402
from src.utils.config import Config  # noqa: E402

CORPORATE_ACTIONS_URL = "https://data.alpaca.markets/v1/corporate-actions"

# Symbols with no dividend history at all. Distinguishing "we asked and the
# answer is none" from "we never asked" is the whole point of recording these:
# the reader treats an absent symbol as unknown and a present-but-empty one as
# a confirmed non-payer.
KNOWN_NON_PAYERS_NOTE = (
    "Symbols present with an empty list pay no dividend over the window and were "
    "confirmed by the fetch, not skipped."
)


def fetch_cash_dividends(symbols, start: date, end: date, headers) -> dict:
    """All cash dividends for ``symbols`` in the window, keyed by symbol.

    Pages until exhausted; the endpoint caps a response at ``limit`` rows and a
    14-symbol multi-year pull exceeds one page.

    Note the endpoint filters on *process* date, not ex-date, so a handful of
    rows can come back with an ex-date just before ``start`` (a dividend that
    went ex in late December and settled in January). They are kept as-is: an
    ex-date outside every replay window is never read, and trimming them would
    risk dropping one that is inside the window at the far edge.
    """
    out = collections.defaultdict(list)
    page_token = None
    while True:
        params = {
            "symbols": ",".join(symbols),
            "types": "cash_dividend",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 1000,
        }
        if page_token:
            params["page_token"] = page_token
        response = requests.get(
            CORPORATE_ACTIONS_URL, params=params, headers=headers, timeout=30
        )
        response.raise_for_status()
        payload = response.json()
        for row in payload.get("corporate_actions", {}).get("cash_dividends", []):
            out[row["symbol"]].append(row)
        page_token = payload.get("next_page_token")
        if not page_token:
            break
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the backtest dividend table.")
    parser.add_argument("--symbols", nargs="*", help="Default: the config universe.")
    parser.add_argument(
        "--since",
        default="2023-01-01",
        help="Drop ex-dates before this (default 2023-01-01, a year before "
             "Alpaca's options history starts).",
    )
    parser.add_argument("--until", default=None, help="Default: today.")
    parser.add_argument("--out", default=DIVIDEND_TABLE_PATH)
    args = parser.parse_args()

    config = Config()
    symbols = args.symbols or config.stock_symbols
    since = datetime.strptime(args.since, "%Y-%m-%d").date()
    until = (
        datetime.strptime(args.until, "%Y-%m-%d").date() if args.until else date.today()
    )

    headers = {
        "APCA-API-KEY-ID": config.alpaca_api_key,
        "APCA-API-SECRET-KEY": config.alpaca_secret_key,
    }
    if not headers["APCA-API-KEY-ID"] or not headers["APCA-API-SECRET-KEY"]:
        print("Alpaca credentials are required to BUILD the table (not to read "
              "it): set ALPACA_API_KEY / ALPACA_SECRET_KEY.", file=sys.stderr)
        return 1

    try:
        raw = fetch_cash_dividends(symbols, since, until, headers)
    except requests.RequestException as exc:  # noqa: BLE001 - operator tool
        print(f"FATAL: corporate-actions fetch failed: {exc}", file=sys.stderr)
        return 1

    table, non_payers, specials = {}, [], 0
    for symbol in symbols:
        rows = sorted(raw.get(symbol, []), key=lambda r: r["ex_date"])
        entries = []
        for row in rows:
            rate = float(row.get("rate") or 0.0)
            if rate <= 0:
                continue
            entries.append(
                {
                    "ex_date": row["ex_date"],
                    "amount": rate,
                    "special": bool(row.get("special", False)),
                }
            )
            specials += 1 if row.get("special") else 0
        table[symbol] = entries
        if not entries:
            non_payers.append(symbol)
            print(f"{symbol:<7}   — no dividends in window (recorded as empty)")
        else:
            total = sum(e["amount"] for e in entries)
            print(f"{symbol:<7} {len(entries):>3} ex-dates  "
                  f"{entries[0]['ex_date']} -> {entries[-1]['ex_date']}  "
                  f"${total:.2f}/share total")

    if all(not v for v in table.values()):
        print("\nFATAL: every symbol came back empty — that is a fetch failure, "
              "not a universe of non-payers. Not writing the table.",
              file=sys.stderr)
        return 1

    payload = {
        "generated": date.today().isoformat(),
        "source": "Alpaca /v1/corporate-actions (types=cash_dividend)",
        "since": since.isoformat(),
        "until": until.isoformat(),
        "note": (
            "Amounts are as-declared per share, NOT split-adjusted, matching the "
            "unadjusted bars and as-listed strikes the engine replays against. "
            "ETF rows (SPY/QQQ/IWM) are fund distributions, which bundle passed-"
            "through dividend income with year-end capital-gains distributions; "
            "the cash flow is identical, the composition is not. "
            + KNOWN_NON_PAYERS_NOTE
        ),
        "dividends": table,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)

    payers = len(table) - len(non_payers)
    print(f"\nWrote {len(table)} symbols to {args.out} "
          f"({payers} payers, {len(non_payers)} non-payers"
          + (f", {specials} special dividends" if specials else "") + ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
