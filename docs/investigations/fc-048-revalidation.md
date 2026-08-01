# FC-048 re-validation: what changed when the backtest stopped running half a wheel

> **⚠️ Predates FC-068 (2026-08-01).** These numbers came from the engine-path replay.
> FC-068 repointed the simulator onto the production scan → select → execute pipeline
> and premium-netted the assignment basis, so **every figure here is non-comparable
> with post-FC-068 runs**. The finding it established — that every backtest before
> FC-048 ran a put-only wheel — stands; the magnitudes do not. Also of note: FC-048
> never bumped `ENGINE_VERSION`, so its boundary is timestamp-only (2026-07-29);
> FC-068's is queryable (`engine_version = 'fc-068-prod-pipeline'`).


**Date:** 2026-07-29
**Trigger:** FC-048 (PR #57, `ea5cfa5`) — covered calls were misrouted to `put_seller`
and rejected, so every backtest this project had ever run modelled a **put-only**
strategy. This document re-runs the affected verdicts.

**Headline: the fix was real and worth making — but the hypothesis that motivated the
re-validation is FALSIFIED.** The FC-032 Phase 5 finding that 7 of 14 symbols were
flagged for "not closing a cycle" is **not** primarily a put-only artifact. It is
overwhelmingly a **stage-1 price-band exclusion** plus the **premium floor**. Details in
R2.

---

## R1 — NVDA, 2-year window

`python main.py --command backtest --symbol NVDA --start 2024-07-01 --end 2026-07-01`

| | pre-fix (put-only) | post-fix |
|---|---:|---:|
| puts sold | 30 | **45** |
| calls sold | **0** | **7** |
| completed cycles | 29 | **44** |
| total P&L | +$4,532 | **+$2,296** |
| verdict | MARGINAL | MARGINAL |

Three things worth reading carefully:

1. **The put count changes too.** Pre-fix, the first assignment locked the wheel in
   shares permanently and suppressed the remaining 15 puts. The fix frees the position
   slot, so the whole post-assignment trajectory differs. Cycles 1–29 are date-and-dollar
   identical up to the first assignment — put-side routing is untouched.
2. **Returns go DOWN, and that is the fix working.** The put-only wheel rode NVDA up as
   unrealized stock gains; the corrected wheel gets called away at the strike. **A
   backtest that looked better was overstating the strategy.**
3. **"44 completed cycles" is not 44 completed wheels.** 43 are single-put
   expire-worthless turns, which a put-only engine also produces (pre-fix: 29). Exactly
   **1** cycle is `called_away`. Full-wheel completions: **0 → 1**, plus 6 more calls on
   a still-open position.

---

## R2 — Full 14-symbol screen (post-fix, `--no-persist`)

| verdict | symbols | days in position |
|---|---|---|
| `insufficient` | AMD, F, PFE, QQQ, SPY, VZ | **0%** — never opened a position |
| `marginal` | AAPL, AMZN, GOOGL, IWM, NVDA, UNH | 61–93% |
| `unfit` | KMI (5%), MSFT (2%) | near-zero |

### The FC-048 hypothesis is falsified

`docs/plans/fc-048.md` R2 predicted the `insufficient` verdicts were "plausibly 100%
artifact" of the put-only engine, because a cycle cannot close without a call leg. **That
is wrong.** All six `insufficient` symbols show **0% days in position** — they never
opened *any* position, put or call. A missing call leg cannot explain a symbol that never
sold a put.

The real causes, verified against live quotes and `config/settings.yaml`
(`min_stock_price: 10.00`, `max_stock_price: 400.00`):

| symbol | spot (2026-07-29) | why it never traded |
|---|---:|---|
| SPY | $736.47 | **above the $400 ceiling** → stage-1 block |
| QQQ | $670.92 | **above the $400 ceiling** → stage-1 block |
| AMD | $441.82 | **above the $400 ceiling** → stage-1 block |
| F | $15.50 | premium floor — richest in-band put pays $0.03 (FC-034) |
| PFE | $25.20 | premium floor — $0.07 (FC-034) |
| VZ | $48.09 | premium floor — $0.08 (FC-034) |

And the two `unfit` symbols are the same two stories at the boundary:

- **MSFT $395.39** — within **$5** of the $400 ceiling. Its 2% days-in-position is a
  symbol oscillating across a hard config line, not a strategy failure.
- **KMI $31.84** — the premium-floor cohort (5% days).

### What that means: the effective universe is 6, not 14

| bucket | count | symbols |
|---|---:|---|
| structurally excluded — price ceiling | 3 | SPY, QQQ, AMD |
| structurally excluded — premium floor | 4 | F, PFE, KMI, VZ |
| boundary (oscillating on the ceiling) | 1 | MSFT |
| **actually trading** | **6** | AAPL, AMZN, GOOGL, IWM, NVDA, UNH |

**8 of 14 configured symbols cannot meaningfully trade**, and none of it is the FC-048
bug. This is filed as **FC-055** (price ceiling) and is already covered for the low-price
cohort by **FC-034**'s DEMOTE verdict.

The price ceiling is the more surprising half: AMD is the second-largest premium
generator in the account's history and **SPY/QQQ are the two most liquid options markets
in existence**. They are excluded by a `max_stock_price` that has not moved as the market
rose.

### Provenance note required

Prior rows in `options_wheel.backtest_runs` were produced by the put-only engine. A dated
note goes in `docs/bigquery/backtest_runs.md`; **rows are not edited or deleted** —
provenance is the timestamp plus `config_hash`.

This run was **not persisted**: the first *persisted* post-fix screen should be a
deliberate decision (Track D), not a side effect of re-validation.

---

## R3 — The three studies

| study | headline | rests on | status |
|---|---|---|---|
| `fc-036-gap-gate-study.md` | **DO-NOT-ARM** | Layer 3: 330 real BigQuery fills | **Stands.** Engine layers are put-only and labelled; the verdict never depended on them. |
| `fc-002-gap-filter-ab.md` | **don't re-tune; resolve FC-049 first** | real-fills + overlay | **Stands** — and is strengthened: FC-049 showed the filter never ran live at all. |
| `fc-034-premium-floor-ab.md` | **DEMOTE** F/PFE/KMI/VZ | chain-level premium + real fills | **Stands, and R2 independently reproduces it** — all four show 0–5% days in position on a full post-fix screen. |

No headline conclusion moves. All three rested on real-fills layers rather than the
engine, which is exactly why they survive a change of this size — the reason that layer
was required.

---

## R4 / R5 — still open

- **R4 (Track C):** C2 (ex-div early assignment) has still never fired in a real replay —
  it needs a dividend payer holding an ITM short call, and the payers are precisely the
  symbols that cannot trade (F/PFE/KMI/VZ). **C2 remains validated only by unit tests.**
  C1's wheel-side dividend totals should now be *lower* on symbols where calls remove
  shares; NVDA moved 26.00 → 25.00, directionally correct but too small to be evidence.
- **R5 (call-side parity):** not yet run. The 81% strike-reproduction claim in
  `docs/plans/fc-032.md` is **put-only by construction** (its 204 decisions are put
  sell-to-open fills). Call-side selection fidelity has never been measured, and the
  engine only just became capable of producing calls to measure.

---

## Verdict on the engine

FC-048 was worth fixing: the engine now models the strategy that actually runs, and it
does so *less* flatteringly. But the re-validation's own finding is that **the dominant
constraint on this strategy is configuration, not engine fidelity** — a $400 price
ceiling and a $0.50 premium floor between them exclude 8 of 14 symbols. That is a bigger
lever than anything in the backtest engine, and it was invisible while every verdict was
being read as a *strategy* result.
