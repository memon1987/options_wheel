# The backtest engine — what it measures, and what not to trust

**Status:** complete as a **measurement tool**, and **live in production** — a monthly Cloud
Run Job writes to `options_wheel.backtest_runs`. Not wired to any automated *action*:
`demote` is a column, not a trigger.
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

## Track D — DONE (2026-07-30). The screen is live.

The engine runs monthly as a **Cloud Run Job**. `/backtest/screen` remains disabled
(503) and should stay that way — a full screen takes **1h47m**, so no synchronous HTTP
request can serve it.

### What is deployed

| | |
|---|---|
| Job | `backtest-screen` (us-central1) |
| Image | `us-central1-docker.pkg.dev/<PROJECT>/options-wheel/options-wheel-strategy:<SHA>` — **Artifact Registry**, SHA-pinned |
| Resources | 1 vCPU, 1 GiB, `--task-timeout 10800s`, `--max-retries 0` |
| Credentials | `--set-secrets` → `alpaca-api-key`, `alpaca-secret-key`, `finnhub-api-key` |
| Schedule | `monthly-performance-review`, **ENABLED**, `0 6 1 * *` UTC (= 02:00 ET) |
| Trigger | Scheduler → **OAuth** → `run.googleapis.com/...jobs/backtest-screen:run` |

### Verified end to end, 2026-07-30

- Execution `backtest-screen-s5dp7` **succeeded in 1h47m39s**
- Wrote **14 rows** to `options_wheel.backtest_runs` (`run_kind='full'`, window 2025-07-30 → 2026-07-29)
- **Verdicts identical to a local run** of the same window — same code, two environments,
  same answer on all 14 symbols (6 `marginal`, 6 `insufficient`, 2 `unfit`)
- Scheduler trigger test-fired and confirmed to create an execution (then cancelled)

### Corrections to what this doc previously said

Three things here were wrong before Track D was attempted, and each would have broken the
deploy. Recorded because the same mistakes are easy to repeat:

1. **Registry.** It said `gcr.io/...`. It is **Artifact Registry**. `jobs create` would have
   failed on image pull.
2. **`:latest`.** It said no `latest` tag is published. **One is** — the build tags both the
   SHA and `latest`. SHA-pinning is still correct for a Job (reproducibility), but the claim
   was false.
3. **Timeout.** It said `3600s`. The real run takes **1h47m**, so an hour would have timed
   out. Now `10800s`.

### Operating notes

- **~5.5 min/symbol**, and the cache never warms — Cloud Run's filesystem is ephemeral, so
  every run is cold. Roughly 16 of those minutes are spent building chains for F, PFE and VZ
  only to discover no put clears the `$0.50` floor: they pass the price band, so the engine
  cannot know until it looks. That is a concrete cost of FC-034 remaining unactioned.
- **Schedule is 02:00 ET deliberately.** A ~2h run must not overlap the trading session; the
  previous `0 12 1 * *` (08:00 ET) would have finished ~09:47 ET, on top of the open and
  contending with the live bot for the same Alpaca quota.
- **`--max-retries 0` is deliberate.** The default of 3 would mean a failing screen hammering
  contract discovery three times.
- **The job name is now a misnomer** — `monthly-performance-review` runs a screen. Left as-is
  because renaming means delete-and-recreate, losing history.

### If it fails

Logs work now (FC-059 — Cloud Run **Jobs** set `CLOUD_RUN_JOB`, not `K_SERVICE`, so log
output previously went to a file inside an ephemeral container and vanished):

```bash
gcloud run jobs executions list --job backtest-screen --region us-central1
gcloud logging read 'resource.labels.job_name="backtest-screen"' --limit 50 --freshness=3h
```

A failure writes **zero** rows — persistence is a single batch after the loop — so a partial
run cannot corrupt `backtest_runs`.

### Before the first *persisted* screen

Persisted rows land in `options_wheel.backtest_runs`, which historically fed demotion
recommendations. Given the engine is being adopted as a measurement tool only, the useful
sequence is: run the Job, read the output, and treat the first few months as **data
collection**. The `demote` column is a recommendation for a human, and the biases above
are the reason it needs one.
