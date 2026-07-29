# FC-036 Half 1 — what a *working* stage-4 gap gate would have done

**Date:** 2026-07-29
**Plan:** [docs/plans/fc-036.md](../plans/fc-036.md) — "Half 1 — Study design"
**Branch:** `fc-036-gap-gate` (Phase A merged: gate math fixed, threshold 999, disarmed)
**Harness:** [`tools/diagnostics/fc036_gap_gate_study.py`](../../tools/diagnostics/fc036_gap_gate_study.py)
**Question:** before Phase B arms the gate, what would it have blocked over 2024-02 → 2026-07, and would blocking have helped or cost money?

---

## Verdict

**AGAINST arming — at 1.5, and on this evidence at any swept threshold.** All three of the
plan's pre-registered "do not ship" rules fire, and the decisive one now rests on **330 real
fills from BigQuery**, not on simulation: a working 1.5 gate would have cost the account
**$5,021**, a quarter of everything the strategy realized in ten months, while preventing
no loss it could not afford. Merge the correctness fix; leave the threshold at 999.

| pre-registered rule | fires? | evidence |
|---|---|---|
| **(a)** blocked trades net-profitable by >5% of window premium income, with no offsetting tail-loss reduction | **YES** — on **330 real fills from BigQuery**, not simulation | at 1.5 a working gate blocks **96 of 327 real entries**, forgoing **$22,621 of $68,518 premium (33%)** and costing the account **$5,021 net = 7.3% of window premium income and 24% of everything the strategy realized in ten months** (86 winners / 10 losers). Partial tail reduction exists at 1.5 and does not pay for itself; at 3.5 and 5.0 there is **none at all** — every blocked trade was a winner. |
| **(b)** return-on-collateral improves monotonically as the threshold rises, with no drawdown/worst-cycle improvement at tighter thresholds | **YES** | NVDA return-on-collateral 19.31% → 19.98% → 32.92% → 33.64% → 33.64% across 1.5 / 2.5 / 3.5 / 5.0 / 999. Max drawdown is **worse** armed at 1.5 (−4.05%) than unarmed (−3.97%). Worst cycle is unchanged. AMD and IWM show the same shape; AAPL and GOOGL are flat. Monotone on all five symbols run. |
| **(c)** 09:35-measure block rate at 1.5 above ~25-30% of days on NVDA/AMD | **YES, on every framing of the measure** | 09:35 reconstruction: **NVDA 37.64%, AMD 41.61%**. Daily open vs prior close: 32.31% / 37.10%. Even the most forgiving framing — *all three* daily scans must block for the day to be lost — is **25.53% / 29.52%**. |

**Recommendation.**

