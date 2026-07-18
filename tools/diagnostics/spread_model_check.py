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
(closer to reality) than it is. The script reports whether the market was open.

Usage:
    python tools/diagnostics/spread_model_check.py
    python tools/diagnostics/spread_model_check.py --symbols NVDA AMD --out spread.json
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Modeled vs real option spreads.")
    ap.add_argument("--symbols", nargs="*")
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
    rth = 0 if now.weekday() >= 5 else (1 if 9 <= now.hour < 16 else 0)
    print(f"\n  sampled {now:%Y-%m-%d %H:%M} local — "
          f"{'during' if rth else 'OUTSIDE'} regular trading hours."
          + ("" if rth else " Out-of-hours quotes are WIDER than intraday, so the"
                            " model looks closer to reality here than it is."))

    if args.out:
        with open(args.out, "w") as fh:
            json.dump({
                "generated": now.isoformat(), "n": len(rows),
                "median_real_half_spread": med_real,
                "median_modeled_half_spread": med_modeled,
                "modeled_over_real": (med_modeled / med_real) if med_real else None,
                "modeled_wider_pct": wider / len(ratios) * 100,
                "during_regular_hours": bool(rth),
                "rows": rows,
            }, fh, indent=1)
        print(f"\nWrote {len(rows)} comparisons to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
