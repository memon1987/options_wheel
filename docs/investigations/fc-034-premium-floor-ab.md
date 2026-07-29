# FC-034 — Premium-floor A/B: demote the low-price cohort, or re-shape the threshold?

**Study:** Track B2 of `docs/plans/fc-042.md` · **FC entry:** FC-034
**Harness:** `tools/diagnostics/fc034_premium_floor_study.py` — the pre-registered decision rules were committed in `fc926e8` **before any result was collected**.
**Date:** 2026-07-29
**Status:** evidence only. **No live threshold moves in this document.** Any change to `min_put_premium` / `min_call_premium` gates on FC-034's own plan and the two-reviewer process, per `docs/plans/fc-042.md` §Non-goals.

---

## Answer

**DEMOTE.** Drop F, PFE, KMI and VZ from `stocks.symbols`; leave the $0.50 flat floor alone.

The pre-registered rules return DEMOTE, and the single measurement that carries the decision is this one:

| symbol | median *richest* in-band put available per decision day |
|---|---|
| F | **$0.03** |
| KMI | **$0.05** |
| PFE | **$0.07** |
| VZ | **$0.08** |
| AAPL | **$0.51** |
| AMZN | **$0.53** |

Across 275 decision days, the best 0.10–0.20-delta ≤7-DTE put the cohort offers on a typical day is worth **three to eight cents a share — $3 to $8 per contract**. The controls offer ~$51–53. The threshold is not mis-shaped for these names; **the premium is not there.** Any floor loose enough to admit them is a floor that admits $3-per-contract trades, and on the same setting it takes AAPL from 50% to 94% of days — that is not re-shaping a threshold, it is removing one.

The full reasoning, the arms that were tried, and the two results that would have changed this answer are below.

---

## Read this first — the caveats that bound every number

1. **The engine window is 13 months, not the planned 2.5 years: 2024-02-01 → 2025-03-07, 275 decision days.** This is a deliberate, disclosed reduction — see *What the plan got wrong* §3. Alpaca's **trading-API** contract-discovery endpoint throttles hard enough that a full 2024-02→2026-07 cold chain build for six symbols did not complete in the time available; the window is the prefix that did.
2. **The engine window does not overlap the real-fills window.** Production's first sell-to-open fill is 2025-10-06, seven months after the engine window ends. The two layers therefore describe *different periods* and are complementary, not corroborating. Neither validates the other's period.
3. **One volatility regime**, and a mostly-rising one. Nothing here says how a re-shaped floor behaves in a 2022-style drawdown.
4. **The wheel never writes a covered call in any of these 18 runs** (`calls_sold = 0` everywhere, against 293 covered-call opportunities found on AAPL alone). Every assignment therefore becomes an unhedged long-stock position held to the end of the window, and **every high return-on-collateral figure below is stock direction, not premium.** This is a replay-path defect, described in *New findings* §1. It is the largest single threat to the engine layer's validity and the reason the premium-only column is the one to read.
5. **Modelled, not observed, option prices.** Marks are daily-bar trade prints; bid/ask and greeks are modelled (Black-Scholes inversion + `SpreadModel`). The spread model is still the after-hours 2.1× calibration that FC-042 C3 flagged as unproven intraday. A premium floor is a threshold *on price*, so this is the study's most load-bearing assumption — which is why every arm was replayed at the bid (§Fill sensitivity).
6. **Low trade counts on the excluded names bound the statistics.** Pre-registered rule R5 refuses to let any claim rest on fewer than 10 closed cycles. VZ's headline +16% annualized return-on-collateral under arms B and C comes from **one** put, and the engine correctly labels it `insufficient`.
7. **Dividends are modelled on both legs** (FC-042 Track C) and `dividend_coverage` reports `complete for this window` for all six symbols — the shortened window ends well inside the table, so the usual "window exceeds table" caveat does not apply here.
8. **One reconciliation gap is non-zero:** KMI arm B, $13.00, from the single cycle still open at the window edge. All other 17 runs reconcile to $0.00.

---

## The question

`min_put_premium: 0.50` (`config/settings.yaml`) is a **fixed dollar** hurdle applied identically to a $12 stock and a $340 one. It is enforced in exactly one live place — `MarketDataManager._check_put_criteria_detailed` (`src/api/market_data.py:586`), with the call-side twin at `:628`. `RiskManager._validate_option_specific_risks` re-checks the same floor at `src/risk/risk_manager.py:200`, but its only entry point `validate_new_position` **has no caller anywhere outside its own tests** — that path is dead. Anyone implementing an FC-034 change needs to touch exactly one file.

