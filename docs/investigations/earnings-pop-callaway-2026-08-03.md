# Earnings-Pop Call-Away Investigation — Current Holdings

**Date:** 2026-08-03
**Author:** Claude (Fable), senior-options-trader lens
**Scope:** every held symbol with an open short call (enumerated live: AAPL, AMZN, GOOGL, NVDA)
**All marks timestamped 2026-08-03 19:51:16 UTC (15:51 ET)** via Alpaca IEX stock quotes and OPRA option NBBO. All fills from BigQuery `options_wheel.trades_from_activities`. Candidate deltas/scores from the GCS scan blobs (`gs://options-wheel-opportunities/opportunities/`). Earnings dates from `src/backtesting/data/earnings_dates.json` as refreshed on `fc-013/step0-audit` (generated 2026-08-03, yfinance).

---

## 1. Summary

### The operator's premise, corrected first

The observation was: *"covered calls were sold on GOOGL, AMZN, AAPL around their earnings; the stocks popped; the open calls are now ITM."* The data supports **one-third** of that:

- **AMZN is the genuine earnings-pop call-away.** The C262.5 was sold at 10:15 ET on **the morning of earnings day** (7/30, AMC report) with the stock at ~$236.7 — 10.9% OTM, premium juiced to $2.22 by earnings IV (0.68). AMZN gapped **+12.3%** overnight (235.75 → 264.80 open) *through* the strike and now trades ~$285.6. The call is $23 ITM.
- **GOOGL did not pop on earnings — it gapped DOWN 6.1%** (7/22 AMC: 342.06 close → 321.00 open). The open C370 was sold **9 days after** earnings (7/31, stock ~352, 5.1% OTM) and was then run over by a **post-earnings momentum rally** (+6% in the next two sessions). It is $4.0 ITM. No earnings gate variant would have touched this sale.
- **AAPL gapped DOWN 8.5% on earnings** (7/30 AMC: 333.07 → 304.76 open). Its open C312.5 was sold **after** earnings (8/03) and is **OTM**. Nothing is being surrendered. (AAPL's pre-earnings spanning call, C347.5 sold hours before the report, *profited* $165 on the gap down.)
- **NVDA** (open C220 exp 8/10, OTM, stock 207.1): earnings are 8/26, after expiry. No earnings interaction.

So the live book demonstrates **both tails of the same exposure**: one spanning call destroyed by a gap-up (AMZN), two spanning calls that profited from gap-downs (GOOGL C370 7/24 +$374, AAPL C347.5 +$165), and one ITM call that no earnings gate can address because the risk was plain momentum (GOOGL).

### Summary table (marks 2026-08-03 15:51 ET)

| | AMZN | GOOGL | AAPL | NVDA |
|---|---|---|---|---|
| Shares / basis (Alpaca avg_entry) | 100 @ 261.20 | 100 @ 368.34 | 100 @ 303.50 | 100 @ 218.43 |
| Lot origin (put assignment) | P262.5 assigned 6/05 | P370 assigned 6/05 | P305 assigned 6/12 | P220 assigned 6/08 |
| Open call | C262.5 exp 8/07 | C370 exp 8/07 | C312.5 exp 8/05 | C220 exp 8/10 |
| Sold (ET) / premium | 7/30 10:15 / $2.22 | 7/31 11:53 / $1.49 | 8/03 12:15 / $0.77 | 8/03 14:15 / $0.85 |
| Delta / score at sale (scan blob) | 0.170 / 81.7 | 0.170 / 73.2 | 0.166 / 86.0 | 0.155 / 81.8 |
| days_until_earnings at sale | **0** (7/30 AMC) | 89 (next 10/28) | 87 (next 10/29) | 23 (8/26) |
| Expiry spans earnings? | **YES** (8/07 ≥ 7/30) | no | no | no (8/10 < 8/26) |
| Stock mark | 285.58 | 373.98 | 303.59 | 207.11 |
| Call mark (bid/ask) | 22.77 / 23.93 | 8.28 / 8.87 | 0.54 / 0.62 | 0.63 / 0.70 |
| Intrinsic / time value (mid) | 23.08 / 0.27 | 3.98 / 4.60 | 0 (OTM 2.9%) | 0 (OTM 5.9%) |
| **Foregone upside (mark − strike)×100** | **$2,308** | **$398** | $0 | $0 |
| If called away: realized this leg | +$352 | +$315 | (+$977 if assigned) | (+$242 if assigned) |
| Gate variant that would have blocked the sale | **ALL** (N=1..7, SPAN) | **NONE** | NONE | NONE |

**The decision-relevant number: $2,706 of upside is currently surrendered ($2,308 AMZN + $398 GOOGL) against $533 of premium collected on the four open calls — 5.1 : 1. AMZN alone is 10.4 : 1 ($2,308 vs $222).**

Honest counters, stated up front:

- These are **mark-dependent paper numbers with 2–4 DTE remaining**. The pop can retrace before Friday; every dollar AMZN gives back shrinks the surrender dollar-for-dollar. Conversely GOOGL's $4.60 of time value means closing it costs far more than intrinsic today.
- The premium **was** collected, and on the two gap-down spanners the identical trade shape *made* money. Per-position, per-lot, the wheel is **ahead of buy-and-hold on GOOGL and AAPL** (see §2) — the surrender concentrates entirely in AMZN.

---

## 2. Per-position lineage

### AMZN — the earnings-pop case

- **Equity lot:** 100 sh from AMZN260605P00262500 assignment (OPASN 2026-06-06; put sold 5/29 @ $1.30). Alpaca `avg_entry_price` 261.20 = 262.50 strike − 1.30 premium.
- **Open call:** `AMZN260807C00262500`, sold_short 2026-07-30 14:15:04 UTC (10:15 ET) @ $2.22 ($222), order `9e92a6e4`. Executed from the 7/30 14:00 UTC scan blob (`status: executed, executed_count: 1`).
- **At the moment of sale:** spot $236.73 (blob), strike 10.9% OTM, delta 0.1696, IV 0.68 (earnings-pumped — compare GOOGL's 0.36 the next day), attractiveness_score 81.7. `days_until_earnings = 0` (AMZN reported 7/30 AMC); `span = True` (expiry 8/07 ≥ 7/30).
- **Which gates evaluated it:** only the cost-basis floor existed on the sell path. Floor passed because 262.5 ≥ 261.20 (`assignment_above_cost_basis: true`). **No earnings gate existed on any live path** (FC-013's core finding, reconfirmed here). Note the interplay: with the stock at $236.7, the floor *forced* the strike 10.9% OTM — far above where the delta band alone would have priced a call — and earnings IV is the only reason a strike that far out cleared the $0.30 premium floor. The floor accidentally limited the damage (a non-floored 0.17Δ strike would have sat ~$245); earnings IV is the reason the trade existed at all. **Earnings IV making far-OTM strikes sellable is itself the selection hazard**: the bot is structurally *attracted* to the day-of-earnings trade because that is when premium looks best.
- **Prior cycle on this lot:** C262.5 exp 7/22 (7/15 sold 1.64 → 7/17 closed 0.51, +$113). Did not span earnings (7/22 < 7/30).
- **Impact at marks (15:51 ET):** stock 285.58 (bid/ask 285.56/285.60); call 22.77/23.93, mid 23.35 — intrinsic 23.08, time value 0.27 at mid (0.85 at ask). Called away Friday: realized = (262.5 − 261.20)×100 + 222 = **+$352** (lot total since assignment +$465 incl. the closed call). Buy-and-hold on the same lot: **+$2,438** unrealized (+$113 closed call). **Net surrender vs B&H = $2,086** (= 2,308 foregone − 222 premium).
- **Early-assignment note:** AMZN pays no dividend; ~$0.85 time value at the ask means early exercise is unlikely before expiry week. Expect assignment at Friday 8/07 expiry if the stock holds above 262.5.

### GOOGL — the momentum case wearing an earnings costume

- **Equity lot:** 100 sh from GOOGL260605P00370000 assignment (OPASN 2026-06-06; put sold 5/29 @ $1.66). Basis 368.34.
- **Open call:** `GOOGL260807C00370000`, sold 2026-07-31 15:53:03 UTC (11:53 ET) @ $1.49, order `c9195b14`, from the 7/31 15:00 UTC blob.
- **At sale:** spot $352.18 (blob), 5.1% OTM, delta 0.1699, IV 0.359, score 73.2. GOOGL's earnings were **9 days earlier** (7/22, gap **down** 6.1%); next earnings 10/28 → `days_until = 89`, `span = False`. **No FC-013 variant, at any N, blocks this sale.** The stock then rallied 352 → 374 in two sessions (7/31 intraday +4.4%, 8/03 +5%) — post-earnings momentum, not an event gap.
- **Floor note (FC-071 relevance):** the 7/31 blob shows `cost_basis_per_share: 370.0` and `assignment_above_cost_basis: false` — the pre-FC-065-deploy resolver was still serving the BQ assignment strike (370) rather than Alpaca's 368.34, so this sale was priced **exactly at the floor**: if called away under the resolver's own basis it books $0 equity gain. Under the true basis it books +$166. This is the at-floor scoring asymmetry FC-071 tracks, live.
- **Full call history on this lot** (assigned 6/05; every one closed by DTE-band profit-taking or expiry-day buyback, zero assignments): 9 round trips, June +$335 (C375, C372.5, C377.5, C380), July +$945 (C370 ×3, C395, C370-spanner) = **+$1,280 realized call income**. Two of those *spanned* the 7/22 earnings — C395 sold 7/16 (days_until 6) and C370 sold 7/17 (days_until 5) — and both profited **because the stock gapped down**: +$210 and +$374 (bought back at $0.01 on 7/24).
- **Impact at marks:** stock 373.98; call 8.28/8.87, mid 8.57 — intrinsic 3.98, **time value 4.60** (elevated IV; expensive to buy back relative to moneyness). Foregone upside $398 vs $149 premium → net surrender $249. Called away: +$315 this leg; **lot total +$1,595 vs B&H +$563.50 — the wheel is $1,031 AHEAD of buy-and-hold on GOOGL** because it harvested the June–July round-trip (368 → 390 → 315 → 374) that B&H rode for nothing.

### AAPL — the mirror image (gap down through a spanning call)

- **Equity lot:** 100 sh from AAPL260612P00305000 assignment (OPASN 2026-06-13; put sold 6/08 @ $1.50). Basis 303.50.
- **Open call:** `AAPL260805C00312500`, sold 2026-08-03 16:15:15 UTC (12:15 ET) @ $0.77, order `891221eb`, from the 8/03 16:00 blob. Spot at sale 303.67, 2.9% OTM, delta 0.166, score 86.0 (beat the C310 8/05 @ 0.24Δ / 85.2 and C312.5 8/07 @ 0.23Δ / 85.0 siblings). `days_until = 87` (next earnings 10/29), `span = False`. Never blockable; currently **OTM** — nothing surrendered; +$19 unrealized on the call.
- **The earnings event this lot actually lived through:** AAPL ran 303 → 344 during July (the lot carried ~+$2,950 unrealized into earnings), reported 7/30 AMC, and gapped **down 8.5%** (333.07 → 304.76). The unrealized share gain round-tripped to ~$0. The call sold **3 hours before the report** — C347.5 exp 8/03 @ $1.66, `days_until = 0`, `span = True` — was bought back next morning at $0.01: **+$165**. That is the same trade shape as AMZN's disaster with the coin landing the other way.
- **Lot economics:** 6 closed calls since assignment +$495 realized; B&H unrealized on the lot: +$8.50. The wheel is ~$560 ahead of B&H on AAPL.

### NVDA — held symbol with an open call, no earnings interaction

- **Equity lot:** 100 sh from NVDA260608P00220000 assignment (OPASN 2026-06-09; put sold 6/02 @ $1.57). Basis 218.43. Stock 207.11 → −$1,132 unrealized.
- **Open call:** `NVDA260810C00220000` sold 2026-08-03 18:15:04 UTC @ $0.85, delta 0.155, score 81.8, spot 208.13 at sale. Earnings **8/26** — `days_until = 23`, expiry 8/10 **< **earnings → `span = False`. OTM (5.9%); mark 0.67 mid.
- 11 closed calls since assignment, +$584 realized — the premium engine slowly grinding against an underwater lot. Note for the calendar: any ~7-DTE call sold from **8/19 onward** will span the 8/26 report; NVDA is the next live test of whatever N ships.

---

## 3. Gate counterfactual — FC-013 variants applied to this window

Semantics per fc-013.md DD-3: block when `0 ≤ days_until_earnings ≤ N` (calendar days); SPAN blocks when the candidate's expiry ≥ next earnings date. Applied to **every call sale on the held book, 7/15 – 8/03**:

| Call sale | days_until | span | Outcome as traded | N=1 | N=2 | N=3 | N=5 | N=7 | SPAN |
|---|---|---|---|---|---|---|---|---|---|
| AMZN C262.5 7/22 (7/15) | 15 | no | +$113 closed | – | – | – | – | – | – |
| GOOGL C395 7/24 (7/16) | 6 | **yes** | +$210 closed (gap down) | – | – | – | – | **B** | **B** |
| GOOGL C370 7/24 (7/17) | 5 | **yes** | +$374 closed (gap down) | – | – | – | **B** | **B** | **B** |
| **AMZN C262.5 8/07 (7/30)** | **0** | **yes** | **−$2,308 upside open** | **B** | **B** | **B** | **B** | **B** | **B** |
| AAPL C347.5 8/03 (7/30) | 0 | **yes** | +$165 closed (gap down) | **B** | **B** | **B** | **B** | **B** | **B** |
| GOOGL C370 8/07 (7/31) | 89 | no | −$398 upside open | – | – | – | – | – | – |
| AAPL C312.5 8/05 (8/03) | 87 | no | OTM, +$19 | – | – | – | – | – | – |
| NVDA C220 8/10 (8/03) | 23 | no | OTM, +$15 | – | – | – | – | – | – |

**Net effect per variant, at today's marks** (upside preserved − winning premium forgone):

| Variant | Blocks | Upside preserved | Premium forgone | Net benefit |
|---|---|---|---|---|
| N=1, 2, 3 | AMZN 7/30, AAPL 7/30 | $2,308 | $387 ($222 + $165) | **+$1,921** |
| N=5 | + GOOGL C370 7/17 | $2,308 | $761 | +$1,547 |
| N=7 | + GOOGL C395 7/16 | $2,308 | $971 | +$1,337 |
| SPAN | same four as N=7 | $2,308 | $971 | +$1,337 |

Two honesty adjustments:

1. **Re-arm effect.** A blocked 7/30 AMZN sale doesn't preserve the full $2,308: on 7/31 the bot would have re-armed post-pop (spot 264.80 open, floor 261.20) and sold a ~0.17Δ call around $278–283, which at today's 285.58 would itself be ~$300–800 ITM. Realistic preserved value ≈ **$1,500–2,000** — still roughly an order of magnitude above the $222 forgone. The gate converts *gap-through-strike* exposure into ordinary *post-event drift* exposure; it does not abolish call-away.
2. **Sample honesty.** In this window, every incremental block above N=1 removed only *winners* (the two GOOGL gap-down spanners). That is coin-flip luck, not design: GOOGL's 7/17 C370 held through the 7/22 report with exactly AMZN's geometry and won only because the gap went down. Choosing N by this sample alone overfits to two coin flips. What the sample *does* establish: the catastrophic case on record was a **day-of** sale, and day-of is where earnings IV makes the trade most attractive to the scorer (see §2 AMZN).

**Input to DD-3's binding acceptance criterion** (both incidents on record must be blocked): this trace pins the AAPL incident precisely. The only pre-earnings AAPL call of the 7/27 week was **C347.5, filled Thursday 7/30 15:15 ET — `days_until = 0`**, not the feared Monday `days_until = 3` geometry. With the GOOGL put incident at `days_until = 1` (4/28 vs 4/29), **N=1 already satisfies the binding criterion**. The criterion is therefore weaker than the plan assumed; it cannot by itself justify any N above 1, and the N decision reduces to risk appetite on span exposure (below).

---

## 4. Roller feasibility

### 4a. As-built (assume FC-066's quote-key bugs fixed) — can it rescue these positions? **No.**

Walking each open call through the roller's real constraints (`call_roller.py`, `settings.yaml` `rolling.*`, `risk_manager.validate_roll`):

| Constraint | AMZN C262.5 8/07 | GOOGL C370 8/07 | AAPL C312.5 8/05 | NVDA C220 8/10 |
|---|---|---|---|---|
| Friday-only cadence (next: 8/07) | seen 8/07 | seen 8/07 | **never seen** — expires Wed 8/05 | skipped |
| `max_current_dte: 1` | DTE 0 ✓ | DTE 0 ✓ | n/a | DTE 3 ✗ |
| ITM ratio ≥ 0.98 | 1.088 ✓ | 1.011 ✓ (if holds) | n/a | 0.94 ✗ (OTM — no roll wanted) |
| Max rolls (wheel-state count, never persisted → always 0) | ✓ | ✓ | | |
| Earnings blackout 2d | ✓ (10/29 far) | ✓ | | |
| Floor → min_strike | max(261.20, 262.51) | max(368.34, 370.01) | | |
| `validate_roll` delta band [0.15, 0.25] | forces new strike ~$300–305 | forces new strike ~$390+ | | |
| `validate_roll` DTE ≤ 7 | next Friday only | next Friday only | | |
| Debit tolerance | **FAIL** | **FAIL** | | |

The debit tolerance is the structural wall, three layers deep:

1. **Dead wheel-state premium:** `original_premium` comes from `wheel_state.get_active_call_details` — never persisted (`STATE_STORAGE_BUCKET` unset, FC-039/FC-066 cause 3) → resolves 0 → `debit_pct_of_premium = 999` → **every debit roll rejected; the roller is credit-only in practice.**
2. **Even with real premium:** the cap is 25% of collected premium — $0.55 for AMZN, $0.37 for GOOGL. A deep-ITM buy-back costs *intrinsic*: ~$23/sh for AMZN. The gap between cap and need is ~40x.
3. **Even the notional backstop** (0.5% → $131 AMZN / $185 GOOGL) is an order of magnitude below the ~$1,600–2,200 an AMZN-style roll actually costs — and it is an AND-gate with the premium cap anyway.

And the delta band compounds it: `validate_roll` reuses the **entry** band [0.15, 0.25], so the only permitted replacement strikes are far-OTM cheap ones (a 0.2Δ next-week AMZN call pays ~$1.50–2.50 vs a $23 buy-back) — the band *maximizes* the debit precisely when the position most needs a near-the-money rescue roll. A credit roll satisfying [0.15–0.25]Δ, ≤7 DTE, strike > current, for a call that is already ITM essentially cannot exist.

**Verdict: the as-built roller can never rescue an earnings-pop position — not because of the quote-key bug, but by construction.** Its economics (debit ≤ 25% of a ~$2 premium) describe a *strike-optimizer for near-the-money calls drifting slightly ITM in the last day*, not an assignment-rescue tool. Fixing FC-066's cause 1 (the `last_price`/`ask_price` and `ask_price`-vs-`ask` key bugs at `call_roller.py:127` and `:219`) would merely let it evaluate AMZN on Friday and log `no_candidate_passed_economics`. Separately, the Friday cadence is blind to AAPL-style Wednesday expiries (52% of this book's call expiries are mid-week, per FC-066).

### 4b. Idealized roll economics — live quotes, 2026-08-03 15:51 ET

Realistic BTC-at-ask / STO-at-bid pricing:

**AMZN (deep ITM — BTC C262.5 8/07 @ $23.93 ask):**

| Target | STO bid | Net debit | Strike gained | If above target strike at expiry | Breakeven vs call-away |
|---|---|---|---|---|---|
| 8/14 C285 | 7.32 | **$1,661** | +22.50 | +$589 better | AMZN ≥ 279.11 at 8/14 |
| 8/21 C290 | 6.48 | **$1,745** | +27.50 | +$1,005 better | ≥ 279.95 at 8/21 |
| 9/18 C290 | 11.66 | **$1,227** | +27.50 | +$1,523 better | ≥ 274.77 at 9/18 |

Every AMZN roll is a four-figure debit — you pay the market back most of the surrendered upside *in cash today* to keep a *contingent* claim on it. Below the breakevens (a ~2% retrace), the roll is strictly worse than taking the call-away. This is a leveraged directional bet that the pop holds, financed out of banked premium — exactly the trade the wheel exists to not make. The clean alternative: take assignment Friday (+$352 realized), and re-enter via CSP at ~0.15Δ (~$270 strike, ~$2/wk premium). **Rolling deep ITM does not "rescue" upside; it repurchases it at fair price.**

**GOOGL (shallow ITM, fat time value — BTC C370 8/07 @ $8.87 ask):**

| Target | STO bid | Net debit | Strike gained | If above target at expiry |
|---|---|---|---|---|
| 8/14 C375 | 8.31 | $56 | +5.00 | +$444 better |
| 8/21 C380 | 8.88 | **−$1 (credit)** | +10.00 | +$1,001 better |

GOOGL is the textbook rescuable position: shallow ITM with time value near intrinsic, so a two-week roll-up is available **at zero net cost**. The 8/21 C380 credit roll dominates holding to assignment in every terminal scenario (worst case: identical outcome +$1; best case: +$1,001 more strike room), at the cost of two extra weeks capped at 380 instead of recycling into a fresh position after Friday's call-away. A human trader does this today. Note both good GOOGL targets are ~0.35–0.48Δ and/or 14 DTE — **both illegal under `validate_roll`'s entry-band reuse and DTE ≤ 7**, and today is Monday, so the as-built Friday roller couldn't act until the quotes have moved anyway.

- Assignment-risk notes: AMZN pays no dividend and carries $0.85 TV — early exercise unlikely before 8/07; GOOGL's $4.60 TV makes early assignment a non-issue; only the 9/18 AMZN tenor would cross a GOOGL-style ex-div boundary (GOOGL's next ex-div ~early Sep is beyond the 8/14–8/21 targets; AMZN has none).
- AAPL and NVDA are OTM: no roll warranted. DTE-band profit-taking is already doing its job there (AAPL call +25% of premium at 2 DTE; band target 60% at DTE 2, so it rides for now).

---

## 5. Synthesis for the build (options, not decisions)

### What this episode says about the FC-013 N choice

- **The one catastrophic sale on record was day-of (`days_until = 0`), and both DD-3 incidents are `days_until ≤ 1`** — the binding acceptance criterion is satisfied by N=1 and cannot arbitrate higher N. §3's table shows N=1 capturing 100% of this window's benefit at minimum premium cost ($387 forgone), with every increment to N=7/SPAN forgoing another winning gap-down premium for zero incremental preservation *in this sample*.
- **But the structural argument for SPAN stands, and AMZN is its live demonstration:** any call whose expiry covers the report carries the full gap — GOOGL's 7/17 spanner had identical geometry and simply won the flip. For the uniform 7-DTE book, SPAN ≡ N=7 (the audit's convergence point, DD-3). The real question is price: SPAN costs roughly $580–970 per earnings season in forgone winning premium across this book (per §3, and the winners only *stay* winners while gap-downs outnumber gap-ups), against a demonstrated single-event tail of ~$1,500–2,100 net (re-arm-adjusted). One AMZN-scale gap-up every few seasons pays for permanent SPAN gating.
- **Day-of selling deserves special attention regardless of N:** earnings IV is what made the AMZN strike sellable at all (10.9% OTM clearing the premium floor at IV 0.68). The scorer is structurally attracted to the highest-risk day. Even the minimal gate kills this adverse selection.

