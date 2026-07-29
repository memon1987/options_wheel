#!/usr/bin/env python3
"""FC-032 Phase 3 parity check — does the replay pick what the bot picked?

The backtest is only trustworthy if, given the same day and the same symbol, it
selects approximately the contract the live bot actually sold. This tool asks
exactly that, one real decision at a time:

  1. Pull every put sell-to-open fill from the Alpaca account (the same source
     `options_wheel.trades_from_activities` is derived from).
  2. For each (date, underlying) the bot actually traded, rebuild that day's
     chain from historical data, wrap it in BacktestAlpacaClient, and run the
     *live* selection path — MarketDataManager.find_suitable_puts()[0], which is
     precisely what PutSeller.find_put_opportunity() picks.
  3. Compare the selected contract against the one that really filled.

Why per-decision rather than a full replay: a full-window replay makes its own
sequence of decisions, so assignment timing diverges from live within days and
nothing lines up trade-for-trade. Isolating the *selection* answers the question
that actually matters for fidelity — is the chain we reconstruct good enough to
reproduce the bot's choice — without conflating it with path divergence.

Matches are approximate by construction: live decided on a live chain with real
bid/ask at ~9:35/12:00/15:00 ET; the replay decides on trade-derived bars at the
close with modeled spreads. Strike agreement is the strong signal; premium
agreement is the weaker one.

Sides: the check ran PUTS ONLY until FC-048. That was not a choice — covered
calls were misrouted in the engine, so the replay could not produce one to
compare. The headline "81% strike reproduction" therefore describes the put leg
alone. `--side call` measures the other half against real covered-call fills.

The call side needs one thing the put side does not: a **cost-basis floor**.
Live called `find_suitable_calls(symbol, min_strike_price=cost_basis)`, so
comparing without that floor would be a different question than the one the bot
answered. Basis is resolved per FC-029 R2 — the strike of the most recent prior
put assignment (OPASN) on that underlying. A decision whose basis cannot be
resolved is reported as `no_basis` and excluded from the rate rather than
silently compared on a floor of zero.

Usage:
    python tools/diagnostics/parity_check.py                    # puts, whole history
    python tools/diagnostics/parity_check.py --side call        # the call leg
    python tools/diagnostics/parity_check.py --symbols NVDA AMD
    python tools/diagnostics/parity_check.py --limit 40 --out parity.json
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.api.market_data import MarketDataManager  # noqa: E402
from src.api.alpaca_client import AlpacaClient  # noqa: E402
from src.backtesting.data.alpaca_provider import AlpacaDataProvider  # noqa: E402
from src.backtesting.data.chain_builder import ChainBuilder  # noqa: E402
from src.backtesting.engine.alpaca_adapter import BacktestAlpacaClient  # noqa: E402
from src.backtesting.engine.broker import BacktestBroker  # noqa: E402
from src.utils import clock  # noqa: E402
from src.utils.config import Config  # noqa: E402

OCC = re.compile(r"^([A-Z]{1,5})(\d{6})([CP])(\d{8})$")


def fetch_assignment_basis(config):
    """Per-underlying history of put assignments -> (date, strike).

    FC-029 R2: the cost basis of assigned shares is the strike of the put that
    assigned them. Call OPASN rows (shares called away) are excluded — they end
    a position, they do not establish a basis.
    """
    client = AlpacaClient(config)
    rows = client.get_account_activities("OPASN", after="2024-01-01", page_size=500) or []
    basis = {}
    for a in rows:
        m = OCC.match(a.get("symbol", ""))
        if not m or m.group(3) != "P":
            continue
        underlying, _, _, strike = m.groups()
        day = datetime.strptime(a["date"][:10], "%Y-%m-%d").date()
        basis.setdefault(underlying, []).append((day, int(strike) / 1000.0))
    for k in basis:
        basis[k].sort()
    return basis


def basis_as_of(basis, underlying, day):
    """The most recent put-assignment strike on or before `day`, else None."""
    prior = [(d, k) for d, k in basis.get(underlying, []) if d <= day]
    return prior[-1][1] if prior else None


def fetch_live_sales(config, side="put"):
    """Every sell-to-open fill of `side` on the account, oldest first."""
    client = AlpacaClient(config)
    rows, token = [], None
    for _ in range(80):
        batch = client.get_account_activities(
            "FILL", after="2024-01-01", page_size=100, page_token=token
        )
        if not batch:
            break
        rows.extend(batch)
        token = batch[-1].get("id")
        if len(batch) < 100:
            break

    sales = []
    for a in rows:
        m = OCC.match(a.get("symbol", ""))
        want = "P" if side == "put" else "C"
        if not m or m.group(3) != want or a.get("side") != "sell_short":
            continue
        underlying, ymd, _, strike = m.groups()
        sales.append(
            {
                "day": datetime.strptime(a["transaction_time"][:10], "%Y-%m-%d").date(),
                "underlying": underlying,
                "symbol": a["symbol"],
                "expiration": datetime.strptime(ymd, "%y%m%d").date(),
                "strike": int(strike) / 1000.0,
                "premium": float(a["price"]),
            }
        )
    sales.sort(key=lambda s: (s["day"], s["underlying"]))
    return sales


def main() -> int:
    parser = argparse.ArgumentParser(description="FC-032 replay-vs-reality parity check.")
    parser.add_argument("--symbols", nargs="*", help="Restrict to these underlyings.")
    parser.add_argument("--limit", type=int, help="Only the first N decisions (smoke test).")
    parser.add_argument("--max-dte", type=int, default=None,
                        help="Override the DTE window used to build chains.")
    parser.add_argument("--side", choices=["put", "call"], default="put",
                        help="Which leg to check. 'call' needs a cost-basis floor "
                             "(resolved from the assigning put per FC-029 R2).")
    parser.add_argument("--out", help="Write per-decision detail as JSON.")
    args = parser.parse_args()

    config = Config()
    dte_key = "put_target_dte" if args.side == "put" else "call_target_dte"
    max_dte = args.max_dte if args.max_dte is not None else getattr(config, dte_key, 7)

    sales = fetch_live_sales(config, side=args.side)
    basis_history = fetch_assignment_basis(config) if args.side == "call" else {}
    if args.symbols:
        wanted = {s.upper() for s in args.symbols}
        sales = [s for s in sales if s["underlying"] in wanted]

    # One comparison per (day, underlying): the bot may fill several contracts
    # for one decision, so collapse to the richest premium actually sold.
    by_decision = {}
    for s in sales:
        key = (s["day"], s["underlying"])
        if key not in by_decision or s["premium"] > by_decision[key]["premium"]:
            by_decision[key] = s
    decisions = sorted(by_decision.values(), key=lambda s: (s["day"], s["underlying"]))
    if args.limit:
        decisions = decisions[: args.limit]

    print(f"\nParity check [{args.side.upper()}]: {len(decisions)} live decisions, "
          f"max_dte={max_dte}\n")

    provider = AlpacaDataProvider.from_config(config)
    builder = ChainBuilder(provider)

    # Underlying history per symbol, fetched once (the adapter clips to sim date).
    symbols = sorted({d["underlying"] for d in decisions})
    span_start = min(d["day"] for d in decisions)
    span_end = max(d["day"] for d in decisions)
    stock_bars = {s: provider.get_stock_bars(s, span_start, span_end) for s in symbols}

    header = (f"{'day':<12}{'sym':<7}{'live K':>8}{'sim K':>8}{'ΔK':>7}"
              f"{'live $':>8}{'sim $':>8}{'sim δ':>8}  verdict")
    print(header)
    print("-" * len(header))

    results = []
    for d in decisions:
        symbol, day = d["underlying"], d["day"]
        snapshot = builder.build(symbol, day, max_dte)
        if snapshot is None:
            results.append({**_key(d), "outcome": "no_chain"})
            print(f"{day!s:<12}{symbol:<7}{d['strike']:>8.1f}{'—':>8}{'—':>7}"
                  f"{d['premium']:>8.2f}{'—':>8}{'—':>8}  no_chain")
            continue

        broker = BacktestBroker(starting_cash=1_000_000.0)
        client = BacktestAlpacaClient(
            broker, chains={symbol: {day: snapshot}}, stock_bars=stock_bars
        )
        market_data = MarketDataManager(client, config)

        floor = None
        if args.side == "call":
            # Live selected against the cost-basis floor, so comparing without
            # it would answer a different question than the bot answered.
            floor = basis_as_of(basis_history, symbol, day)
            if floor is None:
                results.append({**_key(d), "outcome": "no_basis"})
                print(f"{day!s:<12}{symbol:<7}{d['strike']:>8.1f}{'—':>8}{'—':>7}"
                      f"{d['premium']:>8.2f}{'—':>8}{'—':>8}  no_basis")
                continue

        with clock.frozen(datetime.combine(day, time(16, 0))):
            try:
                if args.side == "put":
                    suitable = market_data.find_suitable_puts(symbol)
                else:
                    suitable = market_data.find_suitable_calls(
                        symbol, min_strike_price=floor)
            except Exception as exc:  # noqa: BLE001 - diagnostic tool
                results.append({**_key(d), "outcome": "error", "error": str(exc)})
                print(f"{day!s:<12}{symbol:<7}{'ERROR':>8}  {exc}")
                continue

        if not suitable:
            results.append({**_key(d), "outcome": "no_candidate"})
            print(f"{day!s:<12}{symbol:<7}{d['strike']:>8.1f}{'—':>8}{'—':>7}"
                  f"{d['premium']:>8.2f}{'—':>8}{'—':>8}  no_candidate")
            continue

        # Exactly what the seller takes: find_put_opportunity /
        # evaluate_covered_call_opportunity both use suitable[0].
        best = suitable[0]
        sim_strike = float(best["strike_price"])
        sim_prem = float(best.get("mid_price") or 0.0)
        sim_delta = abs(float(best.get("delta") or 0.0))
        strike_diff_pct = (sim_strike - d["strike"]) / d["strike"] * 100.0

        outcome = "exact" if abs(sim_strike - d["strike"]) < 1e-6 else (
            "close" if abs(strike_diff_pct) <= 2.0 else "diverged"
        )
        results.append({
            **_key(d), "outcome": outcome, "sim_strike": sim_strike,
            "sim_premium": sim_prem, "sim_delta": sim_delta,
            "sim_symbol": best["symbol"], "strike_diff_pct": strike_diff_pct,
        })
        print(f"{day!s:<12}{symbol:<7}{d['strike']:>8.1f}{sim_strike:>8.1f}"
              f"{strike_diff_pct:>6.1f}%{d['premium']:>8.2f}{sim_prem:>8.2f}"
              f"{sim_delta:>8.3f}  {outcome}")

    band = (tuple(config.put_delta_range) if args.side == "put"
            else tuple(config.call_delta_range))
    _summarize(results, delta_band=band, side=args.side)
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(results, fh, indent=2, default=str)
        print(f"\nWrote {len(results)} decisions to {args.out}")
    return 0


def _key(d):
    return {
        "day": d["day"].isoformat(), "underlying": d["underlying"],
        "live_symbol": d["symbol"], "live_strike": d["strike"],
        "live_premium": d["premium"],
        "live_dte": (d["expiration"] - d["day"]).days,
    }


def _summarize(results, delta_band=(0.10, 0.20), side='put'):
    total = len(results)
    if not total:
        print("\nNo decisions compared.")
        return
    counts = Counter(r["outcome"] for r in results)
    print(f"\n{'='*64}\nPARITY SUMMARY ({total} decisions)\n{'='*64}")
    for outcome in ("exact", "close", "diverged", "no_candidate", "no_chain", "error"):
        n = counts.get(outcome, 0)
        if n:
            print(f"  {outcome:<14}{n:>5}  ({n/total*100:>5.1f}%)")

    matched = [r for r in results if r["outcome"] in ("exact", "close", "diverged")]
    if matched:
        reproduced = counts.get("exact", 0) + counts.get("close", 0)
        print(f"\n  Strike reproduced (exact or within 2%): "
              f"{reproduced}/{len(matched)} = {reproduced/len(matched)*100:.1f}% "
              f"of decisions where the replay found any candidate")
        diffs = sorted(abs(r["strike_diff_pct"]) for r in matched)
        print(f"  |strike diff| median {diffs[len(diffs)//2]:.2f}%  "
              f"p90 {diffs[int(len(diffs)*0.9)]:.2f}%  max {diffs[-1]:.2f}%")
        ratios = sorted(r["sim_premium"] / r["live_premium"]
                        for r in matched if r["live_premium"] > 0 and r.get("sim_premium"))
        if ratios:
            print(f"  sim/live premium ratio: median {ratios[len(ratios)//2]:.2f}  "
                  f"p10 {ratios[int(len(ratios)*0.1)]:.2f}  p90 {ratios[int(len(ratios)*0.9)]:.2f}")
        deltas = sorted(r["sim_delta"] for r in matched if r.get("sim_delta"))
        if deltas:
            lo, hi = delta_band
            in_band = sum(1 for x in deltas if lo <= x <= hi)
            # The band differs by leg: puts [0.10,0.20], calls [0.15,0.25]
            # (FC-029 R1 tightened the call range). Reporting a call against the
            # put band understates fidelity.
            print(f"  sim delta in [{lo:.2f},{hi:.2f}] ({side}s): {in_band}/{len(deltas)} "
                  f"({in_band/len(deltas)*100:.1f}%), median {deltas[len(deltas)//2]:.3f}")

    by_sym = defaultdict(Counter)
    for r in results:
        by_sym[r["underlying"]][r["outcome"]] += 1
    print("\n  Per symbol:")
    for sym in sorted(by_sym):
        c = by_sym[sym]
        tot = sum(c.values())
        ok = c.get("exact", 0) + c.get("close", 0)
        print(f"    {sym:<7}{ok:>3}/{tot:<4} reproduced   "
              + "  ".join(f"{k}={v}" for k, v in sorted(c.items())))

    live_dtes = Counter(r["live_dte"] for r in results)
    print(f"\n  Live DTE distribution: {dict(sorted(live_dtes.items()))}")


if __name__ == "__main__":
    raise SystemExit(main())