FC-032's coverage gate measured F, PFE, KMI at **0 usable decision days** and VZ at **2**, against 122/122 bar coverage, and the bot has never sold an option on any of the four. FC-042 Track C then found VZ collects **$0 dividends even after dividends were modelled**, because it holds shares on ~0 of 481 days — it never trades at all.

**FC-034's open question: demote those four, or re-shape the threshold?**

---

## Pre-registration

Written into `PREREGISTERED_RULES` and committed in `fc926e8` before the engine ran. `report` applies them mechanically in `_apply_rules`; the printed PASS/FAIL is not a judgement call.

**Outcomes.** **DEMOTE** — drop the four, leave the floor. **RE-SHAPE** — replace the flat floor with a scale-free shape, keep the four. **HYBRID** — keep the flat floor globally, add a per-symbol override for any excluded name that passes R1+R2.

| Rule | Content |
|---|---|
| **R1 — enablement** | A re-shape is on the table only if some arm lifts an excluded name's `days_in_position_fraction` to **≥ 0.25** (the engine's own `MIN_DAYS_IN_POSITION`, `metrics/fitness.py:37`) on **≥ 2 of the 4** names. If no arm does → DEMOTE. |
| **R2 — worth doing** | Each name R1 enables must, under that arm, show positive annualized return-on-collateral clearing the engine's `RISK_FREE_RATE` of **4%**, with verdict `fit` or `marginal` — never `insufficient` or `unfit`. |
| **R3 — control non-regression** | On **both** controls the enabling arm must not (a) cut annualized return-on-collateral by >10% relative, (b) worsen max drawdown by >2 pp, or (c) cut `puts_sold` by >10%. |
| **R4 — real-fills non-regression** | Applying the arm's floor to the 330 real sell-to-open fills must not retroactively block fills whose realized option P&L exceeds **10% of total premium collected** (~$6.9k of $68,518). |
| **R5 — statistical adequacy** | Any per-symbol claim resting on <10 closed cycles is directional only and cannot by itself satisfy R1 or R2. |

**Decision:** RE-SHAPE iff R1∧R2∧R3∧R4 for at least one arm; HYBRID if R1∧R2 but R3 or R4 fails; otherwise DEMOTE.

A "demote them, the floor is fine" outcome was an accepted result from the start.

---

## Arms

| Arm | Shape | Put floor | Call floor |
|---|---|---|---|
| **A** | flat (status quo) | `$0.50` | `$0.30` |
| **B** | % of strike | `max(0.40% × K, $0.05)` | `max(0.24% × K, $0.05)` |
| **C** | annualized return on collateral | `max(8% × K × DTE/365, $0.05)` | `max(4.8% × K × DTE/365, $0.05)` |

- **The call floor keeps the live 0.6× ratio** (`0.30/0.50`), so the arms change the *shape* and nothing else. A put-only re-shape would strand assigned low-price shares: the wheel could enter but never write the covered call.
- **A `$0.05` absolute tick floor on arms B and C.** Without it arm C is degenerate — an 8%-annualized floor at DTE 0 is `$0.00`, and at DTE 1 on a $12 stock it is `$0.003`. `$0.05`/share = `$5.00`/contract against the engine's `$0.04`/contract fee. Its effect is reported explicitly rather than assumed (§Chain census).

**Where each shape actually bites.** At 7 DTE, arm C's floor is `0.15% × K` and arm B's is `0.40% × K` — arm B is ~2.6× stricter at the strategy's target tenor, and on a $250 underlying its `$1.00` is **twice** the status quo. **A "%-of-strike" floor is not a loosening; on everything the bot currently trades it is a tightening.** That is what makes the controls load-bearing rather than decorative.

---

## Symbols and controls

Subjects: **F, PFE, KMI, VZ**. Engine controls: **AAPL and AMZN**. IWM is a control in the real-fills layer only.

The brief suggested AAPL+SPY or NVDA+QQQ. Measured, none of SPY, QQQ or NVDA can serve:

| Symbol | Close range 2023-12-01..2026-07-28 | `detect_split` | Universe on 2026-03-09 | Usable as engine control? |
|---|---|---|---|---|
| AAPL | 165.00 – 340.08 | None | 408 | **yes** |
| AMZN | 144.52 – 274.99 | None | 372 | **yes** |
| IWM | 174.82 – 300.45 | None | **1042** | fills layer only — cost, see below |
| SPY | 454.76 – 759.57 | None | — | no — **never** inside `[min_stock_price 10, max_stock_price 400]` |
| QQQ | 385.05 – 746.16 | None | — | no — above the cap for nearly the whole window |
| NVDA | 94.31 – 1224.40 | **(2024-06-10, 10:1)** | — | no — engine refuses split-spanning windows |
| AMD | 78.21 – 580.91 | None | — | no — breaches the $400 cap mid-window |
| MSFT | 352.83 – 542.07 | None | — | no — breaches the cap |
| UNH | 237.77 – 625.25 | None | — | no — breaches the cap |
| GOOGL | 129.27 – 402.62 | None | — | marginal — grazes the cap |

