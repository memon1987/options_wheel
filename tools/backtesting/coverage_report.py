#!/usr/bin/env python3
"""FC-032 Phase 1 data-coverage gate.

Runs the coverage report against real Alpaca data to answer the question that
drives the data-source decision (stay on free Alpaca vs buy ThetaData/ORATS):

    For each symbol, on what fraction of weekly decision days does Alpaca's
    trade-derived option history actually contain a usable put candidate in our
    0.10-0.20 delta band above the premium floor?

Requires Alpaca credentials (same as live trading), so it is run by the operator
in an environment with .env / Secret Manager configured, NOT in CI.

Usage:
    python tools/backtesting/coverage_report.py                 # whole universe
    python tools/backtesting/coverage_report.py --symbols NVDA AMD
    python tools/backtesting/coverage_report.py --start 2024-06-01 --sample 1
    python tools/backtesting/coverage_report.py --out coverage.json

Interpretation (per src/backtesting/data/quality.py verdicts):
    good     >= 90% usable decision days  -> free Alpaca data is sufficient
    marginal 70-90%                       -> usable with caveats; consider vendor
    poor     < 70%                        -> buy real chain data before trusting
"""

import argparse
import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.backtesting.data.alpaca_provider import (  # noqa: E402
    ALPACA_OPTIONS_HISTORY_START,
    AlpacaDataProvider,
)
from src.backtesting.data.chain_builder import ChainBuilder  # noqa: E402
from src.backtesting.data.quality import evaluate_coverage  # noqa: E402
from src.utils.config import Config  # noqa: E402


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest data-coverage gate (FC-032).")
    parser.add_argument("--symbols", nargs="*", help="Symbols (default: config universe).")
    parser.add_argument(
        "--start",
        type=_parse_date,
        default=ALPACA_OPTIONS_HISTORY_START,
        help="Window start (default: Alpaca options history floor, 2024-02-01).",
    )
    parser.add_argument(
        "--end", type=_parse_date, default=date.today(), help="Window end (default: today)."
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=5,
        help="Sample every N trading days (default 5 ~ weekly; 1 = exhaustive).",
    )
    parser.add_argument("--out", help="Optional path to write the JSON summary.")
    args = parser.parse_args()

    config = Config()
    symbols = args.symbols or config.stock_symbols

    start = max(args.start, ALPACA_OPTIONS_HISTORY_START)
    if start != args.start:
        print(
            f"Note: clamped start to Alpaca options-history floor {start.isoformat()}."
        )

    provider = AlpacaDataProvider.from_config(config)
    max_dte = getattr(config, "put_target_dte", 7)
    put_band = tuple(getattr(config, "put_delta_range", [0.10, 0.20]))
    min_prem = getattr(config, "min_put_premium", 0.50)
    builder = ChainBuilder(provider)

    summaries = []
    errors: list = []
    print(
        f"\nData coverage {start.isoformat()} -> {args.end.isoformat()} "
        f"(sample every {args.sample} trading days, max_dte={max_dte}, "
        f"put delta {put_band}, min premium ${min_prem})\n"
    )
    header = (
        f"{'symbol':<8}{'days':>6}{'w/bar':>8}{'in-band':>9}{'inband%':>9}"
        f"{'usable':>8}{'usable%':>9}  {'verdict':<9} limited-by"
    )
    print(header)
    print("-" * len(header))

    for symbol in symbols:
        try:
            report = evaluate_coverage(
                provider,
                builder,
                symbol,
                start,
                args.end,
                max_dte=max_dte,
                put_delta_band=put_band,
                min_put_premium=min_prem,
                sample_every_trading_days=args.sample,
            )
        except Exception as e:  # noqa: BLE001 - operator tool, surface and continue
            print(f"{symbol:<8}ERROR: {e}")
            errors.append({"symbol": symbol, "error": str(e)})
            continue

        s = report.summary()
        summaries.append(s)
        print(
            f"{symbol:<8}{report.decision_days:>6}{report.days_with_bar:>8}"
            f"{report.days_with_in_band_put:>9}{report.in_band_fraction * 100:>8.1f}%"
            f"{report.days_with_usable_put:>8}{report.usable_fraction * 100:>8.1f}%"
            f"  {report.verdict():<9} {report.limiting_factor()}"
        )

    # A gate that reports success on zero data is worse than no gate: it is the
    # exact failure the old engine shipped for a year. Refuse to write an
    # artifact that a reader would mistake for a clean run.
    if not summaries:
        print(
            f"\nFATAL: no symbol produced a coverage report ({len(errors)} errored). "
            "No gate decision is possible; not writing an output file."
        )
        return 1

    if args.out:
        with open(args.out, "w") as f:
            json.dump(summaries, f, indent=2)
        print(f"\nWrote {len(summaries)} symbol summaries to {args.out}")

    # Aggregate guidance.
    good = sum(1 for s in summaries if s["verdict"] == "good")
    marginal = sum(1 for s in summaries if s["verdict"] == "marginal")
    poor = sum(1 for s in summaries if s["verdict"] == "poor")
    no_data = [s["symbol"] for s in summaries if s["verdict"] == "no-data"]
    print(
        f"\nVerdict tally: {good} good, {marginal} marginal, {poor} poor "
        f"of {len(summaries) - len(no_data)} measured symbols."
    )

    # The vendor decision turns on WHY days are unusable, not how many. A paid
    # provider supplies quotes and greeks; it cannot make a 15-delta weekly pay
    # a premium it never paid. Only 'data'-limited symbols are an argument to buy.
    measured = [s for s in summaries if s["verdict"] != "no-data"]
    data_limited = [s["symbol"] for s in measured if s["limiting_factor"] == "data"]
    premium_limited = [s["symbol"] for s in measured if s["limiting_factor"] == "premium"]
    print(
        f"Limited by DATA (a vendor would help): {len(data_limited)} "
        f"{sorted(data_limited) if data_limited else ''}"
    )
    print(
        f"Limited by PREMIUM (no vendor helps; the symbol underpays our floor): "
        f"{len(premium_limited)} {sorted(premium_limited) if premium_limited else ''}"
    )
    print(
        "\nGate: buy ThetaData/ORATS only if symbols are DATA-limited — i.e. the "
        "chain lacks a priced put at our deltas. PREMIUM-limited symbols are a "
        "finding about the symbol (it does not pay our floor), and are exactly "
        "what the fitness report exists to surface; they are not a data problem."
    )

    if no_data:
        print(
            f"\nWARNING: {len(no_data)} symbol(s) yielded ZERO decision days and "
            f"were not measured at all: {', '.join(no_data)}. This is not a "
            "coverage verdict — investigate the data path before reading the gate."
        )
    if errors:
        print(
            f"\nWARNING: {len(errors)} of {len(symbols)} symbols failed and are "
            f"absent from the tally: {', '.join(e['symbol'] for e in errors)}"
        )
    return 1 if (errors or no_data) else 0


if __name__ == "__main__":
    raise SystemExit(main())
