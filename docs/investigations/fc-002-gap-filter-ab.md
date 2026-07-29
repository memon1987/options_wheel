# FC-002 / FC-042 B1 — the stage-2 gap-risk filter, A/B'd

**Date:** 2026-07-29
**Plan:** [docs/plans/fc-042.md](../plans/fc-042.md) Track B1
**FC entry:** FC-002 in [docs/FUTURE_CONSIDERATIONS.md](../FUTURE_CONSIDERATIONS.md)
**Harness:** [`tools/diagnostics/fc002_gap_filter_ab.py`](../../tools/diagnostics/fc002_gap_filter_ab.py)
**Scope:** **stage 2 only** — `GapDetector.analyze_gap_risk` / `_is_suitable_for_trading`
(gap frequency + realized-vol cap). Stage 4, the execution gap gate, is a different
control, was studied separately in [fc-036-gap-gate-study.md](fc-036-gap-gate-study.md),
and is not re-examined here.

**This document is evidence, not a change.** No live threshold moves on this study. Any
change to `gap_risk_controls` gates on FC-002's own plan plus two adversarial reviews.

> ### ⚠️ Read this before Layer 2: the engine arms are put-only
>
> **FC-049** (`c37f777` on main, filed independently while this study was running):
> `ExecutionEngine.execute_batch` routes on `opp.get('type', 'put')`
> (`src/strategy/execution_engine.py:286`). The live `/scan` path sets `'type': 'call'`
> (`options_scanner.py:340`); the path the **backtest replays** —
> `call_seller.evaluate_covered_call_opportunity` via `wheel_engine.run_strategy_cycle()` —
> sets `'strategy': 'sell_call'` and no `'type'` key at all. Every covered-call opportunity
> in replay is therefore handed to `put_seller` and rejected. Verified here independently by
> code trace and by this study's own output: **`calls_sold = 0` and realized `stock_pnl = $0`
> in all 36 arms across all four symbols.** Production is unaffected (84 real calls in
> `trades_from_activities`).
>
> **What it invalidates:** [Layer 2](#layer-2--the-engine-ab) only. Its returns, RoC, max
> drawdown, worst cycle and days-in-position are measured with no call premium and with no
> cycle ever completing — once assigned, shares are held to the end of the window.
>
> **What it does not touch:** [Finding 0](#finding-0--the-filter-is-not-in-the-live-path)
> (source, git history, production logs, one BigQuery fill), [Layer 1](#layer-1--what-the-filter-does-and-which-leg-does-it)
> (daily bars, no engine), [Layer 3](#layer-3--the-real-fills) (real fills) and the
> [Overlay](#overlay--2329-synthetic-entries-because-the-engines-sample-is-too-small)
> (daily bars, no engine). **Those four carry the conclusion.**
>
> **Direction of the bias — measured, not assumed, and it is the opposite of the intuitive
> guess.** The intuitive reading is that looser arms are penalised, because they take more
> assignments and then forfeit the call premium on those shares. In *this* window the
> opposite dominates: shares that are never called away retain their full upside in a strong
> bull market, and that outweighs the forgone call premium several times over. Decomposing
> NVDA's own arms:
>
> | NVDA arm | option P&L | unrealized stock P&L | stock as % of P&L | puts | days in position |
> |---|---:|---:|---:|---:|---:|
> | (a) as-is | $2,498 | $2,934 | 54% | 30 | 236 |
> | (b) off | **$1,709** | **$6,484** | **79%** | 21 | 466 |
>
> **Arm (b)'s option income is *lower* than arm (a)'s — its entire apparent advantage is
> retained stock appreciation from being assigned earlier and holding longer.** The same
> pattern is more extreme elsewhere: AMD's arms are 99.5% unrealized stock ($34,945 against
> $181 of option P&L), GOOGL's 99.7%, IWM's 98.2%. So Layer 2 **flatters the loosening arms**,
> and the engine evidence for loosening is overstated, not understated. That cuts against
> this study's own direction of travel, which is why it is stated here rather than in a
> footnote.
>
> **Does the recommendation flip?** Items 1 and 2 below do not — they rest on Finding 0 and
> on the real-fills/overlay layers. **Item 3 (carry forward arm (e), graduated response) is
> contingent and is flagged as such**: its only support is Layer 2, and 78% of its apparent
> AMD gain is retained stock upside ($34,945 → $37,195 unrealized, against $181 → $688 of
> option P&L) that a working call path would partly have called away. **Arm (e) must be
> re-run after FC-049 is fixed before anyone acts on it.** The harness makes that a
> four-command job.
>
> *(This branch is not rebased onto `c37f777`; the finding is incorporated by reference.)*

---

## Verdict

**Do not re-tune the thresholds. The premise of the FC entry is wrong in a way that makes
threshold tuning the wrong question.**

Two findings, in order of consequence.

**1. The stage-2 gap-risk filter is not wired into the production trading path, and has
never gated a live trade.** It lives in `WheelEngine._find_new_opportunities`. The deployed
Cloud Run path is `/scan` → `OptionsScanner` → opportunity store → `/run`, and
`OptionsScanner` does not construct a `GapDetector`. Commit `842dcce` (2025-10-03) removed
`wheel_engine.run_strategy_cycle()` from `/run`; the account's first fill is **2025-10-06**,
three days later. Every one of the 330 live sell-to-open fills was placed by a path that
never evaluates stage 2. Every block rate FC-002 quotes, and every stage-2 rate in the
FC-036 study, describes the **backtest engine**, not production.

**2. Setting the wiring aside, the filter's premise does not hold in this window — it blocks
the better days, not the worse ones.** This rests on real fills and on a daily-bar overlay,
**neither of which involves the engine**, so neither is touched by FC-049. Against the 330 real fills, the
123 entries the status-quo rule would have refused earned **$8,691** of realized P&L at
**$70.66/entry** against **$55.94/entry** for the 204 it would have allowed. Against 2,329
synthetic daily entries priced from bars and a fill-calibrated IV model, the days it blocks
earned **$122.97/entry** against **$28.04/entry** for the days it allows — a sign that holds
on all four symbols, under both IV models, and under ±20% premium scaling.

| pre-registered rule | fires? | evidence |
|---|---|---|
| **R1** — the premise holds in real money | **partly, on one fragile metric only** | P&L per entry is **higher** in the top vol decile ($77.95 vs $59.50) — the ≥25%-lower clause does not fire. Assignment rate 11.43% vs 8.56% = 1.34× — below the 1.5× bar. The **worst-decile-mean clause does fire** (−$940 vs −$413, 2.3×) — but that statistic is the mean of the **3 worst of 35** trades and is entirely one trade (AMD 2025-11-17, −$2,428). On mean-of-worst-5 it reverses (−$547 vs −$1,200); on loss rate it reverses (5.7% vs 6.8%). See [R1, in full](#r1--does-elevated-vol-predict-bad-outcomes-in-real-money). |
| **R2** — loosening buys return by taking risk | **no — but this rule is now unreliable and is not load-bearing** | NVDA off vs as-is: ROC 33.64% → 66.07%, max DD −3.97% → −5.17%; worst cycle flat (+$50.27 → +$49.28) and **no arm on any symbol had a losing cycle**. **However, R2 is evaluated purely on Layer 2, which FC-048 makes put-only, and the direction of that bias flatters the loosening arms** (arm (b)'s option income is *lower* than arm (a)'s; its gain is retained stock). Treat R2 as unresolved pending an FC-048 re-run. The verdict does not depend on it: R3 and R4 are measured without the engine. |
| **R3** — the filter is genuinely selective | **no, and it inverts** | Blocked days out-earn allowed days on **4 of 4** symbols, under both IV models and at −20% premium. AMD's allowed days are the only negative bucket in the entire overlay: **−$168.89/entry, 28.6% assignment**. |
| **R4** — the filter is not binding | **no** | It is severely binding *in replay*: NVDA 63.4% of sessions, AMD 94.4%, and 100% of AMD's 201 sessions in the live-fills window. |

**Recommendation.** Three items, in dependency order. None of them is a threshold change.

1. **Decide the intent first — filed as FC-049.** Either the live path
   should run the filter or the filter should be deleted; what it must not stay is a
   control that exists in config, in the backtest, and in the FC index, but not in the
   thing that trades. Deciding *whether* to gate is a strictly larger question than *where*
   to put the line, and it has to be answered first — tuning a number that nothing reads is
   a no-op, and shipping the current number into the live path would be the single largest
   behaviour change in this project's history (it would have refused 123 of 327 entries).
2. **If it is wired in, do not wire in the current rule.** On this window it is
   anti-selective: it would have cost $8,691 of realized P&L, 43% of the book's $20,102 on
   evaluable entries, while cutting per-entry loss drag from $58 to $38. Stated as a
   benefit-to-cost: the blocked set contains **$7,183 of losses and $15,874 of gains**, so
   the filter forfeits **$2.21 of gain for every $1 of loss it avoids**. The
   gap-**frequency** leg is the
   more damaging half (it alone blocks 51.3% of NVDA and 77.6% of AMD sessions and is what
   blocks 100% of AMD's live window), and it is the leg with the least theoretical
   justification: a >2% overnight move on a 40-vol name is a **typical** day, not a tail.
3. **The one arm worth carrying forward is (e), graduated response — contingent, and not
   actionable until FC-049 is fixed.** It is the one arm that improves the engine without
   removing the control (AMD ROC 210.41% → 229.33%, 9 puts instead of 2). But **its only
   support is Layer 2, which is put-only**, and 78% of that AMD gain is retained stock
   upside a working call path would partly have called away. Re-run it after FC-049 before
   acting. Two further limits: its *stated* first option, "half size", **cannot be
   implemented** — `put_seller.py:182` hard-codes `contracts = 1` and there is no half
   contract — so only the delta-band variant was testable; and the graduated response is the
   one arm whose merit the real-fills layer **cannot** adjudicate, because it changes what is
   traded rather than whether, and the book contains no [0.10, 0.15]-delta fills to compare
   against.

**What would change this answer:** a vol regime this window does not contain. 2024-02 →
2026-07 is one long bull market in which realized vol and premium rose together and every
replayed cycle was profitable. A vol filter earns its keep when high vol precedes a crash,
not a melt-up. This study can show the filter cost money in a benign regime; it cannot show
it would be worthless in a bad one.

---

## Pre-registration

*Written and committed in `61c0994`, before any result was produced. Reproduced verbatim.*

The failure mode this section exists to prevent: running eight arms, picking the one with
the best headline return, and calling it evidence. The rules below name in advance what
would argue **against** loosening the filter.

### What would argue AGAINST loosening (keep the filter as-is)

- **R1 — the premise holds in real money.** Among the 330 real sell-to-open fills, entries
  taken when the underlying's trailing realized vol was high show materially worse realized
  economics than entries taken when it was low. "Materially worse" = any of: realized P&L
  per entry at least **25% lower**, assignment rate at least **1.5×** higher, or a worst-decile
  loss at least **2×** larger. If elevated vol really predicts bad outcomes in this book,
  this is where it shows, and the cap is defensible even if expensive.
- **R2 — loosening buys return by taking risk.** In the engine A/B, a loosening arm raises
  return on collateral but degrades risk: max drawdown worsens by more than the ROC
  improvement in relative terms, or worst cycle worsens by more than 50%.
- **R3 — the filter is genuinely selective.** In the daily-bar synthetic short-put overlay
  over 2024-02 → 2026-07 (a far larger sample than the engine's handful of entries), the
  symbol-days the status-quo filter **blocks** show worse expected per-entry P&L than the
  days it allows, with the sign stable under ±20% scaling of the modeled premium.
- **R4 — the filter is not actually binding.** Loosening changes the block rate by less
  than 5 percentage points on NVDA/AMD. Then the change buys nothing and is pure
  over-fitting risk.

### What would argue FOR loosening

All three, jointly:

1. The filter's block decisions show **no discriminating power** on real outcomes (R1 fails).
2. Blocked days are **no worse** than allowed days in the overlay (R3 fails).
3. Blocked days are **numerous** — a large opportunity cost, not a rounding error.

### Arm-selection rules, also pre-registered

- No recommendation of a specific threshold that works on **one** symbol. A proposal must
  hold its sign on at least 3 of the 4 study symbols, or it is over-fit to NVDA.
- Prefer the **simplest** arm that captures most of the available benefit. A vol-relative
  percentile gate that beats a fixed cap by a hair is not worth the extra machinery.
- A **negative / no-change-warranted** result is a valid and valuable outcome. FC-036's
  most useful output was its AGAINST verdict.
- The **real-fills layer overrules the engine A/B** wherever they disagree. FC-036 proved
  the engine alone can call a threshold "free" that real fills price at $1,900.

### One criterion adopted after the fact, and labelled as such

FC-036's published "what the plan got wrong" §4 recommends that a study pre-register a
**minimum-entries criterion** for an engine arm to count as evidence. That was not in this
study's own pre-registration; it is adopted here at **10 entries**, taken from FC-036's
recommendation rather than tuned to these results. Under it, **only NVDA's engine arms are
evidence** — AMD (2–9 puts), GOOGL (1) and IWM (3–8) are not. That is why the overlay
exists.

---

## Finding 0 — the filter is not in the live path

Everything below this section is a question about the backtest engine unless and until the
wiring changes. This is not an inference from log volume; it is four independent checks,
three of which are executed by `fc002_gap_filter_ab.py verify`.

**(a) Source. The live scan path cannot reach the filter.** `verify` imports each module
and inspects its source:

| module | references `GapDetector` | calls `filter_stocks_by_gap_risk` |
|---|---|---|
| `src/data/options_scanner.py` — **the live `/scan` path** | no | no |
| `src/api/market_data.py` | no | no |
| `src/strategy/put_seller.py` | no | no |
| `src/strategy/call_seller.py` | no | no |
| `src/strategy/wheel_engine.py` | **yes** | **yes** |
| `deploy/cloud_run_server.py` | no | no |

The only `WheelEngine` method that reaches stage 2 is `_find_new_opportunities`. The server
constructs a `WheelEngine` twice, but calls only `reconcile_positions()` (pre-trade
housekeeping on `/run`) and `run_rolling_cycle()` (`/roll`) — neither enters
`_find_new_opportunities`. `run_strategy_cycle(` does not appear in the server at all.

**(b) History. The removal is dated, and it predates the book.** `git log -S
"run_strategy_cycle" -- deploy/cloud_run_server.py` returns `842dcce` (2025-10-03,
"Implement Cloud Storage scan-to-execution architecture"), whose diff deletes
`wheel_engine.run_strategy_cycle()` from `/run`. The account's first fill is **2025-10-06**.
There is no live history in which the filter could have gated an entry.

**(c) Production logs. Every stage-2 event in production comes from a backtest.** Over
Cloud Logging's 40-day retention, 18 distinct `request_id`s emit `stage_2_complete` /
`stock_passed_gap_filter` / `stock_filtered_by_gap_risk`. Each one also emits
`quick_backtest_started` or `comprehensive_backtest_started` and `backtest_completed`.
**Zero** come from a request that emitted `market_scan_triggered` or executed a trade.

**(d) A single day settles it.** `docs/analysis/AMD_GAP_RISK_ANALYSIS_2025.md`, dated
2025-10-06, records the filter's own output for AMD that day: gap frequency 23.53%,
historical volatility 85.49%, "**Suitable for Trading: ❌ NO**", under the headline "AMD IS
CORRECTLY FILTERED BY GAP RISK MANAGEMENT". BigQuery, same day:

```
symbol                  d           side        qty  price  premium_total  strike
AMD251010P00192500      2025-10-06  sell_short  1.0  2.23   223.0          192.5
```

The bot sold the put on the day the filter said no.

**Consequence for the rest of this study.** It is *because* the filter never ran that the
real-fills layer can measure it at all: every real entry is observable under both verdicts,
so "what would it have blocked, and what did those trades earn" is a direct measurement
rather than a counterfactual. In FC-036 the equivalent question required simulation. Here
it does not.

---

## Method and fidelity

### What the filter actually computes — two corrections to the FC entry

Both verified by `layer1 --selfcheck`, which asserts each mirrored constant against `Config`
and inspects `gap_detector`'s source:

- **`vol_lookback_days: 252` is dead config.** Nothing reads `Config.vol_lookback_days`;
  `--selfcheck` fails the run if `gap_detector` ever starts to. The vol is
  `df['close'].pct_change().std() * sqrt(252)` over whatever frame `analyze_gap_risk`
  fetched, which is `gap_lookback_days + 20` = **50 calendar days ≈ 34 sessions**. The cap
  is on a ~7-week realized vol, not a 1-year one.
- **The gap-frequency ratio shares that same 34-session frame** — the two legs are not
  computed over different windows despite the config implying they are.

### Fidelity of the reconstruction

Layer 1 reimplements the filter's arithmetic so that arms can be swept without running the
engine 2,300 times. Three independent checks that it is faithful:

1. **Against the real class.** `verify` drives the actual
   `GapDetector.analyze_gap_risk` over historical bars through a frame-serving client, on
   seven symbol-days the live book traded. **6 of 7 verdicts agree.**

   | symbol | date | live code: suitable | live vol | live freq | recon vol | recon freq | recon blocks |
   |---|---|---|---:|---:|---:|---:|---|
   | AMD | 2025-10-06 | False | 0.7384 | 0.2353 | 0.7283 | 0.2286 | yes |
   | AMD | 2025-12-01 | False | 0.6594 | 0.3529 | 0.6498 | 0.3714 | yes |
   | AMD | 2026-01-20 | False | 0.3949 | 0.2188 | 0.3939 | 0.2121 | yes |
   | AMD | 2026-04-20 | False | 0.5279 | 0.2941 | 0.5223 | 0.3143 | yes |
   | AMD | 2026-05-01 | False | 0.6119 | 0.2941 | 0.6129 | 0.2857 | yes |
   | NVDA | 2026-06-02 | **True** | 0.3997 | 0.1176 | 0.4042 | 0.1143 | **yes — disagrees** |
   | GOOGL | 2026-02-04 | True | 0.1812 | 0.0625 | 0.2039 | 0.0606 | no |

   **The one disagreement is the study's own thesis in miniature.** NVDA on 2026-06-02 has
   a live-code vol of 0.3997 and a reconstructed 0.4042 — a gap of 0.45 vol points either
   side of a hard 0.40 line. The two differ because the live code's frame contains one
   fewer session at the edge (`total_days` 34 vs the reconstruction's 34 gaps). Whenever a
   symbol's vol sits on the line, a one-bar difference in the frame flips the verdict. That
   is not a defect of either implementation; it is what a binary cliff at the middle of a
   symbol's distribution does.

2. **Against the engine.** NVDA over the identical window (2024-08-15 → 2026-07-24, 486
   decision days): the engine reports **278** stage-2 blocked days, the reconstruction
   **273** — 98.97% agreement. GOOGL: engine 108, reconstruction 104. The residual is
   structural, not error: the engine only reaches stage 2 on days it can open a new
   position (`_can_open_new_positions`), so days spent holding a position never reach the
   filter and are never counted. That is also why the engine reports 539 blocked days for
   AMD where the reconstruction, counting every session, reports 586.

3. **Against live production values.** Cloud Logging's `stock_passed_gap_filter` events
   carry the live-computed `volatility`. AAPL: 0.284 / 0.330 / 0.331 on 2026-06-29 /
   07-06 / 07-13, against reconstructed 0.276 / 0.323 / 0.321.

### Corporate actions

NVDA split 10:1 on 2024-06-10 (ratio 0.1007), the only corporate action detected across the
symbols run. Layer 1 drops that single session from the return and gap series so a 90%
"return" cannot poison every window containing it. The engine and the overlay additionally
start NVDA at **2024-08-15** (= 2024-06-16 after the simulator's 60-calendar-day warm-up),
which is what keeps the split out of the warm-up too. The overlay also drops any 7-day
holding window containing a corporate-action date; with the start override in place, 0 such
windows remained.

---

## Layer 1 — what the filter does, and which leg does it

Block rate over 2024-02-01 → 2026-07-24, every session (not only days the engine reaches
stage 2):

| symbol | days | median vol | days vol>40% | (a) as-is | (b) off | (c) cap 40% | (c) cap 50% | (c) cap 60% | (c') vol cap removed | (c') freq cap removed | (d) own p80 | (e) graduated |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| NVDA | 620 | 0.407 | 328 | 63.4% | 0.0% | 63.4% | 55.6% | 51.3% | 51.3% | 52.9% | 56.9% | 63.4% |
| AMD | 621 | 0.491 | 556 | 94.4% | 0.0% | 94.4% | 79.9% | 77.6% | 77.6% | 89.5% | 78.6% | 94.4% |
| GOOGL | 621 | 0.304 | 40 | 16.8% | 0.0% | 16.8% | 14.5% | 14.5% | 14.5% | 7.9% | 32.5% | 16.8% |
| IWM | 621 | 0.198 | 3 | 4.0% | 0.0% | 4.0% | 4.0% | 4.0% | 4.0% | 0.8% | 20.1% | 4.0% |

Arm (e) is identical to (a) here by construction — it changes the *response*, not the
condition. Arm (d) is the only arm that blocks **more** than the status quo on the low-vol
names (GOOGL 32.5% vs 16.8%, IWM 20.1% vs 4.0%): a relative gate necessarily fires 20% of
the time on every symbol, including ones whose absolute vol never approaches any sensible
danger line. That is a design flaw in (d), visible before any P&L is computed.

**Which leg binds.** Attribution inside a single arm is order-dependent (the live code
tests frequency first), so the decomposition arms are the honest measure — each disables
one leg entirely:

| symbol | frequency leg alone | vol leg alone | both (status quo) |
|---|---:|---:|---:|
| NVDA | 51.3% | 52.9% | 63.4% |
| AMD | 77.6% | 89.5% | 94.4% |
| GOOGL | 14.5% | 7.9% | 16.8% |
| IWM | 4.0% | 0.8% | 4.0% |

**On NVDA the two legs bind almost equally over the full window** (51.3% vs 52.9%), which
corrects the FC entry's framing that the vol cap is the constraint. **But the FC entry's
specific claim is confirmed**: over 2026-06-01 → 2026-07-24, NVDA is blocked on **35 of 38
sessions (92.1%), every one of them by the vol cap** (gap frequency passed on all 38), with
vol ranging 0.387–0.459 against a 0.400 line. The entry's "18 of 20 decision days" is the
engine's decision-day denominator; on all sessions it is 35 of 38.

**On AMD the entry's "47% of scans" is badly stale.** Over the same 2024-02 → 2026-07
window AMD is blocked on **94.4%** of sessions, and over the live-fills window
(2025-10-06 → 2026-07-24) on **201 of 201 — 100%, all of them by the gap-frequency leg**.
AMD's median 34-session realized vol in that window is **0.735** and its median gap
frequency **0.343**. The 47% figure comes from an October-2025 snapshot; AMD has since run
from $164 to $522 with a +37.5% overnight gap on 2025-10-06, and both legs have been far
outside their limits ever since.

---

## Layer 2 — the engine A/B

> **Two independent reasons to treat this layer as supporting evidence only.** First,
> **FC-048: these arms are put-only** — `calls_sold = 0` and realized `stock_pnl = $0` in
> every one of the 36 arms below, because replay misroutes covered calls to `put_seller`.
> Cycles never complete; assigned shares are held to the end of the window. The bias
> **flatters the loosening arms** (see the [banner](#-read-this-before-layer-2-the-engine-arms-are-put-only)).
> Second, the minimum-entries criterion. Both were known before the tables were read.

**Read the minimum-entries criterion first: only NVDA is evidence.** GOOGL opens **one** put
in 2.5 years and holds shares for 616 of 621 days; every GOOGL arm is byte-identical, and
that is not the filter being harmless, it is there being nothing left to filter. IWM opens
3–8. AMD opens 2–9. This is the same structural finding FC-036 reported and it has not
changed.

| symbol | arm | return | return on collateral | max DD | worst cycle | puts | assign | days in position | stage-2 blocked | decision days |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| NVDA | (a) as-is | 5.46% | 33.64% | −3.97% | +50.27 | 30 | 1 | 236 | 278 | 486 |
| NVDA | (b) off | 8.22% | **66.07%** | −5.17% | +49.28 | 21 | 1 | 466 | 0 | 486 |
| NVDA | (c) cap 40% | 5.46% | 33.64% | −3.97% | +50.27 | 30 | 1 | 236 | 278 | 486 |
| NVDA | (c) cap 50% | 5.56% | 34.53% | −3.96% | +50.27 | 31 | 1 | 242 | 247 | 486 |
| NVDA | (c) cap 60% | 5.56% | 34.53% | −3.96% | +50.27 | 31 | 1 | 242 | 247 | 486 |
| NVDA | (c') vol cap removed | 5.56% | 34.53% | −3.96% | +50.27 | 31 | 1 | 242 | 247 | 486 |
| NVDA | (c') freq cap removed | 7.38% | 55.52% | −5.22% | +59.15 | 11 | 1 | 423 | 208 | 486 |
| NVDA | (d) own p80 | 5.56% | 34.53% | −3.96% | +50.27 | 31 | 1 | 242 | 270 | 486 |
| NVDA | (e) graduated | 8.05% | 65.17% | −5.18% | +49.25 | 19 | 1 | 462 | 247 | 486 |
| AMD | (a) as-is | 35.13% | 210.41% | −9.44% | +76.88 | 2 | 1 | 514 | 539 | 621 |
| AMD | (b) off | 34.90% | 202.62% | −10.46% | +59.13 | 7 | 1 | 615 | 0 | 621 |
| AMD | (c) cap 50% | 35.13% | 210.41% | −9.44% | +76.88 | 2 | 1 | 514 | 448 | 621 |
| AMD | (c) cap 60% | 35.13% | 210.41% | −9.44% | +76.88 | 2 | 1 | 514 | 435 | 621 |
| AMD | (c') vol cap removed | 35.13% | 210.41% | −9.44% | +76.88 | 2 | 1 | 514 | 435 | 621 |
| AMD | (c') freq cap removed | 35.29% | 218.73% | −9.42% | +52.25 | 4 | 1 | 522 | 498 | 621 |
| AMD | (d) own p80 | 35.13% | 210.41% | −9.44% | +76.88 | 2 | 1 | 514 | 443 | 621 |
| AMD | (e) graduated | 37.88% | **229.33%** | −10.16% | +59.13 | 9 | 1 | 607 | 432 | 621 |
| GOOGL | *all nine arms* | 18.01% | 126.83% | −6.71% | +235.30 | 1 | 1 | 616 | 49–212 | 621 |
| IWM | (a) as-is | 9.91% | 51.49% | −6.35% | +53.25 | 3 | 1 | 619 | 25 | 621 |
| IWM | (b) off | 9.91% | 51.49% | −6.35% | +53.25 | 3 | 1 | 619 | 0 | 621 |
| IWM | (d) own p80 | 10.04% | 50.58% | −6.34% | +50.30 | 8 | 1 | 607 | 127 | 621 |
| IWM | (e) graduated | 9.91% | 51.49% | −6.35% | +53.25 | 3 | 1 | 619 | 22 | 621 |

Full per-arm rows for every symbol are emitted by `markdown`; the rows collapsed above are
identical to their neighbours.

**What the NVDA arms establish.**

- **Turning the filter off nearly doubles return on collateral** — 33.64% → 66.07% — while
  max drawdown worsens from −3.97% to −5.17% and worst cycle is flat (+$50.27 → +$49.28).
  ROC +96% against DD +30%: rule R2 does not fire.
- **The vol cap is nearly free to relax in the engine, and the frequency cap is not.**
  Moving the cap 40 → 50 → 60% changes NVDA's ROC by 0.9 points and stops mattering at 50%.
  Removing the vol cap entirely gives the same 34.53%. Removing the **frequency** cap
  instead gives 55.52% — the frequency leg is where the engine's cost sits.
- **Arm (d) is a null.** It reproduces the vol-cap-removed arm exactly on NVDA and AMD, and
  on IWM it blocks 5× more days than the status quo for a 0.9-point ROC *loss*. It buys
  machinery and no benefit.
- **Arm (e) is the only arm that improves a symbol without removing the control.** AMD
  210.41% → 229.33% with 9 puts against 2; NVDA 33.64% → 65.17%, within a point of arm (b).

**Three warnings about reading this table.**

1. **Puts sold is not monotone in permissiveness, and higher is not better.** NVDA arm (a)
   sells 30 puts and arm (b) sells 21, yet (b) returns more. Blocking an early entry frees
   collateral that finances different later entries; the paths diverge and the counts are
   not comparable. Return on collateral is the metric that normalises for this, which is
   why R2 was pre-registered on it.
2. **`stage-2 blocked` means different things per arm.** For (a)/(c) it is the days the
   filter refused. For **(e) it is the days the rule fired and the response was a delta
   shift, not a ban** — the inner `_is_suitable_for_trading` still emits its rejection event
   before the harness flips the verdict, so the tally counts it. Arm (e) blocks **zero**
   days; the patch's own counter records 278 graduated days on NVDA, 432 on AMD. For **(d)**
   the tally *undercounts*, because the percentile rule is applied outside the live code and
   emits no event; its counter records 23 extra NVDA blocks.
3. **`days in position` rises sharply when the filter is loosened** (NVDA 236 → 466) because
   more entries mean more assignments and more time holding shares. That is capital
   commitment, not risk per se, but it is the mechanism behind the drawdown difference.

---

## Layer 3 — the real fills

Source: BigQuery `options_wheel.trades_from_activities`, read-only. Verified independently
of the FC-036 study and matching it: **330 sell-to-open fills, 2025-10-06 → 2026-07-28,
$68,518 premium, 8 underlyings, $20,599 net realized**. 327 are evaluable (3 fall after the
daily table's 2026-07-24 end).

### The decisive table — real entries split by each arm's own verdict

Because the filter never gated the live path, every real entry is observable under both
verdicts. This is a measurement, not a simulation.

| arm | verdict | entries | premium | net P&L | P&L/entry | return on collateral | assignment rate | loss rate | loss $/entry | worst-decile mean | worst-5 mean |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| (a) as-is | **blocks** | 123 | $29,649 | **$8,691** | **$70.66** | 0.31% | 10.6% | 7.3% | −$58 | −$594 | −$1,140 |
| (a) as-is | allows | 204 | $38,327 | $11,411 | $55.94 | 0.22% | 7.8% | 6.4% | −$38 | −$384 | −$1,139 |
| (b) off | allows | 327 | $67,976 | $20,102 | $61.47 | 0.25% | 8.9% | 6.7% | −$46 | −$463 | −$1,503 |
| (c) cap 50% | blocks | 105 | $25,111 | $7,275 | $69.29 | 0.30% | 10.5% | 7.6% | −$59 | −$617 | −$1,029 |
| (c) cap 50% | allows | 222 | $42,865 | $12,827 | $57.78 | 0.23% | 8.1% | 6.3% | −$40 | −$392 | −$1,195 |
| (c) cap 60% | blocks | 105 | $25,111 | $7,275 | $69.29 | 0.30% | 10.5% | 7.6% | −$59 | −$617 | −$1,029 |
| (c') vol cap removed | blocks | 96 | $23,386 | $6,745 | $70.26 | 0.31% | 9.4% | 7.3% | −$60 | −$639 | −$1,024 |
| (c') freq cap removed | blocks | 86 | $22,844 | $5,619 | $65.34 | 0.28% | 13.9% | 8.1% | −$76 | −$813 | −$1,140 |
| (c') freq cap removed | allows | 241 | $45,132 | $14,483 | $60.10 | 0.24% | 7.0% | 6.2% | −$35 | −$346 | −$1,139 |
| (d) own p80 | blocks | 146 | $36,273 | $9,811 | $67.20 | 0.27% | 11.0% | 7.5% | −$63 | −$653 | −$1,312 |
| (d) own p80 | allows | 181 | $31,703 | $10,291 | $56.86 | 0.23% | 7.2% | 6.1% | −$32 | −$314 | −$921 |

**Every arm blocks a set with a higher P&L per entry and a higher return on collateral than
the set it allows.** The status quo's blocked set is 37.6% of entries carrying 43.2% of net
realized P&L.

The honest counterweight, and it is real: the blocked set also carries **more of the risk**
— 10.6% assignment rate against 7.8%, and $58 of loss per entry against $38. So the filter
is not noise; it is picking up something. It is just that on this window the thing it picks
up costs $2.21 of gain for every $1 of loss it avoids ($15,874 of gains bundled with the
$7,183 of losses in the blocked set). Arm (c') "freq cap removed" — i.e. the
vol cap on its own — is the sharpest *risk* discriminator in the table (13.9% assignment
rate blocked vs 7.0% allowed, nearly 2×) and still gives up $5,619 to do it.

### Outcome by trailing vol at entry

| vol at entry | entries | premium | net P&L | P&L/entry | return on collateral | assignment rate | win rate | worst-decile mean | worst-5 mean | loss $/entry |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.00–0.20 | 19 | $2,157 | $378 | $19.89 | 0.07% | 5.3% | 94.7% | −$552 | −$92 | −$29 |
| 0.20–0.25 | 41 | $10,050 | $551 | $13.44 | 0.05% | 17.1% | 85.4% | −$1,060 | −$866 | −$106 |
| 0.25–0.30 | 38 | $5,948 | $2,817 | $74.13 | 0.28% | 5.3% | 97.4% | −$214 | −$116 | −$18 |
| 0.30–0.35 | 60 | $11,663 | $4,254 | $70.91 | 0.27% | 5.0% | 93.3% | −$327 | −$397 | −$34 |
| 0.35–0.40 | 83 | $15,314 | $6,483 | $78.10 | 0.35% | 4.8% | 96.4% | −$94 | −$165 | −$10 |
| **≥0.40** | **86** | **$22,844** | **$5,619** | **$65.34** | 0.28% | 13.9% | 91.9% | −$813 | −$1,140 | −$76 |

**86 real entries were taken above the 40% cap** — the direct empirical consequence of
Finding 0 — and they are the single largest premium bucket in the book ($22,844, a third of
it) at $65.34/entry, above the two lowest-vol buckets combined. The worst bucket by
per-entry P&L is **0.20–0.25** ($13.44, 17.1% assignment, −$106 loss per entry): the filter
would let all of those through.

### R1 — does elevated vol predict bad outcomes in real money?

The pre-registered comparison is the top vol decile (cut at 0.5997, n=35) against the rest
(n=292):

| metric | top decile | rest | ratio | R1 clause fires? |
|---|---:|---:|---:|---|
| P&L per entry | $77.95 | $59.50 | 1.31× **higher** | no (needed ≥25% lower) |
| assignment rate | 11.43% | 8.56% | 1.34× | no (needed ≥1.5×) |
| **worst-decile mean** | **−$940** | **−$413** | **2.28×** | **YES** |
| mean of worst 5 | −$547 | −$1,200 | 0.46× | no |
| loss rate | 5.7% (2 of 35) | 6.8% (20 of 292) | 0.84× | no |

**R1 fires on exactly one of five tail framings, and that framing is one trade.** The
top decile's worst-decile mean is the average of its **3 worst** trades, of which one is
AMD 2025-11-17, assigned, −$2,428. Remove nothing and widen the window to the worst five and
the sign inverts, because the rest-of-book tail contains AMZN −$1,517, MSFT −$1,352, AAPL
−$1,237 and NVDA −$979 — four of the five largest losses in the entire book were taken at
trailing vol between 0.22 and 0.40, i.e. inside the filter's comfort zone.

Reported as firing, per the pre-registration's own "any of" wording. But it is a
2-losers-out-of-35 statistic, and the overlay's answer to the same question — on 2,329
observations instead of 35 — points the other way.

### The rate-based forgone estimate (superseded)

The harness also carries a cruder estimator: blocked days × the symbol's observed entry rate
on allowed days × its realized P&L per entry. It totals **$6,023** across the six symbols
where it is defined, in the same direction and rough magnitude as the exact $8,691. It is
**degenerate for AMD** (0 allowed days in the live window ⇒ a 0/0 rate ⇒ a $0 estimate that
reads as "no cost" when the truth is "no denominator"), which is flagged in both the JSON
and the emitted table. The exact table above supersedes it.

---

## Overlay — 2,329 synthetic entries, because the engine's sample is too small

The engine opens 1–31 positions per symbol over 2.5 years. To answer "are blocked days
actually worse than allowed days" on a usable sample, the overlay prices a 7-DTE
0.175-delta short put on **every** session from daily bars, holds to expiry, keeps the
premium, and takes assignment: `pnl = (fill − max(0, K − S_T)) × 100`.

**Premium is modeled, and that is this layer's weakness.** Implied vol comes from inverting
Black-Scholes on the **real fills**: 68 put entries yield `IV = −0.0372 + 1.346 × RV`,
R² = 0.47, mean RV 0.329 → mean IV 0.405, median IV/RV ratio 1.11. Because that fit is
anchored at RV ≈ 0.33 and has a negative intercept, extrapolating it to AMD's 0.7–0.8
implies an IV/RV ratio that *rises* with vol (1.30 at RV 0.8) — which would flatter exactly
the days the filter blocks. So every comparison is also run under a constant-ratio model
(`IV = 1.11 × RV`) and under ±20% premium scaling. **No conclusion is reported that does
not survive all three.**

| symbol | arm | block rate | blocked n | blocked $/entry | allowed n | allowed $/entry | blocked assign% | allowed assign% | blocked worst-decile | allowed worst-decile | blocked / allowed under ratio IV | blocked / allowed at −20% premium |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| NVDA | (a) as-is | 55.9% | 269 | **$88.94** | 212 | $56.44 | 11.9 | 12.7 | −$285 | −$277 | $54.10 / $36.52 | $62.99 / $37.67 |
| NVDA | (c) cap 50/60% | 48.2% | 232 | $83.27 | 249 | $66.56 | 11.2 | 13.2 | −$322 | −$243 | $49.45 / $43.47 | $57.67 / $46.40 |
| NVDA | (c') freq cap removed | 42.4% | 204 | $91.10 | 277 | $62.48 | 12.8 | 11.9 | −$344 | −$237 | $52.44 / $41.87 | $63.29 / $43.39 |
| NVDA | (d) own p80 | 54.7% | 263 | $88.66 | 218 | $57.68 | 12.2 | 12.4 | −$285 | −$277 | $53.30 / $37.97 | $62.58 / $38.86 |
| AMD | (a) as-is | 94.3% | 581 | **$145.39** | 35 | **−$168.89** | 10.8 | **28.6** | −$508 | **−$1,489** | $93.98 / −$204.89 | $103.09 / −$186.55 |
| AMD | (c) cap 50% | 79.7% | 491 | $174.87 | 125 | −$58.43 | 8.3 | 25.6 | −$412 | −$1,019 | $121.42 / −$97.49 | $128.59 / −$78.18 |
| AMD | (c) cap 60% | 77.4% | 477 | $176.15 | 139 | −$39.32 | 8.6 | 23.0 | −$433 | −$971 | $121.65 / −$76.23 | $129.28 / −$59.72 |
| AMD | (c') freq cap removed | 89.5% | 551 | $148.93 | 65 | −$53.88 | 11.1 | 18.5 | −$536 | −$1,179 | $95.64 / −$81.06 | $105.30 / −$71.58 |
| GOOGL | (a) as-is | 16.1% | 99 | $82.85 | 517 | $34.82 | 7.1 | 12.8 | −$555 | −$528 | $57.17 / $17.89 | $53.76 / $15.23 |
| GOOGL | (c') freq cap removed | 7.8% | 48 | $100.37 | 568 | $37.65 | 6.2 | 12.3 | −$301 | −$550 | $78.57 / $19.61 | $73.75 / $17.00 |
| GOOGL | (d) own p80 | 32.0% | 197 | $98.80 | 419 | $16.09 | 5.6 | 14.8 | −$315 | −$603 | $73.47 / $1.04 | $70.31 / −$1.57 |
| IWM | (a) as-is | 4.1% | 25 | $127.20 | 591 | $23.58 | **0.0** | 11.5 | +$81 | −$398 | $112.76 / $17.94 | $101.76 / $9.52 |
| IWM | (d) own p80 | 20.3% | 125 | $94.80 | 491 | $10.72 | 3.2 | 13.0 | +$24 | −$463 | $84.43 / $5.84 | $74.79 / −$2.40 |

Pooled across the four symbols under the status quo: **974 blocked entries carrying
$119,778 of P&L ($122.97/entry), 1,355 allowed entries carrying $37,992 ($28.04/entry)** —
76% of the total sits in the blocked set.

**Three things this layer settles that the engine could not.**

- **The inversion is universal, not an AMD artifact.** Blocked > allowed on 4 of 4 symbols,
  every arm, both IV models, ±20% premium. R3 fails on every framing.
- **The tail does not rescue the filter either.** Blocked-day worst-decile means are
  comparable to or better than allowed-day ones on every symbol (NVDA −$285 vs −$277;
  GOOGL −$555 vs −$528; AMD −$508 vs **−$1,489**; IWM +$81 vs −$398). The days the filter
  lets through on AMD are the worst days in the entire study.
- **AMD's allowed set is the only losing bucket anywhere in the overlay.** The 35 sessions
  the status quo permits average **−$168.89** with a **28.6%** assignment rate. Mechanically
  this is because AMD's vol and gap frequency fall back inside the limits only after a
  sustained calm stretch, which in this window is what preceded its drawdowns. A control
  built to avoid gap risk selected, on AMD, precisely the pre-drawdown days.

---

## Bias footer — read before quoting any number above

1. **One volatility regime.** 2024-02 → 2026-07: a sustained bull market, no 2018-style vol
   shock, no 2020-style crash, no bear market. Realized vol and option premium rose together
   throughout. **Every "blocked days earned more" result in this document is conditional on
   that.** A vol filter is insurance; this window contained no fire. The study can show the
   filter cost money here; it cannot show it would be worthless in a crash.
2. **The real-fills window is 10 months, not 2.5 years.** Layers 1, 2 and the overlay cover
   2024-02 → 2026-07. **Layer 3 covers 2025-10-06 → 2026-07-28** because that is when the
   live account's first fill is. The money answer rests on 330 trades and 28 assignments.
3. **The overlay's premium is modeled, its outcome is not.** Prices come from Black-Scholes
   with a fill-calibrated IV; the underlying path, and therefore every assignment and every
   loss, comes from real bars. The IV fit is R² 0.47 on 68 points and is extrapolated on AMD.
   Both models and the ±20% band are reported for exactly this reason.
4. **The overlay ignores early profit-taking and the covered-call leg.** It holds to expiry
   and stops at assignment. That understates income on **both** sides of every comparison,
   so it is read as a comparison and never as a level.
5. **Layer 3's assignment mark is conservative and its call side is incomplete.** Assigned
   puts are marked `(expiry close − strike)`, ignoring covered calls later written against
   those shares and any recovery — which makes assigned trades look worse than the wheel
   eventually made them, and therefore **flatters the filter**. Stock-disposition P&L of
   called-away shares is not modelled; the call side is captured through its option leg only.
   84 of the 330 entries are calls.
6. **Replay premium is understated ~20%** (median sim/live 0.797,
   [fc-032-parity-check.md](fc-032-parity-check.md)). Layer-2 dollar figures inherit that.
   It is roughly proportional across arms, so differences are more reliable than levels.
7. **The engine barely trades, and FC-049 is a large part of why.** 1 put on GOOGL, 2–9 on
   AMD, 3–8 on IWM over 2.5 years; only NVDA clears the 10-entry bar. The original draft of
   this footer attributed that to stage-6 "already holding", the cost-basis drawdown pause,
   and FC-038's covered-call starvation. Those contribute, but the dominant mechanism is
   simpler and was visible in this study's own output before FC-049 was filed:
   **`calls_sold = 0` in all 36 arms**. Once a symbol is assigned it can never be called
   away, so stage 6 blocks every subsequent put for the rest of the window — GOOGL holds
   shares on 616 of 621 days after its single put. Recorded here as a miss: the evidence was
   in my own table and I read it as "the engine barely trades" without asking why.
8. **Layer 2's headline returns are not wheel income.** With the call leg dead, arms are
   dominated by unrealized stock appreciation: AMD 99.5% ($34,945 of $35,126), GOOGL 99.7%,
   IWM 98.2%, NVDA 54–79%. Return-on-collateral differences between arms are therefore
   largely differences in *when the symbol got assigned into a rising stock*, not in option
   selling. This is the single strongest reason the recommendation leans on Layers 1/3 and
   the overlay.
9. **Reconstruction precision is ±~0.005 of annualized vol at the frame edge**, which is
   enough to flip a verdict when vol sits on the 0.40 line — as the NVDA 2026-06-02
   disagreement shows. Block rates for NVDA, whose median vol is 0.407, carry that
   uncertainty; AMD's (median 0.491, median gap frequency 0.343) do not.
10. **Cloud Logging retention is 40 days.** Finding 0(c) is a 40-day observation. It is
   corroborated by 0(a) source inspection, 0(b) git history and 0(d) a 2025-10-06 fill, none
   of which depend on retention.
11. **Arm (e)'s delta shift lands one scan late for covered calls.** `_manage_existing_positions`
    (which sells covered calls) runs *before* `_find_new_opportunities` (which evaluates
    stage 2), so on any given day the call side uses the previous day's delta band. Puts are
    unaffected. Small, and it biases arm (e) toward the status quo.
12. **Arm (e)'s "half size" variant was not tested because it cannot exist.**
    `src/strategy/put_seller.py:182` hard-codes `contracts = 1`. There is no half contract.
    Only the delta-band variant of the plan's arm (e) is testable at current sizing.

---

## What the plan and the FC entry got wrong

**1. The FC entry's central diagnosis — "the binding constraint is the vol cap" — is half
right, and the half that is wrong matters more.** Confirmed: NVDA in Jun–Jul 2026 was
blocked on 35 of 38 sessions, all by the vol cap, with vol at 0.387–0.459 against a 0.400
line. Not confirmed: over the full window the two legs bind almost equally on NVDA (52.9%
vol-alone vs 51.3% frequency-alone), and on AMD — the symbol FC-002 is named for — the
**gap-frequency** leg is what blocks 100% of the live window. A plan that swept only the
vol cap would have moved AMD's block rate from 94.4% to 77.6% and left it untradeable.

**2. "AMD is gap-filtered on 47% of scans (262 of 553)" is stale by an order of magnitude
in the direction that matters.** It is 94.4% over 2024-02 → 2026-07 and **100% over the
live-fills window**. AMD's median 34-session vol in that window is 0.735.

**3. `vol_lookback_days: 252` is dead config, and the entry's "30-day vol" is also not
right.** Nothing reads `Config.vol_lookback_days`. The window is `gap_lookback_days + 20` =
50 **calendar** days ≈ 34 sessions, and it is shared with the gap-frequency ratio. A plan
that proposed tuning `vol_lookback_days` would have shipped a no-op.

**4. Neither the plan nor the entry checked whether the control they propose to tune is
connected to anything.** This is the finding with the largest consequence in the document
and it took one `grep` and one `git log -S`. FC-036's post-mortem made the same point about
its own plan's unverified BigQuery query; the general lesson is that a plan's *premise*
deserves at least one cheap verification before its *design* gets a section.

**5. The plan's arm (e) is under-specified in a way that made half of it unimplementable.**
"over-threshold ⇒ half size, or delta band shifted to [0.10, 0.15]" — half size is
impossible at `contracts = 1`. The plan should have checked the sizing path before offering
it as an arm.

**6. The plan's arm (d) is a good idea whose failure mode is visible before any P&L.** A
relative percentile gate fires on ~20% of days *by construction*, on every symbol, whatever
its absolute vol. On IWM (median vol 0.198) it blocks 20.1% of sessions against the status
quo's 4.0%, for no risk reduction — its blocked days have a **positive** worst-decile mean.
Any percentile gate needs an absolute floor beneath it, and the plan did not say so.

**7. What the plan got right, and it is what made the negative result cheap.** Specifying a
four-symbol minimum spanning two high-vol names and two calm ones is what exposed arm (d)'s
flaw and stopped AMD's extremity from being read as universal. And Track B's framing —
"published A/B studies … evidence, not code changes", with any threshold move gated behind
FC-002's own plan and two reviewers — is exactly the structure that lets this document
recommend "do not tune, fix the wiring question first" without needing to re-litigate a PR.

---

## Reproducing this document

```bash
OUT=/tmp/fc002
python3 tools/diagnostics/fc002_gap_filter_ab.py layer1  --out $OUT
python3 tools/diagnostics/fc002_gap_filter_ab.py verify  --out $OUT
python3 tools/diagnostics/fc002_gap_filter_ab.py layer3  --out $OUT   # needs gcloud auth login
python3 tools/diagnostics/fc002_gap_filter_ab.py overlay --out $OUT
python3 tools/diagnostics/fc002_gap_filter_ab.py layer2  --symbol NVDA  --out $OUT
python3 tools/diagnostics/fc002_gap_filter_ab.py layer2  --symbol AMD   --out $OUT
python3 tools/diagnostics/fc002_gap_filter_ab.py layer2  --symbol GOOGL --out $OUT
python3 tools/diagnostics/fc002_gap_filter_ab.py layer2  --symbol IWM   --out $OUT
python3 tools/diagnostics/fc002_gap_filter_ab.py markdown --out $OUT
```

Every table in this document is **emitted** by `markdown`, not typed by hand; the prose
figures are read from the same JSON. Raw outputs (`layer1.json`, `layer1_rows.json`,
`verify.json`, `layer2_<SYM>.json`, `layer3.json`, `layer3_entries.json`, `overlay.json`,
`overlay_trades.json`) are **not committed** — frozen data snapshots per the repo's
diagnostic-artifact policy, and `layer3_entries.json` carries per-trade account detail.

`layer3` reads BigQuery through the authenticated `bq` CLI. It is **strictly read-only and
never writes to `options_wheel`**. `layer2` costs ~10 minutes per symbol against an empty
`cache/backtest/chains/` (gitignored) and ~10 seconds per arm once warm; all four symbols
here ran against a warm cache in under five minutes total.

**Production code is untouched by this study.** Arms (d) and (e) are implemented as a
context-managed monkeypatch on `GapDetector.analyze_gap_risk` inside the harness, removed in
`finally`. Full suite: **645 passed**.