The `max_stock_price: 400` cap is a live **stage-1** gate: `wheel_engine.py:287` → `MarketDataManager.filter_suitable_stocks` → `get_stock_metrics`'s `meets_price_criteria` (`src/api/market_data.py:85`). A symbol above it is dropped before any chain is built, so its arm results would measure the price cap, not the premium floor.

> **Correction to a prior document.** `docs/investigations/fc-032-coverage-gate.md` explains SPY/QQQ's absence from real trades as an affordability effect ("a SPY cash-secured put reserves ~$60k of collateral… the gate measures chain usability, not affordability"). That is not the binding constraint: SPY's *lowest* close in the window is 454.76, so it fails `max_stock_price` on **every** day and never reaches the collateral test at all.

**IWM was the first choice and was dropped from the engine layer on cost, not merit.** A $175–300 ETF is the closest liquid name to the $12–48 cohort, which is exactly what makes a good control. But IWM's $1 strike ladder gives it a 1042-contract universe against AAPL's 408 and AMZN's 372, and under the trading-API throttle each IWM chain build cost ~13 minutes — roughly 40× AAPL. It remains a control in the `fills` layer, where it carries the study's **strongest** control result (22 of its 35 real fills fail arm B) from real money rather than simulation.

---

## Method

**`chain` — the census (no engine).** Walks all 275 decision days, records every priced put/call inside the live delta bands, then evaluates any floor shape offline from that one pass. It separates *"the contract did not exist"* from *"the contract existed and did not pay the floor"*, and affords a 12-point parameter sweep the engine could not.

**`engine` — the A/B.** Drives the real backtest engine once per (symbol, arm) through `evaluate_symbol`.

- A **fresh `Config` per arm** via `config._config["strategy"]["min_put_premium"]` — `Config.min_put_premium` is a read-only property (`src/utils/config.py:286`), so the backing dict is the only injection point.
- Arms B and C additionally install `_FloorShape`, which **wraps** `MarketDataManager._check_{put,call}_criteria_detailed`: it sets the backing config value to *this contract's* floor and delegates to the original method. Every other rule (DTE first, then premium, then delta, then liquidity) and every rejection string is therefore the production one — a hand-written copy would drift from production the moment anyone edited it, the exact failure mode FC-032 exists to avoid. Each run records how many contracts passed through the wrapper (arm A: 0; AAPL arm C: 14,041) so a silently-inert patch is impossible to miss.
- Arms share the warm parquet chain cache: the strike window the simulator requests is derived from bars alone (`Simulator._strike_anchors`), so it is arm-independent and all three arms hit the same files.
- `SimulationResult.rejections` is keyed by **description**, not raw event name; the premium-floor bucket is `"no put cleared delta/DTE/premium (stage 7)"` (from `no_suitable_puts`). The harness asserts that key exists in `_REASONS.values()` rather than silently reporting zeros if someone renames a bucket.
- A harness-local `_StageTally` captures what `rejections` cannot — see *New findings* §2.

**`fills` — the real-fills layer.** Read-only BigQuery via the authenticated `bq` CLI. This layer exists because of the FC-036 lesson: engine-only A/B called a gate "free" that 330 real fills priced at $1,900.

---

## Result 1 — the chain census

`python tools/diagnostics/fc034_premium_floor_study.py chain --symbol <SYM> --start 2024-02-01 --end 2025-03-07`

Percent of the 275 decision days on which **at least one in-band put clears the floor**:

