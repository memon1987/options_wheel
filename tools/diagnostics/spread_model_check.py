#!/usr/bin/env python3
"""Measure the modeled bid/ask spread against real live quotes.

The backtest has no historical option quotes (Alpaca sells none), so bid/ask
comes from `SpreadModel`. Every fitness report therefore carries a claim about
how that model compares to reality — and a claim like that must be derived, not
asserted. This is the derivation.

Method: pull the current option chain for each symbol, keep OTM puts in the
price band the strategy actually trades, and compare each contract's real
half-spread ((ask-bid)/2) against what SpreadModel would have produced for the
same contract.

Caveat worth carrying into any conclusion: quotes sampled outside regular
trading hours are wider than intraday, which makes the model look *better*
(closer to reality) than it is. Session state is resolved from Alpaca's own
market clock (which knows holidays and half-days), not from a local-hour guess.

Pass ``--require-rth`` to make the script refuse to emit any conclusion unless
the market is genuinely open. Use that flag whenever the output is going to be
quoted as an intraday measurement — an after-hours sample labelled "intraday"
is the exact failure this tool exists to prevent.

``--calibrate`` fits a SpreadModel and prints the parameters together with
their provenance (n, date, session, symbols) AND their fit diagnostics, then
states a VERDICT on whether they may be committed. Provenance alone is not
validity: an RTH sample can still produce a fit that is clamped, extrapolated,
or explains almost none of the variance. Both gates must pass.

Usage:
    python tools/diagnostics/spread_model_check.py
    python tools/diagnostics/spread_model_check.py --symbols NVDA AMD --out spread.json
    # the calibration run (must be during US market hours):
    python tools/diagnostics/spread_model_check.py --require-rth --calibrate \
        --out docs/investigations/spread-rth-sample.json
"""

import argparse
import json
import os
import statistics
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.api.alpaca_client import AlpacaClient  # noqa: E402
from src.backtesting.data.spread_model import SpreadModel  # noqa: E402
from src.utils.config import Config  # noqa: E402
from src.utils.option_symbols import parse_option_symbol  # noqa: E402


def resolve_session(client) -> tuple[bool, str]:
    """Return (is_rth, description) using Alpaca's market clock.

    The broker clock is authoritative: it accounts for weekends, exchange
    holidays and early closes, none of which a local-hour heuristic sees. If
    the clock call fails we return ``False`` — refusing to claim RTH is the
    safe direction, since a false "intraday" label is what corrupts the
    conclusion.
    """
    try:
        clock = client.trading_client.get_clock()
        if clock.is_open:
            return True, f"market OPEN (closes {clock.next_close:%Y-%m-%d %H:%M %Z})"
        return False, f"market CLOSED (next open {clock.next_open:%Y-%m-%d %H:%M %Z})"
    except Exception as exc:  # noqa: BLE001 - diagnostic tool
        return False, f"market clock unavailable ({str(exc)[:50]}) - assuming CLOSED"


