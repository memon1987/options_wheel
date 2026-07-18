# FC-032 Phase 3 — Replay-vs-reality parity check

**Date:** 2026-07-17
**Plan:** [docs/plans/fc-032.md](../plans/fc-032.md)
**Tool:** [`tools/diagnostics/parity_check.py`](../../tools/diagnostics/parity_check.py)
**Question:** given the same day and symbol, does the replay select approximately the contract the live bot actually sold?

## Method

204 real decisions — every `(date, underlying)` on which the live account has a put sell-to-open fill, 2025-10-06 → 2026-07-17, across 8 symbols. Source is the Alpaca account's `FILL` activities, which is what `options_wheel.trades_from_activities` is derived from (cross-checked: BQ holds 673 activity rows against 612 FILLs pulled directly; the difference is non-FILL activity types).

For each decision the tool rebuilds that day's chain from historical data, wraps it in `BacktestAlpacaClient`, and runs the **live** selection path — `MarketDataManager.find_suitable_puts()[0]`, exactly what `PutSeller.find_put_opportunity()` picks — then compares against the contract that really filled.

**Why per-decision rather than a full replay.** A full-window replay makes its own sequence of decisions, so assignment timing diverges from live within days and nothing lines up trade-for-trade. Isolating *selection* answers the question that matters for fidelity — is the reconstructed chain good enough to reproduce the bot's choice — without conflating it with path divergence.

Matches are approximate by construction: live decided on a live chain with real bid/ask at ~9:35/12:00/15:00 ET; the replay decides on trade-derived bars at the close with modeled spreads. **Strike agreement is the strong signal; premium agreement is the weak one.**

## Result

| | before DTE fix | after |
|---|---:|---:|
| decisions | 204 | 204 |
| replay found any candidate | 176 (86%) | **202 (99%)** |
| strike reproduced (exact or ≤2%) | 146 (72%) | **166 (81%)** |
| sim delta inside [0.10, 0.20] | 100% | **100%** (median 0.180) |

Per symbol, after: NVDA 50/65, AMD 28/37, GOOGL 23/27, UNH 22/25, AMZN 20/24, IWM 14/15, AAPL 6/7, MSFT 3/4.

**Every sim-selected contract landed inside the strategy's 0.10–0.20 delta band**, median 0.180. The Black-Scholes inversion and the delta filter are working.

## Bug found: DTE flooring (fixed)

Live computes `dte = (expiration - now).days` where the expiration is midnight and `now` is intraday, so the subtraction **floors**: a contract 8 calendar days out reads as DTE 7 and passes a `dte <= 7` filter. **50 of 241 real put fills (21%) were exactly those contracts.**

The chain builder filtered its universe by *calendar* days, so those contracts never entered the chain at all — the replay was structurally blind to a fifth of the trades live actually made.

The parity data isolates it cleanly:

| live DTE | n | reproduced (before) | reproduced (after) |
|---:|---:|---:|---:|
| 2 | 21 | 76% | 76% |
| 3 | 25 | 80% | 80% |
| 4 | 46 | 80% | 80% |
| 5 | 6 | 100% | 100% |
| 6 | 11 | 73% | 73% |
| 7 | 55 | 86% | 86% |
| **8** | **40** | **30%** | **80%** |

26 of the 28 total no-candidate failures were DTE-8 decisions. Fixed by fetching the universe one day wider (`UNIVERSE_DTE_BUFFER`) and letting the strategy's own filter — flooring included — decide. One day is the exact buffer: a 9-calendar-day contract floors to DTE 8 and live rejects it.

## Finding: premium is understated, and by how much

The replay's premium runs **below** live's fill on 80% of decisions, median ratio 0.797. Decomposing by how closely the contract matched isolates pricing from selection:

| match quality | n | median sim/live | below live |
|---|---:|---:|---:|
| identical OCC symbol | 57 | **0.927** | 72% |
| exact strike | 77 | 0.855 | 78% |
| within 2% | 89 | 0.770 | 82% |
| diverged | 36 | 0.743 | 81% |
| all | 202 | 0.797 | 80% |

So the ~20% total gap is roughly **7% pure pricing** (same contract, different price) plus ~13% from choosing a different, cheaper contract. A 7% gap between a daily bar close (a trade print, which on a thin low-delta option skews toward the bid) and live's intraday quote fill is good fidelity.

**Intraday theta is disconfirmed as the cause.** If the gap were time-of-day decay, shorter DTE would show a worse ratio — one day of decay is a bigger fraction of a 2-DTE option. The opposite holds: DTE 2 has the *best* ratio (0.966), DTE 5–6 the worst (0.61–0.62). The more likely driver is that live scans three times daily and takes the first qualifying moment, effectively capturing a best-of-three intraday price, while the replay takes one fixed EOD snapshot.

**Direction is conservative** — reported premium capture understates what live achieved — so results err toward calling a symbol unfit rather than fit. Recorded in every report's bias footer.

## Divergences are symmetric, not biased

Of the 36 diverged decisions (strike off by >2%), 19 were lower and 17 higher, median absolute difference 2.75%. Symmetric noise around live's choice rather than a systematic skew — had it leaned one way it would have indicated a scoring bug in the replay.

## Three further defects this exercise surfaced

Found while chasing why a 91-day NVDA replay produced one trade:

1. **Stale chain cache.** `MarketDataManager` caches the option chain with a wall-clock TTL (`time.time()`, 300s). A replay passes hundreds of simulated days in seconds of wall time, so the cache never expired and the strategy was served day one's chain forever — on 2025-10-20 it proposed a contract that had expired 17 days earlier. Cache ages now use `clock.now()`. NVDA October went from 1 trade to a proper weekly cadence of 5.
2. **`reconcile_positions()` was never called.** `run_strategy_cycle()` does not call it; production runs it as pre-trade housekeeping. It is what teaches `WheelStateManager` that a put expired or was assigned.
3. **`get_stock_bars(days=N)` means N calendar days**, not N bars. Slicing the last N *bars* handed callers ~43% more history, which changes every windowed statistic — `GapDetector`'s gap *frequency* is a ratio over exactly that window, and the longer window blocked NVDA for all of Nov 2025 (18.6% measured against a 15% limit) while live traded it on 7 days.

## Known residual divergence

After all three fixes, the replay trades NVDA once in Nov 2025 against live's 7. NVDA's gap frequency sits near the 15% threshold in that period, so small data differences flip the gate. Live also scans three times daily and can pass on any one of them, while the replay decides once at the close. Not chased further: the primary fidelity metric is *selection* (81% strike reproduction), and this is a gate-timing artifact rather than a modelling error. Worth revisiting if a symbol's verdict ever hinges on gap-filter behavior.

## What this does and does not establish

**Does:** the reconstructed chain, the BS greeks, and the delta/DTE/premium filters reproduce live's contract choice ~81% of the time and land in the correct delta band 100% of the time. The replay is driving the real strategy code over real data and arriving at approximately real decisions.

**Does not:** validate P&L. Parity measures selection at entry, not outcome. Nothing here checks assignment handling, cost-basis floors, or rolling — those are covered by the golden-path integration test and the broker's unit tests.