| floor | F | PFE | KMI | VZ | **AAPL** | **AMZN** |
|---|---|---|---|---|---|---|
| *in-band put exists at any price* | 62.9 | 80.0 | 71.3 | 90.5 | 94.9 | 96.7 |
| $0.10 flat | 3.6 | 16.4 | 7.3 | 32.7 | 94.9 | 96.7 |
| $0.25 flat | 0.0 | 0.4 | 0.0 | 1.5 | 89.8 | 92.4 |
| **$0.50 flat (arm A, status quo)** | **0.0** | **0.4** | **0.0** | **0.7** | **49.8** | **52.7** |
| $1.00 flat | 0.0 | 0.4 | 0.0 | 0.0 | 8.7 | 11.6 |
| 0.20% of strike | 15.6 | 57.1 | 33.5 | 46.2 | 66.2 | 76.7 |
| **0.40% of strike (arm B)** | **15.3** | **10.5** | **5.8** | **8.4** | **16.4** | **22.9** |
| 0.60% of strike | 8.0 | 2.2 | 1.1 | 1.5 | 3.3 | 10.2 |
| 1.00% of strike | 2.2 | 0.4 | 0.0 | 1.5 | 0.0 | 4.0 |
| 4% ann. RoC | 15.6 | 68.4 | 36.7 | 83.6 | 94.9 | 96.7 |
| **8% ann. RoC (arm C)** | **15.6** | **68.4** | **36.7** | **79.6** | **93.8** | **96.7** |
| 12% ann. RoC | 15.6 | 58.9 | 34.2 | 58.9 | 88.0 | 94.5 |

Three things fall out immediately.

- **Arm A reproduces FC-032 on an independent window.** 0.0% / 0.4% / 0.0% / 0.7% usable days for F/PFE/KMI/VZ against ~50% for both controls.
- **Arm B is a tightening, not a loosening — including on the cohort.** It roughly triples F's usable days (0.0→15.3) but *cuts AAPL from 49.8% to 16.4%* and AMZN from 52.7% to 22.9%. There is no %-of-strike setting in the sweep that helps the cohort without gutting the controls: at 0.20% the cohort reaches 15–57% but the controls still fall to 66%/77%, and at 0.40% everything collapses together.
- **Arm C helps the cohort only by nearly removing the floor.** It takes AAPL from 49.8% to 93.8% and AMZN from 52.7% to 96.7%. An 8%-annualized floor at 7 DTE is `0.15% × K` = $0.36 on a $240 strike — below the status quo $0.50 on every name the bot trades. Its "success" on PFE (0.4→68.4%) and VZ (0.7→79.6%) is the same effect.

**The tick floor is what caps F.** Removing the `$0.05` tick from arm C lifts F from 15.6% to **62.9%** — i.e. F's entire remaining headroom sits at premiums *below five cents a share*. That is the finding, stated as a threshold: F's 0.10–0.20-delta weeklies are worth under $5 a contract.

**Premium actually available, per decision day** (richest in-band put, over the days one exists):

| symbol | days with an in-band put | p10 | **median** | p90 | max |
|---|---|---|---|---|---|
| F | 173 | 0.02 | **0.03** | 0.07 | 0.23 |
| KMI | 196 | 0.02 | **0.05** | 0.10 | 0.24 |
| PFE | 220 | 0.04 | **0.07** | 0.11 | 2.38 |
| VZ | 249 | 0.05 | **0.08** | 0.15 | 0.57 |
| AAPL | 261 | 0.28 | **0.51** | 0.97 | 1.68 |
| AMZN | 266 | 0.30 | **0.53** | 1.16 | 2.45 |

F's *maximum* over 173 days is $0.23. KMI's is $0.24. Neither name has ever, on any day in this window, offered a put that clears the current floor.

---

## Result 2 — the engine A/B

`python tools/diagnostics/fc034_premium_floor_study.py engine --symbol <SYM> --start 2024-02-01 --end 2025-03-07 --sensitivity`

275 decision days, $100k starting cash, mid-minus-25%-of-spread fills.