def main() -> int:
    ap = argparse.ArgumentParser(description="Modeled vs real option spreads.")
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--require-rth", action="store_true",
                    help="Refuse to emit a conclusion unless the market is open.")
    ap.add_argument("--calibrate", action="store_true",
                    help="Fit a SpreadModel from the sample and print it with provenance.")
    ap.add_argument("--min-mark", type=float, default=0.20)
    ap.add_argument("--max-mark", type=float, default=3.00)
    ap.add_argument("--max-moneyness", type=float, default=0.15,
                    help="Keep strikes within this fraction of spot.")
    ap.add_argument("--out")
    args = ap.parse_args()

    config = Config()
    symbols = args.symbols or ["NVDA", "AAPL", "IWM", "AMD"]
    client = AlpacaClient(config)
    model = SpreadModel()

    # Resolve the session BEFORE pulling chains, so a gated run fails fast
    # instead of burning API calls on a sample it will refuse to use.
    rth, session_desc = resolve_session(client)
    if args.require_rth and not rth:
        print(f"--require-rth given but {session_desc}.\n"
              "Refusing to sample: an out-of-hours measurement cannot stand in "
              "for an intraday one. Re-run while the market is open.",
              file=sys.stderr)
        return 2

    rows = []
    for symbol in symbols:
        try:
            quote = client.get_stock_quote(symbol)
            spot = (quote["bid"] + quote["ask"]) / 2 if quote else 0.0
            chain = client.get_options_chain(symbol)
        except Exception as exc:  # noqa: BLE001 - diagnostic tool
            print(f"{symbol:<6} FAILED: {str(exc)[:70]}")
            continue
        if not spot or not chain:
            print(f"{symbol:<6} no spot/chain")
            continue

        kept = 0
        for opt in chain:
            if opt.get("option_type") != "put":
                continue
            bid, ask = float(opt.get("bid") or 0), float(opt.get("ask") or 0)
            if bid <= 0 or ask <= 0 or ask < bid:
                continue
            strike = float(opt.get("strike_price") or 0)
            if not strike or strike >= spot:  # OTM puts only
                continue
            if abs(strike - spot) / spot > args.max_moneyness:
                continue
            mark = (bid + ask) / 2
            if not (args.min_mark <= mark <= args.max_mark):
                continue

            exp = opt.get("expiration_date")
            exp_date = (datetime.strptime(exp[:10], "%Y-%m-%d").date()
                        if isinstance(exp, str) else exp)
            dte = max(0, (exp_date - date.today()).days) if exp_date else 7

            real_half = (ask - bid) / 2
            moneyness = abs(1.0 - strike / spot)
            modeled_half = model.half_spread(mark, moneyness)
            rows.append({
                "symbol": symbol, "strike": strike, "spot": round(spot, 2),
                "dte": dte, "mark": round(mark, 3),
                "moneyness": round(moneyness, 4),
                # SpreadModel.calibrate() consumes mark/moneyness/half_spread.
                "half_spread": round(real_half, 4),
                "real_half_spread": round(real_half, 4),
                "modeled_half_spread": round(modeled_half, 4),
                "ratio_real_over_modeled": round(real_half / modeled_half, 3)
                if modeled_half > 0 else None,
            })
            kept += 1
        print(f"{symbol:<6} spot {spot:>8.2f}  usable OTM puts: {kept}")

    if not rows:
        print("\nNo comparable quotes — refusing to emit a conclusion.", file=sys.stderr)
        return 1

    real = [r["real_half_spread"] for r in rows]
    modeled = [r["modeled_half_spread"] for r in rows]
    ratios = [r["ratio_real_over_modeled"] for r in rows
              if r["ratio_real_over_modeled"] is not None]

    med_real, med_modeled = statistics.median(real), statistics.median(modeled)
    print(f"\n{'='*60}\nSPREAD MODEL vs REALITY  (n={len(rows)})\n{'='*60}")
    print(f"  median real half-spread    ${med_real:.4f}")
    print(f"  median modeled half-spread ${med_modeled:.4f}")
    if med_real > 0:
        print(f"  modeled / real             {med_modeled / med_real:.2f}x")
    print(f"  median real/modeled ratio  {statistics.median(ratios):.3f}")
    wider = sum(1 for r in ratios if r < 1.0)
    print(f"  modeled WIDER than real on {wider}/{len(ratios)} "
          f"({wider / len(ratios) * 100:.0f}%) — wider is conservative for a seller")

    now = datetime.now()
    print(f"\n  sampled {now:%Y-%m-%d %H:%M} local — {session_desc}")
    print(f"  session: {'REGULAR TRADING HOURS' if rth else 'OUTSIDE regular trading hours'}"
          + ("" if rth else " — out-of-hours quotes are WIDER than intraday, so the"
                            " model looks closer to reality here than it is."
                            " NOT a valid intraday measurement."))

    calibrated = None
    calib_diag = None
    if args.calibrate:
        calibrated, calib_diag = SpreadModel.calibrate(rows, return_diagnostics=True)
        defaults = SpreadModel()
        print(f"\n{'='*60}\nCALIBRATION\n{'='*60}")
        print(f"  base_frac     {calibrated.base_frac:.4f}  (default {defaults.base_frac})")
        print(f"  otm_widening  {calibrated.otm_widening:.4f}  "
              f"(default {defaults.otm_widening})")
        print("  fit quality:")
        print(f"    samples in / used   {calib_diag['n_input']} / {calib_diag['n_used']}")
        print(f"    excluded cheap      {calib_diag['n_excluded_cheap']} "
              f"(mark < ${defaults.cheap_threshold:.2f}; cheap_widening is applied "
              f"at eval, so fitting them double-counts it)")
        print(f"    excluded floor      {calib_diag['n_excluded_floor']} "
              f"(half-spread at the ${defaults.abs_floor:.2f} floor; a constant, "
              f"not a fraction of mark)")
        if calib_diag["r_squared"] is not None:
            print(f"    R^2                 {calib_diag['r_squared']:.3f}")
        if calib_diag["moneyness_min"] is not None:
            print(f"    moneyness span      {calib_diag['moneyness_min']:.4f}"
                  f" .. {calib_diag['moneyness_max']:.4f}")
        print(f"    clamp applied       {calib_diag['clamp_hit']}")
        print("  provenance:")
        print(f"    date     {now:%Y-%m-%d %H:%M} local")
        print(f"    session  {'RTH' if rth else 'OUT-OF-HOURS'}")
        print(f"    symbols  {', '.join(sorted({r['symbol'] for r in rows}))}")

        # Per-symbol fits. A pooled fit is weighted by how many strikes each
        # underlying happens to list, not by trading importance — one liquid
        # ETF with a dense ladder can dominate and drag base_frac toward its
        # penny-wide regime, making the backtest optimistic on every other name.
        print("  per-symbol (pooling hides this dispersion):")
        for sym in sorted({r["symbol"] for r in rows}):
            sym_rows = [r for r in rows if r["symbol"] == sym]
            sym_fit, sym_diag = SpreadModel.calibrate(sym_rows, return_diagnostics=True)
            flag = "OK " if sym_diag["usable"] else "BAD"
            print(f"    [{flag}] {sym:<6} n={len(sym_rows):<4} used={sym_diag['n_used']:<4}"
                  f" base_frac={sym_fit.base_frac:.4f}"
                  f" otm_widening={sym_fit.otm_widening:.4f}")

        verdict = "USABLE" if (calib_diag["usable"] and rth) else "NOT USABLE"
        print(f"\n  VERDICT: {verdict} — {calib_diag['reason']}")
        if not rth:
            print("  Additionally the sample is out-of-hours, which alone "
                  "disqualifies it for calibration.")
        if verdict != "USABLE":
            print("  DO NOT COMMIT these parameters.")

    if args.out:
        with open(args.out, "w") as fh:
            json.dump({
                "generated": now.isoformat(), "n": len(rows),
                "median_real_half_spread": med_real,
                "median_modeled_half_spread": med_modeled,
                "modeled_over_real": (med_modeled / med_real) if med_real else None,
                "modeled_wider_pct": wider / len(ratios) * 100,
                "during_regular_hours": bool(rth),
                "session": session_desc,
                "symbols": sorted({r["symbol"] for r in rows}),
                # `usable` gates the whole block: a consumer reading
                # calibrated.base_frac must not get a number that came from a
                # clamped, defaulted, or out-of-hours fit.
                "calibrated": ({
                    "base_frac": calibrated.base_frac,
                    "otm_widening": calibrated.otm_widening,
                    "usable": bool(calib_diag["usable"] and rth),
                    "reason": calib_diag["reason"],
                    "diagnostics": calib_diag,
                } if calibrated else None),
                "rows": rows,
            }, fh, indent=1)
        print(f"\nWrote {len(rows)} comparisons to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