**Options:** (a) N=1–2 — blocks both incidents and all day-of IV-bait, cheapest, accepts span exposure as premium-positive on gap-down luck; (b) N=7/SPAN — buys out the whole event window at ~$600–1,000/season; (c) SPAN on the call leg only where the *floor is binding* (underwater/at-floor lots have the least to gain from juiced premium and the most repair upside to lose) — more machinery, not currently in the plan. The operator picks; this episode's data alone cannot distinguish (a) from (b) — it takes a prior on gap-up frequency.

### Asymmetric windows (puts vs calls)

The plan gates both legs with one knob. The legs' exposures are mirror images but their *costs* are not:

- **Put-side block cost ≈ $0** (skip one entry; cash idles a week). Benefit: avoids assignment above a gapped-down market — a *realized capital loss* (the GOOGL 4/28 incident shape). Cheap insurance → a wide window (N=7/SPAN) is nearly free.
- **Call-side block cost is real premium** on shares you keep holding through the event anyway (~$100–250/symbol/week on this book — and specifically the *juiciest* premium of the cycle). Benefit: unrealized-upside preservation, not loss avoidance; the equity leg carries the gap-down either way (AAPL's lot lost ~$2,950 unrealized through its report, call or no call).
- **This argues for `put_blackout ≥ call_blackout` if they ever diverge** — e.g. SPAN/N=7 puts + N=1–3 calls. Counterargument, honestly: the only four-figure damage on record (AMZN) is call-side, and call-side is where the IV-bait selection pressure lives. If the operator weighs demonstrated damage over cost symmetry, the asymmetry flips to SPAN-on-calls. A single shared N (the plan's current shape) is defensible as the simplest thing that blocks both incidents; the asymmetric option should be a deliberate rejection, not an unconsidered one.

### FC-066 (roller revival) vs DTE-band profit-taking as the management tool

- **The DTE-band profit-taker is carrying the whole management load and doing it well on the winning side:** 27 of 27 completed call round-trips on these four lots since June were closed early at a profit (+$2,472 realized), zero call assignments since the lots were opened. But it has **no move for an ITM call** — no stop (disabled by FC-010, deliberately), no roll (dead) — so ITM calls ride to assignment. That is not obviously wrong: assignment above basis *is* the wheel working (AMZN Friday books +$352 and frees $26k of collateral).
- **The as-built roller cannot fill the gap even if revived per FC-066's fix direction** (§4a): its credit-only-in-practice economics, entry-delta-band reuse, DTE ≤ 7 cap, and Friday cadence make deep-ITM rescue structurally impossible and even shallow-ITM rescue (GOOGL today) illegal. Reviving it as-is buys a strike-optimizer for last-day near-the-money calls — the least valuable member of the family.
- **What the live book actually needed this week:** (1) nothing for AMZN — the honest roll costs $1,200–1,700 and is a directional bet; call-away + re-entry is the wheel's answer; (2) a **credit-only roll-up-and-out** for GOOGL (+$10 strike for $0) — which is *almost* what the as-built debit logic already enforces; the blockers are the delta band, the DTE cap, and the cadence, not the debit math. A minimal FC-066 that (i) fixes the quote keys, (ii) exempts defensive rolls from the entry delta band, (iii) allows ≤14 DTE targets, (iv) runs in the daily monitor cycle rather than Friday — and **keeps credit-only** — would have captured GOOGL's $1,000 of strike room this morning while remaining structurally unable to make the AMZN-style mistake of buying back a gap. That is a candidate scope worth pricing against simply letting FC-013 prevent the AMZN case and letting call-away handle the rest.
- Either way, **FC-013 and FC-066 are complements, not substitutes**: the gate prevents the unrescuable case (deep-ITM gap-through), the roller — if revived — monetizes the rescuable one (shallow ITM drift). The DTE-band config needs no change for any of this.

---

## Appendix: verification trail

- Live positions & marks: Alpaca paper account via `AlpacaClient.get_positions` / `get_stock_quote` (IEX) / `get_option_quote`, 2026-08-03 19:47–19:51 UTC. GET-only throughout; no orders placed or modified.
- Fills & assignments: `options_wheel.trades_from_activities` (activity types FILL/OPASN/OPTRD), queried 2026-08-03. Basis identity checked all four lots: `avg_entry_price = assigned_strike − assigning_put_premium` exactly.
- Sale-time candidates: GCS blobs `2026-07-30/14-00.json`, `2026-07-31/15-00.json`, `2026-08-03/16-00.json`, `2026-08-03/18-00.json` — each `status: executed, executed_count: 1`, matching the four BQ fills.
- Earnings dates: `fc-013/step0-audit` branch `src/backtesting/data/earnings_dates.json` (generated 2026-08-03): GOOGL 7/22, AAPL 7/30, AMZN 7/30, MSFT 7/29, NVDA 8/26. Gap sizes from Alpaca IEX daily bars (7/30 close → 7/31 open: AMZN +12.3%, AAPL −8.5%; 7/22 → 7/23 GOOGL −6.1%).
- Roller semantics: `src/strategy/call_roller.py` (quote-key defects at :127 `last_price`/`ask_price` vs client's `bid`/`ask`, and :219 `ask_price` vs client's `ask`; dead wheel-state premium at :214–215), `src/risk/risk_manager.py:122` `validate_roll`, `config/settings.yaml` `rolling.*` and `profit_taking.dte_bands`. FC-066 entry in `docs/FUTURE_CONSIDERATIONS.md`.
- Counterfactual semantics: `docs/plans/fc-013.md` DD-3 (calendar-day predicate, day-of blocked, SPAN ≡ N=7 for the 7-DTE book).