| sym | arm | puts | calls | cycles | closed | days-in-pos | RoC % | ann RoC % | total % | maxDD % | win | assn | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F | A | 0 | 0 | 0 | 0 | 0.00 | — | — | 0.00 | 0.00 | — | — | insufficient |
| F | B | 9 | 0 | 9 | 8 | 0.73 | −15.74 | −14.36 | −0.18 | −0.34 | 1.00 | 0.11 | unfit |
| F | C | 9 | 0 | 9 | 8 | 0.73 | −15.74 | −14.36 | −0.18 | −0.34 | 1.00 | 0.11 | unfit |
| PFE | A | 1 | 0 | 1 | 1 | 0.02 | 12.27 | 11.20 | 0.23 | −0.01 | 1.00 | 0.00 | unfit |
| PFE | B | 13 | 0 | 13 | 13 | 0.22 | 6.13 | 5.60 | 0.16 | −0.01 | 1.00 | 0.00 | unfit |
| PFE | C | 8 | 0 | 8 | 7 | 0.96 | 7.72 | 7.05 | 0.21 | −0.61 | 1.00 | 0.12 | marginal |
| KMI | A | 0 | 0 | 0 | 0 | 0.00 | — | — | 0.00 | 0.00 | — | — | insufficient |
| KMI | B | 6 | 0 | 6 | 5 | 0.08 | 3.16 | 2.89 | 0.08 | −0.01 | 1.00 | 0.00 | unfit |
| KMI | C | 32 | 0 | 32 | 32 | 0.49 | 8.83 | 8.06 | 0.20 | −0.01 | 1.00 | 0.00 | marginal |
| VZ | A | 2 | 0 | 2 | 2 | 0.03 | 3.21 | 2.93 | 0.11 | −0.00 | 1.00 | 0.00 | unfit |
| VZ | B | 1 | 0 | 1 | 0 | 0.84 | 17.74 | 16.19 | 0.73 | −0.60 | — | 1.00 | insufficient |
| VZ | C | 1 | 0 | 1 | 0 | 1.00 | 17.73 | 16.18 | 0.74 | −0.60 | — | 1.00 | insufficient |
| **AAPL** | A | 9 | 0 | 9 | 8 | 0.81 | 20.59 | 18.79 | 3.57 | −3.45 | 1.00 | 0.11 | marginal |
| **AAPL** | B | 15 | 0 | 15 | 15 | 0.28 | 7.08 | 6.46 | 1.46 | −0.15 | 1.00 | 0.00 | marginal |
| **AAPL** | C | 2 | 0 | 2 | 1 | 1.00 | 32.83 | 29.96 | 5.89 | −3.37 | 1.00 | 0.50 | marginal |
| **AMZN** | A | 6 | 0 | 6 | 5 | 0.92 | 15.63 | 14.26 | 2.61 | −4.00 | 1.00 | 0.17 | marginal |
| **AMZN** | B | 3 | 0 | 3 | 2 | 0.86 | 13.44 | 12.26 | 2.22 | −4.02 | 1.00 | 0.33 | marginal |
| **AMZN** | C | 11 | 0 | 11 | 10 | 0.96 | 16.17 | 14.76 | 2.72 | −4.00 | 1.00 | 0.09 | marginal |

**Read the attribution before the returns.** Because no covered call is ever written (caveat 4), any arm that took an assignment spent the rest of the window long the stock:

| sym | arm | option P&L | unrealized stock | dividends | total | avg collateral | **premium / collateral %** | bid-fill cost | as % of option P&L |
|---|---|---|---|---|---|---|---|---|---|
| F | B/C | 65.94 | −310.00 | 60.00 | −184.06 | 1,170 | **5.64** | 14 | **21.4** |
| PFE | A | 233.10 | 0 | 0 | 233.10 | 1,900 | **12.27** | 15 | 6.3 |
| PFE | B | 159.93 | 0 | 0 | 159.93 | 2,607 | **6.13** | 20 | 12.3 |
| PFE | C | 63.68 | −27.00 | 169.00 | 205.68 | 2,662 | **2.39** | 12 | **18.8** |
| KMI | B | 92.60 | 0 | 0 | 79.60 | 2,516 | **3.68** | 9 | 10.2 |
| KMI | C | 202.56 | 0 | 0 | 202.56 | 2,294 | **8.83** | 48 | **23.9** |
| VZ | A | 110.01 | 0 | 0 | 110.01 | 3,422 | **3.21** | 6 | 5.2 |
| VZ | B | 19.44 | 506.00 | 202.00 | 727.44 | 4,100 | **0.47** | 2 | 8.0 |
| VZ | C | 11.46 | 456.00 | 268.50 | 735.96 | 4,150 | **0.28** | 2 | 13.1 |
| AAPL | A | 588.63 | 2,907.00 | 75.00 | 3,570.63 | 17,341 | **3.39** | 24 | 4.1 |
| AAPL | B | 1,463.36 | 0 | 0 | 1,463.36 | 20,678 | **7.08** | 60 | 4.1 |
| AAPL | C | 135.63 | 5,657.00 | 100.00 | 5,892.63 | 17,950 | **0.76** | 7 | 5.1 |
| AMZN | A | 434.73 | 2,175.00 | 0 | 2,609.73 | 16,695 | **2.60** | 18 | 4.2 |
| AMZN | B | 290.82 | 1,925.00 | 0 | 2,215.82 | 16,488 | **1.76** | 12 | 4.2 |
| AMZN | C | 545.16 | 2,175.00 | 0 | 2,720.16 | 16,819 | **3.24** | 31 | 5.7 |

