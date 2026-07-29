# The backtest engine — what it measures, and what not to trust

**Status:** complete as a **measurement tool**. Not wired to any automated action.
**Last updated:** 2026-07-29

Programmatic demotion is deliberately **out of scope** — a later motion, once the engine
has been generating real data for a while. Nothing in this system changes the trading
universe today. `demote` is a column, not a trigger.

---

## What it is

It replays the **live strategy code** over historical Alpaca data. It does not
reimplement the strategy — `WheelEngine.run_strategy_cycle()`, `PutSeller`, `CallSeller`,
`RiskManager` and `GapDetector` are the real objects, driven by a frozen clock against a
`BacktestAlpacaClient` adapter. That is the whole design premise: a reimplementation would
drift from production, and a drift you cannot see is worse than no backtest.

```bash
python main.py --command backtest --symbol NVDA --start 2025-11-01 --end 2025-12-01
python main.py --command screen                    # whole universe -> BigQuery
python main.py --command screen --no-persist       # analysis only, writes nothing
```

## What it is good for

- **Comparing symbols against each other** under one configuration.
- **Attributing why a symbol does or doesn't trade** — which stage blocked it, on how many
  days. Since FC-057 this includes stage 1, which was previously silent.
- **Answering A/B questions about thresholds** — this is what it did for FC-002, FC-034
  and FC-036, in each case producing a verdict that contradicted the prevailing assumption.

## What it is NOT good for

- **Absolute return levels.** Every known bias points the same way (below). Read a return
  as a floor.
- **The call leg specifically.** See the fidelity table.
- **Anything on a symbol it never traded.** A `0% days in position` row tells you about
  the *filters*, not the symbol.

---

## Fidelity, measured — the two legs are not equal

| | decisions | strike reproduction | premium on **identical** contracts | delta band |
|---|---:|---:|---:|---:|
| **put leg** | 204 | **81%** | ~0.93 of live | 100% |
| **call leg** | 80 | **55.2%** | **0.676 of live** | 100% |

The call leg's pricing error is roughly **5× the put leg's**, and its cause is unknown —
DTE mix was the obvious explanation and was **tested and disconfirmed** (FC-056). The call
leg was unmeasurable until FC-048, because before that the engine could not produce a
covered call at all.

**Delta-band accuracy is 100% on both legs.** The engine always selects a correct-*risk*
contract. It is the price — and on calls the strike — that drift.

### Every known bias points the same direction

| bias | magnitude | direction |
|---|---|---|
| put-leg premium | ~7% low (identical contracts) | conservative |
| call-leg premium | ~32% low (identical contracts) | conservative |
| modeled bid/ask spread | 2.46× wider than real, RTH-measured | conservative |
| dividends | modeled both legs since FC-042 C1 | ~neutral |
| ex-div early assignment | **never fired on real data** | optimistic |

**Reported returns are a floor, not a forecast.** For a screening tool this is the correct
failure mode: it cannot flatter a symbol into looking tradeable.

---

## Things that will mislead you if you don't know them

1. **A symbol with 0% days in position is a filter result, not a verdict on the symbol.**
   As of this writing **8 of 14 configured symbols cannot meaningfully trade**: SPY, QQQ
   and AMD are above the `$400 max_stock_price` ceiling (FC-055); F, PFE, KMI and VZ
   cannot clear the `$0.50 min_put_premium` floor (FC-034); MSFT oscillates on the
   ceiling. The effective universe is six: AAPL, AMZN, GOOGL, IWM, NVDA, UNH.
2. **"Completed cycles" counts put-expire-worthless turns.** A number like "44 completed
   cycles" can contain exactly one full wheel. Look for `called_away`.
3. **Ex-dividend early assignment has never executed on real data.** It needs a dividend
   payer holding an ITM short call, and the payers are precisely the symbols that cannot
   open a position. Validated by unit tests only.
4. **The engine refuses split-spanning windows** (`UnadjustedCorporateAction`) by design —
   raw bars are correct for point-in-time chain work but cannot span a split. Pick a
   window that avoids the split date; the error message names it.
5. **`rows in `backtest_runs` before 2026-07-29 describe a put-only engine** (FC-048).
   Do not compare across that boundary. Provenance is `timestamp` + `config_hash`.
6. **The stage-2 gap filter is not wired into live trading** (FC-049) — the engine runs
   it, production does not. Any stage-2 block rate describes the *engine*.

---

## Re-running the fidelity checks

None of the numbers above are asserted; each has a re-runnable derivation.

```bash
python tools/diagnostics/parity_check.py                     # put leg
python tools/diagnostics/parity_check.py --side call         # call leg
python tools/diagnostics/spread_model_check.py --require-rth # spread, intraday only
python tools/backtesting/coverage_report.py --out coverage.json
```

`--require-rth` exists because an after-hours spread sample makes the model look better
than it is; it refuses to emit a conclusion when the market is closed.

---

## Remaining owner step: Track D (deploy)

The engine runs locally today. `/backtest/screen` is **disabled by default** (503 unless
`ENABLE_SCREEN_ENDPOINT=true`) and should stay that way — at minutes-per-symbol, no
synchronous HTTP request finishes a full universe against a 300s timeout. The intended
path is a **Cloud Run Job**.

```bash
# 1. Create the Job (the only honest execution path for a full screen)
gcloud run jobs create backtest-screen \
  --image gcr.io/gen-lang-client-0607444019/options-wheel-strategy \
  --region us-central1 --task-timeout 3600s \
  --set-env-vars GCP_PROJECT=gen-lang-client-0607444019 \
  --command python --args "main.py,--command,screen"

gcloud run jobs execute backtest-screen --region us-central1   # verify once by hand

# 2. Re-point the paused monthly job at the Job's :run endpoint
#    (currently targets /backtest/performance-comparison, deleted in FC-032)
gcloud scheduler jobs resume monthly-performance-review --location us-central1

# 3. Delete the three jobs whose endpoints no longer exist and have no replacement
gcloud scheduler jobs delete daily-quick-backtest        --location us-central1
gcloud scheduler jobs delete weekly-comprehensive-backtest --location us-central1
gcloud scheduler jobs delete daily-cache-maintenance     --location us-central1
```

All four are **PAUSED** today and target endpoints deleted in FC-032, so nothing is
currently failing — but they are live 404s waiting to be resumed by someone who doesn't
know that.

**Do not set `ENABLE_SCREEN_ENDPOINT=true`** unless you specifically want the HTTP path;
the Job is the supported route.

### Before the first *persisted* screen

Persisted rows land in `options_wheel.backtest_runs`, which historically fed demotion
recommendations. Given the engine is being adopted as a measurement tool only, the useful
sequence is: run the Job, read the output, and treat the first few months as **data
collection**. The `demote` column is a recommendation for a human, and the biases above
are the reason it needs one.