1. **Merge the Phase A correctness fix.** It is not threshold-dependent, and the case for
   it is *stronger* than the plan assumed: the broken gate was never inert. Reconstructed
   from intraday bars, it **blocked 185 sessions across six symbols** (AMD alone 110, or
   17.7% of AMD's sessions) — 12% of those blocks on days with no real gap at any scan —
   while **missing 79–100% of the sessions a working gate would have caught**. Production
   has been blocking trades on drift *and* failing to block on signal, simultaneously.
2. **Do not arm — at 1.5 or at any other swept threshold. Hold at 999.** Against real
   fills, every swept threshold is net-negative and none of them prevented a loss that
   mattered:

   | threshold | real entries blocked | premium forgone | **net cost to the account** | assignments avoided | losing trades blocked |
   |---:|---:|---:|---:|---:|---:|
   | 1.5 | 96 | $22,621 (33%) | **−$5,021** | 10 of 29 | 10 of 22 |
   | 2.5 | 39 | $9,502 (14%) | **−$4,291** | 5 of 29 | 3 of 22 |
   | 3.5 | 11 | $3,872 (6%) | **−$2,781** | **0** | **0** |
   | 5.0 | 6 | $2,533 (4%) | **−$1,900** | **0** | **0** |

   The engine A/B suggested 5.0 was free. Real fills say it is not: it would have blocked
   six entries, all six of them winners, for $1,900. **A threshold that only ever blocks
   profitable trades is not insurance, it is a tax.**

3. **If the owner still wants a stage-4 circuit breaker, it should be sized to a regime
   this window does not contain, and the argument for it is not in this data.** The
   defensible framing is explicitly *insurance against 2018/2020-style gaps*, priced at
   roughly $1,900 per ten months at 5.0 — a decision about risk appetite, not one this
   study can settle. What this study can settle is that **1.5 is indefensible**: it costs
   a quarter of realized P&L and embargoes NVDA and AMD on ~38% and ~42% of sessions.

4. **Revisit jointly with FC-002/B1.** Stage 2 currently removes 57–87% of decision days on
   the symbols where gap risk is real. Every rate in this study is conditional on that. If
   B1 loosens stage 2, stage 4 at 3.5–5.0 becomes materially more useful than it looks
   here, and this study should be re-run — the harness makes that a one-command job.

Full reasoning under [Pre-registered decision rules, applied](#pre-registered-decision-rules-applied).

---

## Method

Everything below is produced by the committed harness. The tables are **emitted** by
`fc036_gap_gate_study.py markdown`, not typed by hand.

```bash
OUT=/tmp/fc036
python tools/diagnostics/fc036_gap_gate_study.py layer1    --out $OUT   # 14 configured symbols
python tools/diagnostics/fc036_gap_gate_study.py intraday  --out $OUT   # 5-minute reconstruction
python tools/diagnostics/fc036_gap_gate_study.py layer2    --symbol NVDA --out $OUT   # one process per symbol
python tools/diagnostics/fc036_gap_gate_study.py equiv     --symbol NVDA --start 2025-10-01 --end 2025-12-31 --out $OUT
python tools/diagnostics/fc036_gap_gate_study.py fccheck   --out $OUT
python tools/diagnostics/fc036_gap_gate_study.py attribute --out $OUT
python tools/diagnostics/fc036_gap_gate_study.py layer3    --out $OUT   # BQ real-fills join (needs gcloud auth login)
python tools/diagnostics/fc036_gap_gate_study.py markdown  --out $OUT
```

**Window:** 2024-02-01 → 2026-07-24 (Alpaca's options-history floor), 620 trading days per
symbol. The ratio-based split detector found exactly one corporate action across all 14
symbols in-window — NVDA 10:1 on 2024-06-10, ratio 0.1007 — and that day is excluded from
every layer-1 statistic.

### Four measures. They are not interchangeable, and conflating them is how this gate stayed broken.

| name | definition | who computes it |
|---|---|---|
| **overnight gap** | `(open_D − close_{D−1}) / close_{D−1}` | the classic gap; open is the 09:30 auction |
| **fixed gate @ scan** | `(px_scan − close_{D−1}) / close_{D−1}` | what the **fixed** gate reads live at 09:35 / 12:00 / 15:00 |
| **close-to-close** | `(close_D − close_{D−1}) / close_{D−1}` | what the **engine A/B** reads: the sim decides once at 16:00 and its quote *is* the close |
| **broken measure** | `(px_scan − px_{scan−20min}) / px_{scan−20min}` | what the gate **actually computed in production** until FC-036 |

Two things validated rather than assumed, because the whole study rests on them:

- **Alpaca's daily-bar `open` is the regular-session open, not the 04:00 pre-market open.**
  NVDA 2026-07-21 daily open 207.54 = the 13:30 UTC (09:30 ET) minute bar's open, exactly.
  SPY 2024-11-06 daily open 589.20 = the 14:30 UTC minute bar's open, exactly. AMD
  2025-03-12 daily open 99.045 sits inside the 09:30 minute bar's 99.02–99.07 range
  (which opening print is used differs by fractions of a cent). It is emphatically not a
  pre-market print.
- **In replay the fixed gate measures close-to-close.**
  `BacktestAlpacaClient.get_stock_quote` returns `bid = ask = close`
  (`src/backtesting/engine/alpaca_adapter.py:211-224`), so `current_price = close_D` and
  the gate compares it to `close_{D−1}`.

---

## Layer 1 — measurement (daily bars, no engine)

| symbol | n | on>1.5 | on>2.5 | on>3.5 | on>5.0 | c2c>1.5 | c2c>2.5 | c2c>3.5 | c2c>5.0 | median \|on\| | p99 \|on\| | max \|on\| |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AAPL | 620 | 8.71% | 3.39% | 1.77% | 0.97% | 26.61% | 11.61% | 5.00% | 1.29% | 0.38% | 4.92% | 9.45% |
| MSFT | 620 | 8.71% | 3.06% | 1.29% | 0.65% | 25.32% | 8.71% | 3.23% | 1.13% | 0.43% | 3.97% | 9.07% |
| GOOGL | 620 | 14.19% | 5.65% | 3.23% | 1.61% | 35.32% | 14.35% | 6.94% | 1.94% | 0.53% | 6.25% | 11.78% |
| AMZN | 620 | 15.81% | 5.32% | 3.23% | 2.10% | 35.97% | 15.65% | 6.29% | 1.77% | 0.53% | 6.76% | 12.22% |
| NVDA | 619 | 32.31% | 12.76% | 4.68% | 1.94% | 56.38% | 34.73% | 21.49% | 7.75% | 1.01% | 6.82% | 14.18% |
| AMD | 620 | 37.10% | 18.06% | 10.32% | 4.84% | 58.06% | 38.55% | 26.29% | 12.74% | 1.03% | 8.06% | 37.51% |
| QQQ | 620 | 7.74% | 1.77% | 0.65% | 0.16% | 20.32% | 5.65% | 1.45% | 0.48% | 0.41% | 3.31% | 5.36% |
| SPY | 620 | 2.58% | 1.13% | 0.16% | 0.00% | 10.00% | 2.10% | 0.65% | 0.32% | 0.28% | 2.60% | 3.99% |
| IWM | 620 | 6.61% | 2.58% | 1.13% | 0.32% | 21.94% | 5.97% | 2.26% | 0.48% | 0.45% | 3.57% | 5.51% |
| UNH | 620 | 9.19% | 4.68% | 3.55% | 2.58% | 35.00% | 15.32% | 7.58% | 4.35% | 0.36% | 10.75% | 17.62% |
| F | 620 | 9.03% | 3.39% | 1.77% | 0.81% | 39.03% | 18.71% | 9.68% | 3.06% | 0.41% | 4.40% | 13.68% |
| PFE | 620 | 3.55% | 1.61% | 0.48% | 0.00% | 26.61% | 9.03% | 3.23% | 0.81% | 0.26% | 2.77% | 4.88% |
| KMI | 620 | 4.19% | 1.94% | 1.13% | 0.00% | 22.58% | 7.26% | 1.94% | 0.48% | 0.30% | 3.54% | 4.06% |
| VZ | 620 | 5.16% | 1.61% | 0.81% | 0.32% | 18.87% | 6.94% | 2.90% | 1.29% | 0.25% | 3.17% | 6.99% |

### Distribution tails

`|overnight gap| > 5%` is rare on the index ETFs and routine on the high-beta names — the
`on>5.0` column above. AMD 4.84% of sessions, UNH 2.58%, AMZN 2.10%, NVDA 1.94%, GOOGL
1.61%; SPY, PFE and KMI did it zero times in 620 sessions. The single largest overnight
gap in the window is **AMD +37.51%** (a genuine move — the split detector flagged no AMD
day). UNH has the fattest tail relative to its typical day: a 0.36% median absolute gap
against a 10.75% p99.

**At 1.5, this is not a tail control on the high-beta names — it is a median control.**
NVDA's and AMD's median absolute overnight gap is ~1.0%. A 1.5 threshold sits just above
the middle of their distributions, which is exactly why the block rate lands above 30%.

### Misclassification 1 — the replay over-blocks; read Layer 2 through this

Close-to-close and the overnight gap are different signals. At threshold 1.5 they disagree
on 9–40% of days, asymmetrically: on every symbol the replay measure blocks far more days
than a live gate would, and it still misses a fifth to a half of the days the live gate
*would* block.

| symbol | both block | live-only | replay-only | neither | agreement | replay misses of live blocks | replay blocks live would pass |
|---|---:|---:|---:|---:|---:|---:|---:|
| AAPL | 35 | 19 | 130 | 436 | 76.0% | 35.2% | 78.8% |
| MSFT | 39 | 15 | 118 | 448 | 78.5% | 27.8% | 75.2% |
| GOOGL | 56 | 32 | 163 | 369 | 68.5% | 36.4% | 74.4% |
| AMZN | 69 | 29 | 154 | 368 | 70.5% | 29.6% | 69.1% |
| NVDA | 150 | 50 | 199 | 220 | 59.8% | 25.0% | 57.0% |
| AMD | 174 | 56 | 186 | 204 | 61.0% | 24.4% | 51.7% |
| QQQ | 33 | 15 | 93 | 479 | 82.6% | 31.2% | 73.8% |
| SPY | 11 | 5 | 51 | 553 | 91.0% | 31.2% | 82.3% |
| IWM | 29 | 12 | 107 | 472 | 80.8% | 29.3% | 78.7% |
| UNH | 43 | 14 | 174 | 389 | 69.7% | 24.6% | 80.2% |
| F | 45 | 11 | 197 | 367 | 66.5% | 19.6% | 81.4% |
| PFE | 15 | 7 | 150 | 448 | 74.7% | 31.8% | 90.9% |
| KMI | 14 | 12 | 126 | 468 | 77.7% | 46.1% | 90.0% |
| VZ | 21 | 11 | 96 | 492 | 82.7% | 34.4% | 82.0% |

Read the last column literally. On NVDA, 57% of the days the engine's stage 4 blocks are
days the live 09:35 gate would have let through — the move happened *during* the session,
not overnight. **Every stage-4 blocked-day count in Layer 2 is therefore an upper bound on
live blocking, roughly 2× too high.** That biases the engine A/B *against* the gate, which
is why the verdict does not rest on Layer 2 alone.

### Misclassification 2 — what the broken gate actually measured

The plan states the broken gate's spurious-fire rate is "not historically reconstructible
(needs 9:15-vs-9:35 intraday prints)". **It is reconstructible.** Alpaca serves historical
intraday bars, including pre-market, on the entitlement this project already holds. Every
timestamp the study needs (09:15, 09:35, 12:00, 15:00) lands on a 5-minute boundary, so
5-minute bars suffice and cut the wire volume 5× against 1-minute bars.

The broken gate's "previous close" was the current session's *partial* daily bar, whose
close is the last print as of `now − 20 min` (`src/api/alpaca_client.py:391`) — so ~09:15
at the 09:35 scan. Its "current price" was a live IEX quote midpoint. Both legs are
reconstructed here from consolidated 5-minute trade prints.

| symbol | n | broken fired | of which spurious | fixed would fire | of those, broken MISSED | agreement |
|---|---:|---:|---:|---:|---:|---:|
| NVDA | 619 | 31 (5.01%) | 14 (45.2%) | 233 (37.64%) | 216 (92.7%) | 62.8% |
| AMD | 620 | 103 (16.61%) | 31 (30.1%) | 258 (41.61%) | 186 (72.1%) | 65.0% |
| AAPL | 620 | 14 (2.26%) | 4 (28.6%) | 71 (11.45%) | 61 (85.9%) | 89.5% |
| GOOGL | 620 | 19 (3.06%) | 5 (26.3%) | 108 (17.42%) | 94 (87.0%) | 84.0% |
| SPY | 620 | 0 (0.00%) | 0 (0.0%) | 17 (2.74%) | 17 (100.0%) | 97.3% |
| IWM | 620 | 0 (0.00%) | 0 (0.0%) | 49 (7.90%) | 49 (100.0%) | 92.1% |

**The broken gate was not inert. It was wrong in both directions.** Over 3,719 symbol-days
across these six symbols, at the threshold production actually ran (1.5):

- It **blocked 185 sessions** (5.0%) — 110 of them AMD, 38 NVDA, 20 GOOGL, 15 AAPL, 2 IWM,
  0 SPY. Those are real entries production declined to take.
- **23 of those 185 blocks (12.4%) landed on sessions where no scan had a real >1.5% gap
  at all** — pure 20-minute-drift false positives. Per-scan the picture is worse: of the 31
  sessions where its 09:35 leg fired on NVDA, **14 (45%) were sessions the fixed 09:35 gate
  would have passed.**
- It **missed 79–100% of the sessions a working gate would have blocked**: 395 of NVDA's
  431, 352 of AMD's 445, 190 of AAPL's 204, 241 of GOOGL's 258, 152 of IWM's 154, and
  **all 62 of SPY's** — SPY and IWM never tripped the broken gate once in 620 sessions.

The reason it half-works is structural: the ~09:15→09:35 window straddles the opening
auction, so it captures the *last fraction* of the overnight gap's realisation and none of
what happened before 09:15. It is a low-power, biased estimator of the thing it claims to
measure — which is exactly why nobody caught it by eyeballing `gap_percent` in the logs.

One honest mitigation: the broken gate **never blocked all three scans on the same day**
for any symbol (`broken_all_scans_block_pct` = 0.00% everywhere). Its false positives cost
at most one of three daily entry opportunities, not the whole day.

### Scan coverage — how much of the blocking a live day actually absorbs

The bot scans ~09:35 / 12:00 / 15:00 ET (`docs/investigations/fc-032-parity-check.md`); the
replay decides once. A day only loses its entry entirely if **all three** scans exceed the
threshold. Both bounds, plus the broken gate's real footprint across all three scans:

| symbol | thr | fires at 09:35 | fires at >=1 of 3 scans | fires at ALL 3 scans (day fully lost) | broken gate fired at >=1 scan |
|---|---:|---:|---:|---:|---:|
| NVDA | 1.5 | 37.64% | 69.63% | 25.53% | 6.14% |
| NVDA | 2.5 | 13.09% | 40.71% | 8.56% | 0.81% |
| NVDA | 3.5 | 5.49% | 23.10% | 3.39% | 0.00% |
| NVDA | 5.0 | 2.10% | 9.05% | 1.29% | 0.00% |
| AMD | 1.5 | 41.61% | 71.77% | 29.52% | 17.74% |
| AMD | 2.5 | 24.35% | 49.03% | 17.42% | 3.39% |
| AMD | 3.5 | 13.39% | 31.94% | 9.19% | 0.48% |
| AMD | 5.0 | 5.65% | 15.65% | 3.87% | 0.16% |
| AAPL | 1.5 | 11.45% | 32.90% | 8.39% | 2.42% |
| AAPL | 2.5 | 3.87% | 12.90% | 2.74% | 0.32% |
| AAPL | 3.5 | 1.29% | 5.81% | 0.97% | 0.00% |
| AAPL | 5.0 | 0.97% | 2.26% | 0.32% | 0.00% |
| GOOGL | 1.5 | 17.42% | 41.61% | 10.81% | 3.23% |
| GOOGL | 2.5 | 7.10% | 17.26% | 4.35% | 0.16% |
| GOOGL | 3.5 | 3.06% | 7.42% | 2.10% | 0.00% |
| GOOGL | 5.0 | 1.94% | 2.74% | 0.97% | 0.00% |
| SPY | 1.5 | 2.74% | 10.00% | 1.94% | 0.00% |
| SPY | 2.5 | 1.29% | 2.42% | 0.32% | 0.00% |
| SPY | 3.5 | 0.16% | 0.81% | 0.00% | 0.00% |
| SPY | 5.0 | 0.00% | 0.48% | 0.00% | 0.00% |
| IWM | 1.5 | 7.90% | 24.84% | 5.16% | 0.32% |
| IWM | 2.5 | 2.42% | 6.94% | 1.45% | 0.00% |
| IWM | 3.5 | 0.97% | 1.94% | 0.65% | 0.00% |
| IWM | 5.0 | 0.16% | 0.97% | 0.00% | 0.00% |

### The FC-entry "3 of 5" correction

The FC-036 entry claims 3 of 5 sampled NVDA days should have blocked at 1.5. The plan
corrected this to 2 of 5 by arithmetic on the entry's own listed gaps. Recomputed from
bars — the five cited sessions are 2026-07-13 … 2026-07-17, whose gaps match the entry's
list exactly:

| session | prior close | open | overnight gap | blocks at 1.5? |
|---|---:|---:|---:|---|
| 2026-07-13 | 210.96 | 208.54 | −1.147% | no |
| 2026-07-14 | 203.53 | 208.20 | **+2.295%** | **yes** |
| 2026-07-15 | 211.80 | 211.96 | +0.076% | no |
| 2026-07-16 | 212.50 | 210.17 | −1.096% | no |
| 2026-07-17 | 207.40 | 202.64 | **−2.295%** | **yes** |

**2 of 5, confirmed from data. Do not propagate "3 of 5".** The qualitative claim behind it
— real overnight gaps that should have blocked did not — stands.

---

## Layer 2 — engine A/B (counterfactual outcomes)

Every arm runs the fix-branch code with a **fresh `Config()` per arm** and the threshold
injected at `config._config["risk"]["gap_risk_controls"]["execution_gap_threshold"]`
(`Config.execution_gap_threshold` is a read-only property). The bid-fill sensitivity pass
is disabled: it answers a different question and doubles runtime.

### Arm-A equivalence — Phase A is a provable no-op to replayed behaviour

The plan asserts arm A (fixed code at 999) is behaviourally identical to pre-fix production
(broken code armed at 1.5), because the broken gate compares `close_D` to `close_D` and
reads exactly 0.0%. The harness **proves** it: it monkeypatches the verbatim pre-fix
`_get_previous_close` (from `110694a`) onto `GapDetector` for one run and diffs ledgers and
equity curves.

```
NVDA 2025-10-01 .. 2025-12-31
  fixed code @ 999   : 12 ledger events, final equity 100612.210509, stage-4 blocked 0
  broken code @ 1.5  : 12 ledger events, final equity 100612.210509, stage-4 blocked 0
  ledgers_identical      : true
  equity_curves_identical: true
  VERDICT: EQUIVALENT
```

Two things this settles. Phase A ships a **provable no-op** to replayed behaviour, so the
correctness fix can merge on its own merits with the arming decision left open. And the
plan's claim that the broken gate never fires *in replay* is confirmed empirically —
0 blocked days at threshold 1.5 — which is precisely why the replay could not have found
this bug on its own and why Layer 1's intraday reconstruction was necessary.

### Arms

| symbol | window | arm | return | return on collateral | max DD | puts | calls | assign | stage-4 blocked days | decision days |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| NVDA | 2024-08-15..2026-07-24 | 999 (shadow) | 5.46% | 33.64% | -3.97% | 30 | 0 | 1 | 0 | 486 |
| NVDA | 2024-08-15..2026-07-24 | 1.5 | 3.09% | 19.31% | -4.05% | 20 | 0 | 1 | 92 | 486 |
| NVDA | 2024-08-15..2026-07-24 | 2.5 | 3.19% | 19.98% | -4.05% | 21 | 0 | 1 | 47 | 486 |
| NVDA | 2024-08-15..2026-07-24 | 3.5 | 5.35% | 32.92% | -3.97% | 29 | 0 | 1 | 23 | 486 |
| NVDA | 2024-08-15..2026-07-24 | 5.0 | 5.46% | 33.64% | -3.97% | 30 | 0 | 1 | 3 | 486 |
| AMD | 2024-02-01..2026-07-24 | 999 (shadow) | 35.13% | 210.41% | -9.44% | 2 | 0 | 1 | 0 | 621 |
| AMD | 2024-02-01..2026-07-24 | 1.5 | 35.12% | 204.88% | -9.44% | 2 | 0 | 1 | 13 | 621 |
| AMD | 2024-02-01..2026-07-24 | 2.5 | 35.12% | 204.88% | -9.44% | 2 | 0 | 1 | 8 | 621 |
| AMD | 2024-02-01..2026-07-24 | 3.5 | 35.12% | 204.88% | -9.44% | 2 | 0 | 1 | 6 | 621 |
| AMD | 2024-02-01..2026-07-24 | 5.0 | 35.13% | 210.41% | -9.44% | 2 | 0 | 1 | 0 | 621 |
| AAPL | 2024-02-01..2026-07-24 | 999 (shadow) | 13.10% | 75.52% | -8.18% | 9 | 0 | 1 | 0 | 621 |
| AAPL | 2024-02-01..2026-07-24 | 1.5 | 13.11% | 75.50% | -8.18% | 9 | 0 | 1 | 144 | 621 |
| AAPL | 2024-02-01..2026-07-24 | 2.5 | 13.10% | 75.52% | -8.18% | 9 | 0 | 1 | 56 | 621 |
| AAPL | 2024-02-01..2026-07-24 | 3.5 | 13.10% | 75.52% | -8.18% | 9 | 0 | 1 | 19 | 621 |
| AAPL | 2024-02-01..2026-07-24 | 5.0 | 13.10% | 75.52% | -8.18% | 9 | 0 | 1 | 3 | 621 |
| GOOGL | 2024-02-01..2026-07-24 | 999 (shadow) | 18.01% | 126.83% | -6.71% | 1 | 0 | 1 | 0 | 621 |
| GOOGL | 2024-02-01..2026-07-24 | 1.5 | 18.01% | 126.83% | -6.71% | 1 | 0 | 1 | 168 | 621 |
| GOOGL | 2024-02-01..2026-07-24 | 2.5 | 18.01% | 126.83% | -6.71% | 1 | 0 | 1 | 60 | 621 |
| GOOGL | 2024-02-01..2026-07-24 | 3.5 | 18.01% | 126.83% | -6.71% | 1 | 0 | 1 | 26 | 621 |
| GOOGL | 2024-02-01..2026-07-24 | 5.0 | 18.01% | 126.83% | -6.71% | 1 | 0 | 1 | 4 | 621 |
| IWM | 2024-02-01..2026-07-24 | 999 (shadow) | 9.91% | 51.49% | -6.35% | 3 | 0 | 1 | 0 | 621 |
| IWM | 2024-02-01..2026-07-24 | 1.5 | 10.04% | 50.40% | -6.34% | 8 | 0 | 1 | 128 | 621 |
| IWM | 2024-02-01..2026-07-24 | 2.5 | 10.11% | 50.97% | -6.34% | 9 | 0 | 1 | 32 | 621 |
| IWM | 2024-02-01..2026-07-24 | 3.5 | 9.91% | 51.49% | -6.35% | 3 | 0 | 1 | 12 | 621 |
| IWM | 2024-02-01..2026-07-24 | 5.0 | 9.91% | 51.49% | -6.35% | 3 | 0 | 1 | 2 | 621 |

**Read this table with one caveat first, because it is the difference between evidence and
noise: only NVDA traded enough for the A/B to say anything.** Over 2.5 years the replayed
strategy opened **1 put on GOOGL, 2 on AMD, 3 on IWM, 9 on AAPL** and 30 on NVDA. Stage 2 blocked 539
of AMD's 621 decision days and 108 of GOOGL's; after the single assignment on each symbol,
stage 5/6 and the cost-basis drawdown pause hold the rest. So AMD/AAPL/GOOGL/IWM arms being
near-identical is **not** evidence the gate is harmless — it is evidence there was almost
nothing left for it to block. Their headline returns (35%, 13%, 18%) are one long stock
position appreciating, not wheel income: AMD's $35,126 of P&L is $34,945 unrealised stock
against **$181** of option premium.

What the table does establish:

- **NVDA, the only symbol with a real sample, loses 43% of its return-on-collateral at 1.5**
  (33.64% → 19.31%) and 41% at 2.5. Ten of its thirty entries disappear.
- **Nothing improves in exchange.** Max drawdown goes the wrong way (−3.97% unarmed →
  −4.05% at 1.5). Worst cycle is unchanged at +$50. There were **no losing cycles on any
  symbol at any threshold** across the whole window — the largest loss the gate could
  possibly have averted is zero.
- **3.5 is where the cost starts.** NVDA at 3.5 keeps 29 of 30 entries and 97.9% of its
  unarmed return-on-collateral; at 5.0 it is byte-identical to unarmed while still blocking
  3 replay days. AMD's small cost appears at 3.5 too (210.41% → 204.88%).
- **Stage-4 blocked-day counts here are the close-to-close measure and run ~2× live.**
  GOOGL's 168 blocked days at 1.5 corresponds to a live 09:35 rate of 17.42%, not 27%.
- **Do not read arm-vs-arm rejection diffs as causal.** NVDA's `drawdown pause` count jumps
  from 2 (unarmed) to 45 (at 1.5) — that is path divergence, not a second effect of the
  gate: blocking entries changed which shares were held and when.

### Attribution — what the gate would have taken away

Post-hoc join, no path contamination: the **baseline (999) arm's** option-open ledger
events joined against the layer-1 gap table — "trades the gate would have prevented,
valued in the world where they actually happened". Where the 5-minute reconstruction
exists this uses the **live 09:35 measure**, not close-to-close, so these are realistic
figures rather than the replay's inflated ones.

| symbol | opens | premium | thr | opens blocked | premium blocked | % of premium | cycles blocked | P&L of those cycles | winners | losers |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| NVDA | 30 | $2,498 | 1.5 | 12 | $1,035 | 41.4% | 12 | $1,061 | 12 | 0 |
| NVDA | 30 | $2,498 | 2.5 | 3 | $222 | 8.9% | 3 | $222 | 3 | 0 |
| NVDA | 30 | $2,498 | 3.5 | 1 | $55 | 2.2% | 1 | $55 | 1 | 0 |
| NVDA | 30 | $2,498 | 5.0 | 0 | $0 | 0.0% | 0 | $0 | 0 | 0 |
| AMD | 2 | $181 | 1.5 | 1 | $77 | 42.5% | 1 | $77 | 1 | 0 |
| AMD | 2 | $181 | 2.5 | 1 | $77 | 42.5% | 1 | $77 | 1 | 0 |
| AMD | 2 | $181 | 3.5 | 0 | $0 | 0.0% | 0 | $0 | 0 | 0 |
| AMD | 2 | $181 | 5.0 | 0 | $0 | 0.0% | 0 | $0 | 0 | 0 |
| AAPL | 9 | $589 | 1.5 | 1 | $78 | 13.2% | 1 | $78 | 1 | 0 |
| AAPL | 9 | $589 | 2.5 | 1 | $78 | 13.2% | 1 | $78 | 1 | 0 |
| AAPL | 9 | $589 | 3.5 | 0 | $0 | 0.0% | 0 | $0 | 0 | 0 |
| AAPL | 9 | $589 | 5.0 | 0 | $0 | 0.0% | 0 | $0 | 0 | 0 |
| GOOGL | 1 | $49 | 1.5 | 0 | $0 | 0.0% | 0 | $0 | 0 | 0 |
| GOOGL | 1 | $49 | 2.5 | 0 | $0 | 0.0% | 0 | $0 | 0 | 0 |
| GOOGL | 1 | $49 | 3.5 | 0 | $0 | 0.0% | 0 | $0 | 0 | 0 |
| GOOGL | 1 | $49 | 5.0 | 0 | $0 | 0.0% | 0 | $0 | 0 | 0 |
| IWM | 3 | $167 | 1.5 | 0 | $0 | 0.0% | 0 | $0 | 0 | 0 |
| IWM | 3 | $167 | 2.5 | 0 | $0 | 0.0% | 0 | $0 | 0 | 0 |
| IWM | 3 | $167 | 3.5 | 0 | $0 | 0.0% | 0 | $0 | 0 | 0 |
| IWM | 3 | $167 | 5.0 | 0 | $0 | 0.0% | 0 | $0 | 0 | 0 |

Totals at 1.5 across the five symbols: **14 of 45 entries blocked, $1,190 of $3,484
premium (34.2%), 14 winners and 0 losers.** At 2.5: 5 entries, $377. At 3.5: 1 entry, $55.
At 5.0: nothing.

Every one of those 14 cycles won because **no cycle in the entire replay lost** — worst
cycle is positive on all five symbols at every arm. A gap gate is insurance, and this
window contained no fire.

**Treat this section as a sanity check on Layer 3, not as evidence in its own right.** It
is 45 simulated entries against the real book's 330, on a strategy whose replay barely
trades. It agrees with Layer 3 in direction and rough magnitude (34% of premium here, 33%
there), which is the only thing it was ever good for. The money answer is
[Layer 3](#layer-3--the-real-fills-join-run--this-is-the-decisive-layer).

---

## Layer 3 — the real-fills join (RUN — this is the decisive layer)

The plan's highest-value question: *dollars of actually-taken trades a working gate would
have prevented, and whether they won or lost.* Source is BigQuery
`options_wheel.trades_from_activities`, read-only, joined in Python against the layer-1 gap
table and the intraday reconstruction.

**Schema reality check.** The plan's sketch query does not run against this table. Verified
column names and semantics, all differing from the plan:

| plan assumed | actually |
|---|---|
| `underlying_symbol` | `underlying` |
| `side = 'sell_to_open'` | `side = 'sell_short'` (close is `'buy'`) |
| `net_amount` carries the money | `net_amount` is **NULL on every FILL row**; `premium_total` is the populated column. `net_amount` *is* set on `OPTRD`, the stock leg of an assignment |
| `DATE(transaction_time)` | fine, but `activity_date` is NULL on FILLs, so it must be `transaction_time` — and it is UTC, so ET dates need `AT TIME ZONE 'America/New_York'` or a fill at 20:05 UTC lands on the wrong day |
| window "2024-02 → present" | **the live account's first fill is 2025-10-06.** There is no 2024 or H1-2025 live history to join against |

**The book, 2025-10-06 → 2026-07-28:** 330 sell-to-open fills (246 puts, 84 calls) across 8
symbols, **$68,518 premium collected**, **$34,860 realized option P&L** (premium net of
buybacks), 29 assignments (16 puts assigned to shares, 13 calls called away). Net realized,
counting the put-assignment marks below: **$20,599**. 308 winners, 22 losers.

### What a working gate would have prevented

Book: **330 sell-to-open fills, 2025-10-06 .. 2026-07-28**, $68,518 premium, $34,860 realized option P&L, 29 assignments (assignment-day mark $-14,261), net realized **$20,599**.

| measure | thr | entries blocked | premium blocked | % of premium | option P&L forgone | assignment mark avoided | **net P&L blocked** | W/L | assignments blocked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| overnight gap | 1.5 | 79 | $18,296 | 26.7% | $10,845 | $-5,761 | **$+5,084** | 74/5 | 8 |
| overnight gap | 2.5 | 22 | $5,726 | 8.4% | $4,250 | $-2,310 | **$+1,940** | 19/3 | 5 |
| overnight gap | 3.5 | 10 | $3,458 | 5.0% | $2,422 | $-550 | **$+1,872** | 9/1 | 2 |
| overnight gap | 5.0 | 4 | $1,587 | 2.3% | $1,485 | $-550 | **$+935** | 3/1 | 2 |
| fixed gate @ 09:35 | 1.5 | 96 | $22,621 | 33.0% | $10,381 | $-5,360 | **$+5,021** | 86/10 | 10 |
| fixed gate @ 09:35 | 2.5 | 39 | $9,502 | 13.9% | $6,601 | $-2,310 | **$+4,291** | 36/3 | 5 |
| fixed gate @ 09:35 | 3.5 | 11 | $3,872 | 5.7% | $2,781 | $0 | **$+2,781** | 11/0 | 1 |
| fixed gate @ 09:35 | 5.0 | 6 | $2,533 | 3.7% | $1,900 | $0 | **$+1,900** | 6/0 | 1 |
| all 3 scans block | 1.5 | 65 | $15,553 | 22.7% | $8,001 | $-2,490 | **$+5,511** | 59/6 | 5 |
| all 3 scans block | 2.5 | 27 | $6,755 | 9.9% | $4,494 | $0 | **$+4,494** | 27/0 | 1 |
| all 3 scans block | 3.5 | 6 | $2,911 | 4.2% | $2,029 | $0 | **$+2,029** | 6/0 | 1 |
| all 3 scans block | 5.0 | 5 | $2,361 | 3.5% | $1,765 | $0 | **$+1,765** | 5/0 | 1 |

### Per symbol, at the plan's 1.5, on the live 09:35 measure

| symbol | entries | premium | net realized | blocked | premium blocked | option P&L forgone | assignment mark avoided | **net P&L blocked** | W/L |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AAPL | 11 | $1,469 | $-622 | 3 | $406 | $259 | $-1,387 | **$-1,128** | 2/1 |
| AMD | 55 | $15,888 | $3,927 | 26 | $8,744 | $5,225 | $-1,760 | **$+3,465** | 24/2 |
| AMZN | 44 | $13,306 | $4,237 | 10 | $3,982 | $1,167 | $0 | **$+1,167** | 8/2 |
| GOOGL | 46 | $10,848 | $5,182 | 8 | $1,957 | $1,356 | $-147 | **$+1,209** | 8/0 |
| IWM | 35 | $4,876 | $1,526 | 3 | $1,106 | $-135 | $0 | **$-135** | 2/1 |
| MSFT | 7 | $1,423 | $-450 | 2 | $317 | $268 | $-1,516 | **$-1,248** | 1/1 |
| NVDA | 101 | $14,017 | $4,385 | 41 | $5,692 | $2,038 | $-550 | **$+1,488** | 38/3 |
| UNH | 31 | $6,691 | $2,414 | 3 | $417 | $203 | $0 | **$+203** | 3/0 |

### How outcome is computed, and what it does not include

- **`option P&L forgone`** is exact and fully sourced from BQ: for each contract,
  premium in minus buybacks out, attributed pro-rata across that contract's entries.
- **`assignment mark avoided`** is the plan's stated fallback attribution: for a **put**
  that was assigned, `(close on the expiry date − strike) × 100 × qty`, from Alpaca daily
  bars. It is the mark taken **at** assignment, not full cycle P&L — it ignores the covered
  calls subsequently written against those shares and any later stock recovery. It is
  therefore **conservative**: it makes assigned trades look worse than the wheel eventually
  made them, which biases this table *in favour of* the gate.
- **Not modelled:** the stock-disposition P&L of the 13 **call** assignments (shares called
  away). Stage 4 gates calls as well as puts — 24 of the 96 entries blocked at 1.5 are call
  writes — so the gate's effect on the call side is captured only through the option leg.
- 3 of the 330 entries fall after the layer-1 window's 2026-07-24 end and are excluded from
  every blocking test (327 evaluable), which the JSON records as `evaluable_entries`.

### The finding

**At 1.5, on the measure the fixed gate actually computes at 09:35, a working gate would
have blocked 96 of 327 entries (29%), forgone $22,621 of premium (33% of the book), and
cost the account $5,021 net — 7.3% of window premium income and 24% of everything the
strategy realized in ten months.** 86 of those 96 trades were winners.

It is not a clean story, and the honest version has two parts:

1. **The gate does find real risk at 1.5.** It blocks 10 of the 29 assignments (34%) while
   blocking 29% of entries, avoiding $5,360 of the book's $14,261 in put-assignment marks
   (38%). That is better than proportional. **It just does not pay for itself** — the
   $10,381 of option income it forfeits is roughly twice the loss it avoids.
2. **At 3.5 and 5.0 it buys literally nothing.** Zero put assignments avoided, zero losing
   trades blocked — **every single blocked entry was a winner** (11/0 and 6/0). Those arms
   are pure income loss of $2,781 and $1,900. The engine A/B suggested 5.0 was "free";
   against real fills it is not free, it is a $1,900 donation that prevented nothing.

**Per-symbol, the sign of the effect is backwards from the intent.** The gate costs money
on every symbol where the bot trades often — AMD −$3,465 over 55 entries, NVDA −$1,488 over
101, GOOGL −$1,209, AMZN −$1,167 — and helps only on AAPL (+$1,128) and MSFT (+$1,248),
which have 11 and 7 entries respectively and one unlucky assignment each. The benefit sits
entirely in the small-sample names; the cost sits where the evidence is.

---

## Pre-registered decision rules, applied

### (a) "Blocked real trades were net profitable by >5% of window premium income, with no offsetting tail-loss reduction"

**FIRES at 1.5 and 2.5, on real money. Does not fire on magnitude at 3.5/5.0 — but those
thresholds fail the rule's spirit even harder.**

The rule has two clauses. Against 330 real fills:

| threshold | net P&L of blocked trades | as % of $68,518 window premium | >5% bar? | offsetting tail-loss reduction? |
|---:|---:|---:|---|---|
| 1.5 | +$5,021 | **7.3%** | **fires** | partial — 10 of 29 assignments and 10 of 22 losing trades avoided, worth $5,360 against $10,381 of income given up |
| 2.5 | +$4,291 | **6.3%** | **fires** | partial — 5 assignments, $2,310 avoided against $6,601 given up |
| 3.5 | +$2,781 | 4.1% | below bar | **none — 0 assignments, 0 losing trades, 11 of 11 blocked trades were winners** |
| 5.0 | +$1,900 | 2.8% | below bar | **none — 0 assignments, 0 losing trades, 6 of 6 blocked trades were winners** |

Read honestly, that table says something slightly different from a clean rule-fire, and the
difference matters:

- At **1.5 and 2.5** the gate is doing real risk work — it catches assignments at a better
  than proportional rate — and still loses money, because the premium it forfeits is about
  twice the loss it avoids. The rule fires on magnitude; the "no offsetting reduction"
  qualifier is only partly true.
- At **3.5 and 5.0** the magnitude falls below the 5% bar, so the rule as literally written
  does not fire. But the qualifier is satisfied *perfectly*: these thresholds avoided
  **zero** assignments and **zero** losing trades across ten months. They are cost with no
  benefit whatsoever. A rule that reads "safe" here is a rule that needs rewording, not a
  green light — flagged in [What the plan got wrong](#what-the-plan-got-wrong).

**This supersedes the simulated-fill estimate.** The engine-attribution table earlier in
this document put the 1.5 cost at 36% of replay premium on four symbols; the real book puts
it at 33% of premium and $5,021 of realized P&L across all eight. The two agree in
direction and rough magnitude, which is the only thing the simulated version was ever good
for.

### (b) "Return-on-collateral monotonically improving as the threshold rises, with no drawdown/worst-cycle improvement at tighter thresholds"

**FIRES.** Return-on-collateral by arm:

| symbol | 1.5 | 2.5 | 3.5 | 5.0 | 999 (unarmed) | monotone? | any risk metric better when tighter? |
|---|---:|---:|---:|---:|---:|---|---|
| NVDA | 19.31% | 19.98% | 32.92% | 33.64% | 33.64% | yes | no — max DD −4.05% at 1.5 vs −3.97% unarmed |
| AMD | 204.88% | 204.88% | 204.88% | 210.41% | 210.41% | yes | no — max DD identical −9.44% at every arm |
| IWM | 50.40% | 50.97% | 51.49% | 51.49% | 51.49% | yes | no — max DD −6.34% vs −6.35%, i.e. within rounding |
| AAPL | 75.50% | 75.52% | 75.52% | 75.52% | 75.52% | flat | no |
| GOOGL | 126.83% | 126.83% | 126.83% | 126.83% | 126.83% | flat | no |

**Return-on-collateral is non-decreasing in the threshold on all five symbols** and strictly
increasing on the three with enough trades to move. No arm improves max drawdown or worst
cycle at a tighter threshold anywhere. That is exactly the pattern the plan pre-registered
as "the gate adds nothing at any sweep level".

One honest wrinkle, because it cuts the other way and a reviewer would find it: **on IWM,
raw total return is *not* monotone** — 10.04% at 1.5 and 10.11% at 2.5 against 9.91%
unarmed, because blocking three early entries freed collateral that later financed eight or
nine. Return-on-collateral, the metric rule (b) is actually phrased on, stays monotone
(50.40% → 51.49%) precisely because it normalises for that. This is path divergence, not a
benefit of the gate, and it is a reminder that raw return across arms is not a like-for-like
comparison once the paths separate.

### (c) "The 9:35-measure block rate at 1.5 exceeds ~25-30% of decision days on NVDA/AMD"

**FIRES on every framing, and on more symbols than the rule names.**

| framing | NVDA | AMD | GOOGL | AMZN |
|---|---:|---:|---:|---:|
| 09:35 reconstruction (the gate's actual live measure) | **37.64%** | **41.61%** | 17.42% | — |
| daily open vs prior close | **32.31%** | **37.10%** | 14.19% | 15.81% |
| at least one of three scans blocks | 69.63% | 71.77% | 41.61% | — |
| **all three scans block (day fully lost)** | **25.53%** | **29.52%** | 10.81% | — |

Even the most forgiving framing — a day is only lost when all three daily scans exceed the
threshold — puts NVDA at 25.5% and AMD at 29.5%, inside the rule's own band. On the measure
the gate actually computes at 09:35, both are near or above 40%. This is a symbol embargo
by another name, layered on top of a stage-2 filter that already embargoes NVDA on 57% of
decision days and AMD on 87%.

### Disposition

The plan's rules are written for exactly this outcome.

- Under **(a)/(b)**: *"merge the code fix anyway — a gate that lies about what it measures
  is not a control — but Phase B arms at a higher swept threshold or holds at 999 pending a
  joint FC-002 decision; surfaced to owner with the numbers."*
- Under **(c)**: *"recommend the lowest swept threshold with a block rate under ~10-15%."*
  On the 09:35 measure that is **3.5** (NVDA 5.49%, AMD 13.39%); on the all-three-scans
  measure 2.5 would also qualify (8.56% / 17.42% — AMD over).

**Where this study lands.** Rule (c) in isolation picks 3.5. The engine arms, read alone,
would have picked 5.0 — it is the only swept threshold whose replay result is identical to
unarmed on every symbol. **The real-fills join overrules both.**

| threshold | real net cost | assignments avoided | losing trades blocked | verdict |
|---:|---:|---:|---:|---|
| 1.5 | −$5,021 | 10 of 29 | 10 of 22 | real risk work, ~2× too expensive for what it buys |
| 2.5 | −$4,291 | 5 of 29 | 3 of 22 | same shape, still net-negative |
| 3.5 | −$2,781 | **0** | **0** | blocked 11 trades, all winners — pure cost |
| 5.0 | −$1,900 | **0** | **0** | blocked 6 trades, all winners — pure cost |

The engine A/B called 5.0 "free" because in replay it blocked 3 NVDA days on which nothing
would have traded anyway. Against the real book it blocks six entries that all made money.
**There is no swept threshold this data supports arming.**

**The recommendation is therefore: merge the fix, hold at 999.** That is the plan's own
disposition under (a)/(b) — *"merge the code fix anyway ... but Phase B arms at a higher
swept threshold or holds at 999 pending a joint FC-002 decision"* — and the evidence points
at the "holds at 999" branch rather than the "higher threshold" branch, because the higher
thresholds buy nothing at all.

**What would change this answer, honestly stated.** Three things, none of which this study
can supply:

1. **A different regime.** Ten months of real fills and 2.5 years of price history, all
   post-2023. A gap gate earns its keep in the tail; this window's worst blocked trade was
   −$1,352. Arming as explicit insurance against a 2018/2020-style event is a risk-appetite
   decision, and 5.0 prices it at roughly $1,900 per ten months.
2. **A loosened stage 2.** Every rate here is conditional on stage 2 removing 57–87% of
   decision days on the high-gap names. FC-002/B1 should re-run this study, not inherit it.
3. **A longer live book.** 330 fills, 29 assignments, 22 losing trades. The per-symbol
   split already shows the benefit sitting entirely in AAPL (11 entries) and MSFT (7) while
   the cost sits in AMD (55) and NVDA (101) — a sample-size pattern, not a signal.

**What must still happen before any Phase B, regardless of threshold:** the 5-day shadow
observation, so the live `gap_percent` distribution can be checked against this study's
09:35 prediction — NVDA ~38% of sessions above 1.5, ~5.5% above 3.5, ~2% above 5.0; AMD
~42% / ~13% / ~6%. If the shadow week disagrees materially with those, the reconstruction
is wrong and this study's conclusions need revisiting before anything is armed.

---

## Bias footer

1. **Single volatility regime.** 2024-02 → 2026-07 only. No 2018-style vol shock, no
   2020-style crash, no sustained bear market. A gap gate's value concentrates in exactly
   the regimes this window lacks. The study can show the gate *cost* money in a benign
   regime; it cannot show it would be worthless in a bad one.
2. **The replay measures close-to-close, not the 09:35 gap.** Quantified in
   Misclassification 1. Layer-2 stage-4 counts run ~2× what live would produce, so the arms
   **overstate the gate's damage**. The attribution table corrects for this by switching to
   the live measure; the arms do not.
3. **One decision per day in replay vs three scans live.** A live 09:35 block can pass at
   12:00 or 15:00. The scan-coverage table bounds this. Also biased against the gate.
4. **Replay premium is understated ~20%** (median sim/live 0.797,
   [fc-032-parity-check.md](fc-032-parity-check.md)). Arm P&L and attribution dollars
   inherit it. It is roughly proportional across arms, so *differences* between arms are
   more reliable than levels.
5. **NVDA's engine window starts 2024-08-15**, not 2024-02-01, to keep the 10:1 split out
   of both the decision window and the 60-day warm-up. NVDA's arms cover ~2.0 years where
   others cover ~2.5.
6. **The broken-gate reconstruction uses consolidated 5-minute trade prints**, not IEX
   quote midpoints against a SIP-derived partial bar. Production compared across two feeds,
   which adds noise the reconstruction does not have — so the reconstruction, if anything,
   **understates** the broken gate's spurious-fire rate. On half-days the 15:00 leg falls
   back to the last available print; that affects ~5 sessions a year and mirrors what live
   would have seen anyway.
7. **Two different windows, and the decisive one is the shorter.** Layers 1 and 2 cover
   2024-02 → 2026-07 (620 sessions). **Layer 3 covers only 2025-10-06 → 2026-07-28**,
   because that is when the live account's first fill is — there is no earlier live
   history to join against, contrary to the plan's "2024-02→present". So the money answer
   rests on ten months and 330 trades, not two and a half years. It is still the best
   evidence available and it is real money, but it is one regime and one sample.
8. **Layer 3's outcome model is conservative on puts and incomplete on calls.** Assigned
   puts are marked at `(expiry close − strike)`, ignoring the covered calls later written
   against those shares — which makes assigned trades look worse than they ended up, and
   therefore flatters the gate. The stock-disposition P&L of the 13 call assignments is not
   modelled at all; 24 of the 96 entries blocked at 1.5 are call writes, so the call side is
   captured through its option leg only.
9. **Stage 2 sits upstream of all of this.** It already excludes NVDA on 278 of 486
   decision days. "Per decision day" and "per day that reaches stage 4" are very different
   denominators; both are given where it matters. **If FC-002/B1 loosens stage 2, every
   stage-4 rate in this study rises**, because more days reach stage 4 — reviewers must
   assess the pair, per the plan.
10. **Coverage by layer.** Layer 1: all 14 configured symbols. Intraday reconstruction: all
    9 symbols that have ever traded live. Layer 3: all 8 symbols with real fills. **Layer 2
    covers five — NVDA, AMD, AAPL, GOOGL, IWM.** SPY was not completed: its chain build
    runs several times slower than a single-name equity (98 of 620 sessions in ~35 minutes
    against Alpaca's 200 req/min cap). That is a coverage gap, not a finding — SPY's rates
    are the lowest in the universe (2.74% at 09:35 against 1.5, and it never once tripped
    the broken gate in 620 sessions), so a completed A/B would show *less* gate effect than
    the five run here, not more. Anyone re-running should start SPY first and alone. AMZN,
    UNH and MSFT have no Layer-2 arms either, but all three appear in Layers 1 and 3.

---

## What the plan got wrong

Five items, in descending order of consequence.

**1. "Spurious-fire rate of the current broken gate: not historically reconstructible."**
It is reconstructible, and it was the single most informative measurement in this study.
Alpaca serves historical intraday bars — including pre-market — on the entitlement this
project already holds; every timestamp the study needs falls on a 5-minute boundary, so
5-minute bars suffice. The plan's proposed substitute was a 10-trial live sample plus the
shadow week. This study reconstructed **3,719 symbol-days**. The 10-trial sample's
conclusion ("0/10 would have spuriously fired at 1.5") is not wrong, it is under-powered:
at NVDA's true 5.01% rate, 10 draws miss it 60% of the time. A study that bounded the
broken gate's behaviour that way would have shipped a decision on a coin flip.

**2. The NVDA engine window start of 2024-07-01 is wrong. Verified, not asserted.**
The plan is right that the simulator survives a split in the warm-up buffer, but survival
is not correctness — the simulator's own log says so. Running NVDA from 2024-07-01 emits:

```
[warning] Split inside the warm-up window, not the decision window: gap statistics over
the first sessions read a corporate action as a price move and will be distorted.
event_type=split_in_warmup ratio=0.1007 split_date=2024-06-10 symbol=NVDA
```

Comparing the two windows at threshold 999, holding everything else equal:

| start | decision days | stage-2 blocked | puts sold | return |
|---|---:|---:|---:|---:|
| 2024-07-01 (plan) | 518 | 310 (59.8%) | 30 | 5.458% |
| 2024-08-15 (used here) | 486 | 278 (57.2%) | 30 | 5.458% |

The plan's extra 32 decision days are **32 for 32 stage-2 blocked**. They contribute zero
stage-4 observations — the thing the study exists to measure — while inflating stage 2's
apparent block rate by 2.6 points. 2024-08-15 puts the 60-calendar-day warm-up start at
2024-06-16, clear of the 2024-06-10 split.

**3. The plan's Layer-1 measure list omits the one measure the gate actually used.**
It specifies the overnight gap and close-to-close and calls the matrix between *those two*
"the honesty instrument". Both are *correct-gate* measures; their matrix quantifies replay
bias, which matters, but says nothing about what production did for the life of the
project. The broken-vs-fixed matrix is what answers "was the old gate firing on noise, and
did it ever fire on signal" — and the answer (185 blocks, 12% of them on days with no real
gap, 79–100% of real gap days missed) is the strongest argument in the fix PR.

**4. The engine A/B cannot carry the weight the plan puts on it, and the plan should have
seen that coming.** At current stage-2 settings the replayed strategy makes **1 to 30
entries per symbol over 2.5 years**. On four of the five symbols run, every arm is
near-identical because there was nothing left to block. The plan specifies eight symbols for
the baseline/1.5 arms and a four-symbol sweep without pre-registering a minimum-entries
criterion for an arm to count as evidence. It should have: "arms with fewer than N entries
are uninformative and must not be reported as showing the gate is harmless." Layer 1 —
which the plan treats as context for Layer 2 — turned out to be the load-bearing layer.

**5. The Layer-3 query in the plan does not run, and its window does not exist.** Four of
the five column references are wrong for the live table (`underlying_symbol`, `side =
'sell_to_open'`, `net_amount` as the money column, and `DATE(transaction_time)` without a
timezone — `net_amount` is NULL on every FILL row and `activity_date` is NULL too, so a
naive query returns either nothing or silently mis-dated rows). More consequentially, the
plan specifies the join over "2024-02→present": **the live account's first fill is
2025-10-06.** Two-thirds of the stated window has no live data in it. A plan that is a
handoff contract should have had its one BigQuery query checked against
`INFORMATION_SCHEMA` before publication — it is a thirty-second check that would have
changed the study's scope statement.

**6. Rule (a)'s wording lets the worst thresholds pass.** The rule fires when blocked trades
are "net profitable by >5% of window premium income, **with no offsetting tail-loss
reduction**". Against real fills, 1.5 and 2.5 clear the 5% magnitude bar but *do* have
partial tail reduction; 3.5 and 5.0 have **zero** tail reduction — they block only winners
— but fall under 5% purely because they block so few trades. So the literal rule fires
where the gate is doing some real work and stays silent where it is doing none at all. The
magnitude test should be relative to what the threshold blocks (net P&L per blocked trade,
or benefit-to-cost), not to total window premium.

**7. Rule (c)'s "~25-30% on NVDA/AMD" is a two-symbol carve-out set roughly at the answer.**
NVDA (32.31%) and AMD (37.10%) clear it on the open-based measure, but GOOGL (14.19%) and
AMZN (15.81%) sit just under — so a rule phrased as "NVDA/AMD only" would licence arming a
threshold that also blocks ~1 session in 7 on two more symbols, and ~1 in 4 on the
at-least-one-scan measure. It should be a universe-wide rate.

**What the plan got exactly right,** and it is worth saying because it is what makes a
negative result cheap to act on: **the phased 999-shadow rollout.** The equivalence check
proves Phase A is a no-op to replayed behaviour, so the correctness fix merges on its own
merits and the arming decision stays open, one config line away, informed by this study and
by a shadow week that has not happened yet. Also right: D3's warning that the replay
measures close-to-close and that the matrix would be needed to read Layer 2 honestly — the
replay over-blocks by ~2×, exactly as predicted.

---

## Reproducing this document

Raw JSON outputs (`layer1.json`, `layer1_rows.json`, `intraday.json`, `intraday_rows.json`,
`layer2_<SYM>.json`, `equivalence_NVDA.json`, `attribution.json`, `fc_entry_check.json`,
`layer3.json`, `layer3_entries.json`) are **not committed** — they are frozen data
snapshots per the repo's diagnostic-artifact policy, and `layer3_entries.json` contains
per-trade account detail. Regenerate with the commands in [Method](#method); the harness is
the artifact with reuse value.

Layer 3 needs `gcloud auth login` and reads BigQuery through the `bq` CLI (the credential
that exists is a user login, not application-default, which is what the CLI authorises).
**It is strictly read-only and never writes to `options_wheel`.** If auth is missing the
subcommand degrades to printing the query rather than approximating an answer.

Cost note for re-runs: layer 2 is ~10 minutes per symbol against an empty
`cache/backtest/chains/` (gitignored), then seconds per additional arm. SPY and IWM build
several times slower than single-name equities because their chains are far larger. The
harness installs 429 backoff on the provider's data endpoints — Alpaca's Basic plan caps at
200 req/min and two study processes in parallel will trip it.