- **VZ's headline 16% annualized RoC is a long-stock position.** One put, assigned, shares held for the rest of the window: +$506 unrealized + $202 dividends against **$19.44** of premium. The engine says `insufficient`; R5 says the same. This is the KMI-at-+138% trap, and it recurred exactly as the brief warned.
- **AAPL arm C's 29.96% is the same artifact** — $5,657 of unrealized stock against $135.63 of option income.
- **The premium-only column is scale-free and unflattering.** F's "enabled" trading earns $65.94 over 13 months. KMI's best arm earns $202.56.
- **F loses money once enabled.** −15.74% return on collateral: the premium collected ($66) plus dividends ($60) does not cover the assigned shares' $310 mark-to-market loss.

### Fill sensitivity

Every arm was replayed at the bid. **No verdict flipped anywhere.** But the *cost* of the fill assumption scales inversely with premium: it eats **19–24% of the cohort's option income** (F 21.4%, PFE arm C 18.8%, KMI arm C 23.9%) against **4–6% for the controls**. A three-cent premium cannot survive a spread that the model is not even calibrated for intraday (caveat 5). Every cohort number above should be read as an upper bound.

---

## Result 3 — the real fills

`python tools/diagnostics/fc034_premium_floor_study.py fills` — read-only against `options_wheel.trades_from_activities`.

**Verified from production, not assumed:** 330 sell-to-open FILLs, **8 underlyings**, $68,518 premium, 2025-10-06 → 2026-07-28. Minimum fill price $0.58.

| underlying | put fills | call fills | premium | min price |
|---|---|---|---|---|
| NVDA | 80 | 21 | $14,017 | 0.71 |
| AMD | 46 | 9 | $15,888 | 0.58 |
| GOOGL | 27 | 19 | $10,848 | 0.78 |
| AMZN | 26 | 18 | $13,306 | 0.62 |
| IWM | 27 | 8 | $4,876 | 0.58 |
| UNH | 27 | 4 | $6,691 | 0.65 |
| AAPL | 8 | 3 | $1,469 | 1.04 |
| MSFT | 5 | 2 | $1,423 | 1.53 |

**F, PFE, KMI and VZ appear zero times.** So do SPY and QQQ — the latter two for the price-cap reason above, not the premium floor. The cohort's absence is the production-side ground truth for "structurally untradeable", and it is stronger than absence usually is: all four sat in `stocks.symbols` and were scanned on every cycle for the entire 10 months.

**What each arm would have done to trades the bot actually took:**

| arm | real fills blocked | premium blocked | realized option P&L destroyed | tightest surviving fill |
|---|---|---|---|---|
| **A** ($0.50 flat) | **0 / 330** | $0 | $0 | IWM 249P, $0.58 vs $0.50 floor — **8c of headroom** |
| **B** (0.40% of strike) | **47 / 330 (14.2%)** | $4,172 | **$2,235** | UNH 372.5P, $1.49 vs $1.49 — **0c** |
| **C** (8% ann. RoC) | 0 / 330 | $0 | $0 | IWM 249P, $0.58 vs $0.4366 — 14c |

Arm B's damage, by underlying: IWM $864 (22 of its 35 fills), GOOGL $438, AMZN $427, UNH $283, AAPL $120, AMD $103. Cross-checked independently in SQL: `COUNTIF(price < 0.004*strike_price)` returns **47 of 246 real puts (19.1%) and 0 of 84 calls** — matching the harness exactly.

This is the FC-036 lesson repeating. Arm B looks defensible in the engine (it *raises* AAPL's put count 9→15 and its premium income $589→$1,463) and is a **$2,235 tax on real trades**. Expressed as percentiles of what production actually collects: real put fills run **min 0.199%, p10 0.328%, median 0.546% of strike**. Arm B's 0.40% sits between the 10th and 50th percentile of the bot's own trades. **A %-of-strike put floor calibrated not to disturb production would have to be ≤0.20% of strike — which on F is $0.022, i.e. no floor at all.**

Arm C blocks nothing, but that is the same fact as "arm C is barely a floor": its tightest real fill cleared by 14c because at 8 DTE on a $249 strike the floor is only $0.44.

---

## Applying the pre-registered rules

Machine-evaluated by `_apply_rules`; reproduce with `report`.

| Rule | Verdict | Evidence |
|---|---|---|
| **R1 — enablement** | **PASS** | arm B lifts 2/4 (F, VZ) to ≥0.25 days-in-position; arm C lifts **4/4** (F, PFE, KMI, VZ). |
| **R2 — worth doing** | **FAIL** | arm C: F annRoC **−14.36%**, `unfit`; PFE `marginal` but only **7** closed cycles (R5); VZ `insufficient`, **0** closed cycles; **only KMI passes** (8.06%, `marginal`, 32 closed cycles). arm B: F `unfit`, VZ `insufficient`. |
| **R3 — control non-regression** | **FAIL** | arm B: AAPL annRoC 18.79%→6.46% (**−66%**); AMZN 14.26%→12.26% (−14%) and puts 6→3 (−50%). arm C: AAPL puts 9→2 (−78%). |
| **R4 — real fills** | **PASS** | arm B destroys $2,235 vs a $6,852 budget; arm C destroys $0. |

R1∧R2∧R3∧R4 fails (RE-SHAPE is out). R1∧R2 fails (HYBRID is out). → **DECISION: DEMOTE.**

**Where I'd push back on my own rules.** R4's 10%-of-premium budget was set generously in pre-registration, and arm B passes it at $2,235 — yet arm B is plainly the worst arm on every other axis. Had R4 been the only control rule, a bad arm would have squeaked through. R3 is what caught it, which is an argument for keeping *both* a simulated and a real-money control rather than either alone. I am reporting arm B's $2,235 as a headline number despite its formal PASS, because a rule passing is not the same as a result being benign.

**The one genuinely close call is KMI.** It is the only name that satisfies R2 cleanly under arm C — 32 closed cycles, 8.06% annualized return on collateral, `marginal`, and its cycles never took an assignment, so unlike VZ and AAPL that figure is *actual premium* rather than stock direction. A per-symbol-override HYBRID scoped to KMI alone is the strongest case the data supports for keeping anything. It still fails on its merits: KMI's $202.56 of premium over 13 months against $2,294 of committed collateral is 8.8%, of which the bid-fill assumption alone consumes **23.9%**, and the arm that produces it takes AAPL's usable days from 50% to 94%. You cannot buy KMI's 8.8% without paying for that.

---

## Recommendation

*Evidence above; proposal below. This is a proposal, not a change.*

1. **Demote F, PFE, KMI and VZ** from `config/settings.yaml` `stocks.symbols`. They occupy 4 of 14 universe slots and consume screening budget while being structurally incapable of a trade. **Leave `min_put_premium: 0.50` and `min_call_premium: 0.30` exactly as they are.** This needs an FC-034 plan and two reviewers because it changes the live universe.
2. **Record the floor's shape as a known, accepted limitation rather than a bug.** The right generalisation is not "%-of-strike" or "annualized RoC"; it is that **a wheel candidate must offer ≥ ~$0.50 of weekly premium at 0.10–0.20 delta**, and price is merely a proxy for that. If a future low-priced candidate is proposed, the test is the census in Result 1 — run `chain` for the symbol and read the median richest in-band put — not a price threshold.
3. **Do not adopt a %-of-strike floor in any form.** It is a tightening on every name the bot trades, and the only setting that leaves production undisturbed (≤0.20% of strike) is indistinguishable from no floor on the cheap names.
4. **The call-side floor (`min_call_premium: 0.30`) was not answerable here** and FC-034's fourth open question stays open: no covered call was written in any of the 18 runs (caveat 4). Re-run this study's call-side arms once *New findings* §1 is fixed.
5. **Consider raising `min_stock_price`.** F was blocked at stage 1 on 43 of 275 decision days by `min_stock_price: 10.00` — and F is the only universe symbol anywhere near that line. If F is demoted, the `10.00` floor has no remaining subject and is dead config; if a low-price candidate is ever reconsidered, note that the price band and the premium floor were both binding on F, independently.

---

## New findings (not part of the brief)

1. **The replay never executes a covered call — 293 opportunities, 0 sales.** On AAPL the engine logs 293 `stage_8_complete_found` / `call_opportunity_found` events and then **147 `call_rejected_by_put_seller`** — `src/strategy/put_seller.py:245`'s safety guard firing because the opportunity reached the *put* seller. `ExecutionEngine.execute_batch` routes on `opp.get('type', 'put')` (`src/strategy/execution_engine.py:286`), defaulting to the put path when the key is absent, and the covered-call opportunities the replay assembles do not carry it. Also present: 1,774 `call_validation_failed` (`src/api/market_data.py:441`) and 146 `active_calls_mismatch` (`src/strategy/wheel_engine.py:1113`). **Production is not obviously affected** — it has sold 84 real covered calls (NVDA 21, GOOGL 19, AMZN 18, AMD 9, IWM 8, UNH 4, AAPL 3, MSFT 2) — so this looks replay-path-specific, but it invalidates the wheel's second leg in every backtest run to date and should be filed as its own FC. Related prior art: the covered-call starvation investigation of 2026-07-18.
2. **`SimulationResult.rejections` cannot see stage-1 blocks.** `engine/rejections.py::_REASONS` has no entry for `stock_rejected_filter`, so a day dropped on the price band vanishes from the breakdown entirely. Measured on a 2-month F replay: 39 decision days, 13 mapped stage-7 blocks, and **26 days with no recorded reason at all** — every one of them F below `min_stock_price`. Over the study window: F is stage-1-blocked on **43 of 275 days** and gap-filtered on 32 more. Adding `stock_rejected_filter` (and the stage-8 call-side buckets) to `_REASONS` is a small, safe improvement worth doing.
3. **`dte_at_event` in `trades_from_activities` is unreliable — do not use it.** It is `0` on **232 of 330** sell-to-open fills (70%), while those same rows' true DTE (`expiration − fill date`) averages 5.29 and ranges 2–8. Any metric that scales with DTE and reads this column is wrong. This harness computes DTE in SQL instead; reading the column produced a spurious "arm C blocks nothing" result on the first pass. Worth a data-quality FC.
4. **`RiskManager.validate_new_position` is dead code.** No caller anywhere outside `tests/test_risk_manager.py`. Its premium/delta/DTE checks (`src/risk/risk_manager.py:174-215`) have never run in production. Either wire it or delete it — as it stands it is a second definition of the trading rules that silently cannot disagree with the first because it never executes.

---

## What the plan got wrong

1. **The suggested controls do not work.** `docs/plans/fc-042.md` B2 says "F/PFE/KMI/VZ plus two liquid controls", and the brief proposed AAPL+SPY or NVDA+QQQ. SPY (454.76–759.57) and QQQ (385.05–746.16) sit above `max_stock_price: 400` for the whole window and are dropped at stage 1 — a SPY arm would measure the price cap. NVDA spans the 2024-06-10 10:1 split, which the engine refuses. Only AAPL of the four proposals survives.
2. **The `$0.50` / `0.4%` / `8%` arm parameters are not on the same side of the status quo, and the plan reads as if they were.** At 7 DTE, 0.4%-of-strike is ~2.6× stricter than 8%-annualized, and on a $250 underlying it is *twice* the current dollar floor. Framing both as candidate "re-shapes" of a floor obscures that one of them is a large tightening of live behavior. That asymmetry is the study's main result on the control side.
3. **The window was not affordable and Track A's cache note under-states why.** FC-042's A2 execution note attributes long runs to chain volume and reports the cache as the fix. The actual wall-clock constraint here was Alpaca's **trading-API** contract-discovery endpoint (`paper-api…/v2/options/contracts`), which throttles independently of the market-data limit and does not respond to sharding — 18 parallel prefetch processes ran *slower* in aggregate (~11 chains/min) than 6 did (~20/min). The full 2024-02→2026-07 window for six symbols was not reachable; this study runs 2024-02-01 → 2025-03-07. **The consequence is stated in caveat 2 and is real: the engine and fills layers no longer share a period.**
4. **`tools/diagnostics/fc036_gap_gate_study.py` has a latent version of the same defect.** Its `_install_rate_limit_retry` matches only `"too many requests"`, but the trading client raises `APIError {"code":42910000,"message":"rate limit exceeded"}`. Contract discovery has never been protected by that retry. This harness matches both.
5. **"Days in position" is a poor enablement proxy when the call leg is broken.** R1 used `days_in_position_fraction ≥ 0.25` on the engine's own authority (`MIN_DAYS_IN_POSITION`). With no covered calls being written, a single assignment pins that metric near 1.00 for the rest of the window — VZ scores 1.00 off **one** put. R1 passed for arm C on all four names largely because of this. R2 and R5 caught it, but a future study should pair the metric with a minimum closed-cycle count in the rule itself, not in a separate rule.

---

## Reproducing

```bash
export FC034_OUT=/tmp/fc034
S="--start 2024-02-01 --end 2025-03-07"
for s in F PFE KMI VZ AAPL AMZN; do
  python tools/diagnostics/fc034_premium_floor_study.py prefetch --symbol $s $S   # cold cache
  python tools/diagnostics/fc034_premium_floor_study.py engine   --symbol $s $S --sensitivity
  python tools/diagnostics/fc034_premium_floor_study.py chain    --symbol $s $S
done
python tools/diagnostics/fc034_premium_floor_study.py fills       # read-only BigQuery
python tools/diagnostics/fc034_premium_floor_study.py report --symbols F,PFE,KMI,VZ,AAPL,AMZN
```

Run the prefetch with **at most one process per symbol**; the trading-API throttle makes more concurrency slower, not faster. Cold cache for six symbols over this window is roughly 90 minutes; warm, all 18 engine runs finish in under a minute.
