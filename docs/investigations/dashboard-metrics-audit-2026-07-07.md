# Dashboard Metrics Audit — Methodology Review of Every Displayed Metric

**Author:** Claude
**Date:** 2026-07-07
**Trigger:** User request — "exhaustive review of the existing dashboard and the calculation methodologies for each shown metric… a fair amount of misleading stats (e.g. buy vs hold ignores capital efficiency and varying hold times), missing information (cost basis for long positions)."
**Scope:** every metric on the three dashboard pages (Overview, Symbol Deep Dive, Bot Health), full data-flow trace (frontend → backend → BigQuery views → ingest), plus external research on wheel-strategy metric best practices.
**Outcome:** feeds FC-031 (`docs/plans/fc-031.md`).

---

## 0. Method

- Traced every rendered metric to its computation site (frontend formula, backend SQL, or BQ view) with file:line references.
- Compared each against best-practice references: CBOE PUT/BXM index methodology (return on *full* collateral base, fully-collateralized), GIPS TWR/XIRR standards, Bailey & López de Prado on small-sample Sharpe, wheel-community cost-basis conventions.
- Verdicts: **KEEP** (correct as-is), **FIX** (calculation wrong), **RELABEL** (correct number, misleading presentation), **REMOVE** (vanity/dead), **ADD** (missing).

### The accounting model the dashboard should obey (from research)

One ledger, mark-to-market, matching the broker statement:

```
Total P&L(t)      = Realized P&L(t) + Unrealized P&L(t)
Realized P&L      = option cash (premium − buybacks) + share cash on disposal (raw basis)
Unrealized P&L    = shares held × (mark − RAW basis) + open option (premium − current mark)
Account equity(t) = cash + share MTM − short-option liability
```

**Convention A (broker truth):** option premium books as realized P&L when each leg closes; assigned shares carry **raw basis = strike × 100** (via actual OPTRD cash). **Convention B (breakeven view):** premiums reduce basis (ACB). Both give identical cycle totals; **mixing them double-counts premium**. The dashboard must use Convention A for all P&L aggregates and show ACB only as "effective breakeven" — a decision input, never a ledger input.

The FC-019 data layer already implements Convention A correctly (`realized_pnl` = option leg, `share_side_pnl` = OPTRD cash). The violations below are all places the *presentation layer* strays from it.

> **Erratum (post-adversarial-review, same day):** FC-019's `share_side_pnl` is a *cash ledger* (Σ all OPTRD net_amount, including the acquisition cost of shares still held), **not** disposal-based realized P&L as the model above implies. The correct MTM identity on this data is therefore `MTM P&L = net cash P&L + market value of held shares` — NOT `+ (mark − basis) × shares`, which double-subtracts basis. See `fc-031-adversarial-review-2026-07-07.md` F1/F2; the FC-031 plan uses the corrected convention.

---

## 1. Overview page

### 1.1 KPI tiles (`KPICards.tsx:41-124`)

| Metric | Today | Verdict |
|---|---|---|
| Net Liquidation Value | `account.portfolio_value` live from Alpaca | **KEEP** |
| Total Return | `NLV − Σ JNLC deposits` (bank-statement number) | **KEEP** (correct since FC-019) |
| Annualized return | `(NLV/deposits)^(365/daysRunning) − 1` (KPICards.tsx:81-85) | **FIX** — three defects: (a) single-deposit CAGR approximation, self-acknowledged in code comments; (b) `daysRunning` = days since first *trade* in the **range-filtered** scorecard, so the annualized figure changes with the 30d/90d/1Y range picker and ignores pre-trading idle capital; (c) no money-weighting of flows. Replace with backend-computed **XIRR** over dated JNLC flows + current NLV, and **TWR** for benchmark comparison. |
| Net Realized P&L | `SUM(realized_pnl)` over closed option events | **RELABEL** — correct number, but it is the *option-leg only*. Share-side realized cash (OPTRD) is excluded, so after a losing assignment cycle this tile overstates. Headline should be **Total P&L = realized (options + shares) + unrealized**, split visibly. Fees (−$24 lifetime) acceptable as noted residual. |
| Days Running | days since first trade in range-filtered scorecard | **FIX** — should be days since first deposit (JNLC), range-independent. |
| Footer "Account data refreshed just now" (Overview.tsx:163) | formats `new Date()` — always "just now" | **REMOVE** — fake freshness stamp. Wire to real fetch timestamps or drop. |

**Missing from headline (ADD):** Max drawdown of the equity curve (the one risk number that is meaningful at small sample size), and current-drawdown-from-peak. Explicitly **do not** add Sharpe/Sortino/beta: with ~9 months of negatively-skewed short-vol returns, estimation error swamps signal (Bailey & López de Prado PSR/MinTRL).

### 1.2 Equity curve (`EquityCurve.tsx`)

Raw NLV line. Deposits appear as fake "gains"; no benchmark; capped at 365d even on "All" (Overview.tsx:32). **FIX/ADD:** index to 100 using flow-adjusted sub-period returns (TWR chain), overlay benchmark (SPY price-return B&H on the same capital base, labeled "price-only, no dividends"), show max-DD band. Remove the 365d cap on "All".

### 1.3 Monthly Premium bars (`MonthlyPremiumBars.tsx`)

Sums **gross** premium by sale date. Heavy-roll months (AMZN cycle 1: 9 rolls) overstate income; buybacks never netted. Premium collected is *revenue*, not profit — the most common wheel vanity metric. **FIX:** switch to **net option cash flow by month** (premiums received − buyback costs, by event month), keep put/call split. Gross available in tooltip.

### 1.4 Per-symbol scorecard (`SymbolScorecard.tsx`, view `fc018_per_symbol_scorecard`)

| Column | Verdict |
|---|---|
| Gross Prem, Option P&L, Share P&L, Total P&L | **KEEP** — FC-019's reconciliation columns are the strongest part of the dashboard. |
| **Unreal** = `(price_now − current_acb_per_share) × shares` (SymbolScorecard.tsx:153) | **FIX — double-counts premium.** `current_acb_per_share` is the premium-adjusted basis; premium is already inside Option P&L. Summing Total P&L + this Unreal counts every net premium dollar on held shares twice. Must use **raw basis** (`running_share_cost / shares`). This is the "cost basis for long positions" gap the user flagged: the view doesn't even expose raw basis today. |
| ACB (shown only when holding) | **RELABEL** — keep, as "Breakeven/sh" (decision metric for call strike selection), never summed into P&L. Add distance-to-breakeven. |
| vs B&H (`wheel_minus_bh`) | **FIX** — see §1.5. |
| Footer "% of symbols beat B&H" (SymbolScorecard.tsx:177) | **FIX** — denominator counts symbols with NULL B&H (missing bars), deflating the beat rate. |
| `price_now` drives Unreal/stress/%-to-strike | **RELABEL** — it is the last daily-bar close, rendered next to 30s-polled live data. Stamp "as of {date}". |

### 1.5 Wheel vs Buy-and-Hold (`VsBuyAndHoldCard.tsx`, view `fc018_vs_buy_and_hold_per_symbol`)

The user's headline complaint, confirmed. Current: `wheel_minus_bh = total_realized_pnl − bh_dollar_pnl` where B&H = first-put collateral converted to shares at first-trade date, marked to `price_now`.

Defects, in order of severity:

1. **Asymmetric marking.** Wheel side is *realized-only*; B&H side is *fully marked-to-market*. A symbol currently holding recovered shares shows all of B&H's paper gain and none of the wheel's. (AMD mid-cycle looks maximally bad.) FIX: wheel side = `total_realized_pnl + unrealized on held shares at raw basis`.
2. **Capital-time ignored.** B&H deploys the full collateral for the entire window; the wheel had that capital deployed only during put/stock phases (phase-timing data exists and shows it). The per-symbol Δ$ therefore embeds a hidden "and the cash earned nothing while idle" assumption, *and* simultaneously lets the same dollar count in several symbols' B&H baselines (the account could never hold all 7 B&H positions at once — confirmed in `strategy-review-2026-05-07.md` §1.2.3). FIX: label per-symbol B&H as a *perfect-foresight reference*, and add a **capital-normalized** comparison: `wheel P&L per $·day deployed` vs `B&H P&L per $·day` (denominator from phase-timing collateral-days). ADD account-level benchmark: indexed TWR curve vs SPY B&H of the same starting equity — the only comparison with an honest denominator.
3. **Dividends** excluded (disclosed in tooltip) — understates B&H for dividend payers (UNH). Acceptable if labeled; note in methodology.
4. `price_at_start` NULL if first trade fell on a non-trading day (`ANY_VALUE(IF(date = first_trade_date…))`) — silent NULL propagates to card's "backfill not complete" message. FIX: use first bar ≥ first_trade_date.
5. Readiness gate uses truthiness — `price_at_start === 0` would show "backfill not complete" (VsBuyAndHoldCard.tsx:22-24). Cosmetic FIX.

### 1.6 Stress row (Overview.tsx:65-91)

`Σ (current − strike) × 100` across ITM short puts. Direction correct; uses stale `price_now`; silently skips puts whose underlying is missing from the scorecard. **KEEP + RELABEL** (stamp price date; count skipped). ADD alongside it the two state metrics that are robust at any sample size: **notional-if-assigned / equity** (leverage; >1.0 = over-sold puts) and **capital deployed %**.

### 1.7 Open positions / ActionPanel (`ActionPanel.tsx`)

| Item | Verdict |
|---|---|
| DTE anchored at `16:00Z` = noon ET (ActionPanel.tsx:31-33) | **FIX** → 4pm ET (21:00Z / 20:00Z DST; compute in ET). |
| % to Strike = `abs(strike − px)/px` (ActionPanel.tsx:38-41) | **FIX** — absolute value hides ITM vs OTM; a put 4% ITM and 4% OTM read identically. Sign it (negative = ITM). |
| % Captured on **stock rows** | **FIX** — formula `(|cost_basis| − |market_value|)/|cost_basis|` is a short-option formula; on long stock it renders nonsense. Show basis + unrealized for stock rows instead. |
| Unrealized % = `upl / |market_value|` (ActionPanel.tsx:119) | **FIX** — denominator is *current* market value: a short option decayed to $10 with $90 gain shows +900%. Use entry credit/cost. |

### 1.8 Dead/vanity fields

`MetricsSummary.win_rate` and `return_30d` are **hardcoded `None`** in the backend (`bigquery.py:363,365`) and never rendered; the router docstring promises win rate. **REMOVE the dead fields** and replace with the *correct* version: **per-cycle win rate + expectancy** (see §2.3) — per-contract win rate is a delta artifact (selling 10–20Δ puts mechanically wins 80–90% of contracts while one bad cycle erases twenty winners) and must not come back as a headline.

---

## 2. Symbol Deep Dive page

### 2.1 Header tiles + mixed windows

Tiles are server-supplied and correct. **FIX (consistency):** widgets on one page use different hardcoded windows (ACB/cycles/phase 730d; decision-quality/scorecard 365d) — unify.

### 2.2 ACB walk (`AcbWalkChart.tsx`, view `fc018_acb_timeline_per_symbol`)

Formula `(running_share_cost − cumulative_net_premium)/shares` is the standard community ACB. **KEEP**, with two caveats surfaced: (a) ACB is inception-cumulative, not cycle-isolated (documented in view, FC-024); (b) `connectNulls` bridges cash phases visually implying an ACB while holding nothing — style fix. Label the line "effective breakeven".

### 2.3 Cycle table (`CycleTable.tsx`)

- Cycle P&L = premium + capital_gain (FC-027) — **KEEP**, this is the honest cycle number.
- **Return** column: **FIX** — two definitions share one column (client formula with server `total_return` fallback); simple-period return on put-strike notional, not comparable across 7-day and 77-day cycles — precisely the "varying hold times" complaint. Replace with **RoC on collateral** plus **$/day per $ collateral** (`cycle P&L / days / collateral`) — the correct hold-time normalization. **Do not annualize single cycles** (a 7-day cycle "annualizes" ×52 into fiction).
- Known residual: per-cycle pairing breaks on overlapping share lots (AMD) — already filed as **FC-020**, out of scope here but the table should badge affected rows if cheap.

### 2.4 Decision quality (`DecisionQuality.tsx`)

Capture-ratio histogram + FC-026 dollar tiles are honest (Foregone = buybacks, explicitly not counterfactual — that's FC-017). **KEEP.** Minor: avg capture is trade-weighted equal (a $5 trade = a $500 trade) — the dollar-weighted "Captured %" tile already covers the right version; note in tooltip. Backend counts assignment/expiration as capture=1.0 — correct for the option leg; tooltip should say so.

### 2.5 Trade log / Phase timing

**KEEP.** Phase timing is the raw material for capital-efficiency math (§1.5.2) — currently display-only.

---

## 3. Bot Health page — the bigger gap

What exists: gate-hits heatmap (14d), error list (7d), daily scan/execution table, ingest freshness (26h hardcoded). What's missing, per SRE/algo-telemetry practice:

1. **Decision funnel** — the single most diagnostic bot view: `symbols scanned → S1 price/volume → S2 gap risk → S4 execution gap → S5 wheel state → S6 dedup → S7/S8 option criteria → S8 sizing → orders placed → filled`, counts per stage with trailing baseline. All stages already log to `options_wheel.scans` (stages 1–9); nothing renders the funnel shape. A funnel-shape break is how config bugs, dead data feeds, and regime changes announce themselves.
2. **Anomaly flags** — none exist. Minimum set: (a) any gate blocking 100% of candidates for N consecutive trading days; (b) zero orders placed for N days while scans ran (silent failure — this exact failure mode already occurred: FC-006 roll engine fired 0 times for weeks before anyone noticed); (c) zero scans on a trading day (scheduler failure); (d) ingest staleness (exists, threshold should match each job's cadence, not one 26h constant).
3. **Run reliability** — scheduled-run success rate over trailing 30d vs an explicit target, not just a table of raw counts.
4. **Drawdown-pause observability (= FC-030)** — R3 pause is a silent `return None` + log event; AMZN sat paused 62 days. The event lands only in the log-sink dataset the dashboard doesn't read. However the *state* is derivable from data the dashboard already has: `shares > 0 AND price_now < (1 − threshold) × raw_basis`. Surface: paused symbols, days paused (consecutive closes below threshold from `stock_history_from_alpaca`), estimated foregone premium optional.
5. **Reconciliation banner** — the accounting invariant `Σ per-symbol Total P&L + unrealized + fees ≈ NLV − deposits` is checked by hand in investigation docs every time (AMD's $1.6k anomaly was found manually). It should be computed on every Overview load; residual above a threshold = yellow banner. This is the trading equivalent of an SRE golden signal.
6. **Gate coverage gaps (bot-side, for the record):** `RiskManager.validate_new_position` block reasons are returned as strings, never structured-logged (FC-014's problem); earnings blackout is only wired into call rolls (FC-013 still draft — the 2026-05-07 review's "done" claim was stale); `options_wheel.call_rolls` is queried by the backend but only defined in the legacy `options_wheel_logs` dataset in committed SQL — silently returns `[]` on failure.

Client-side nits: BotHealth `slice(0,7)` / `slice(0,20)` assume newest-first API ordering; error list unsorted client-side.

---

## 4. Cross-cutting

- **Hardcoded constants:** "All" range = 3650d; ingest staleness 26h; DTE anchor 16:00Z; project ID / bot URL fallbacks; `paper_trading` default `true` in SymbolDeepDive but `false` in LayoutV2.
- **positionState heuristic** (`positionState.ts:12-18`): any open option + shares ⇒ "Long + Short Call"; any open option without shares ⇒ "Short Put". Mixed states mislabeled. Scorecard view needs open-put/open-call counts split.
- **Error masking:** most backend BQ methods swallow exceptions → `[]`; an absent view is indistinguishable from "no trades". Bot-health should distinguish.
- **Legacy metrics endpoints** (`/api/metrics/pnl-by-symbol` options-leg-only; `summary` gross-premium emphasis) have no v2 consumers and contradict the reconciled numbers — deprecate/remove to reduce misleading surface.

## 5. Research summary — what a disciplined wheel dashboard headlines

(Full sources in FC-031 plan. Key: CBOE PUT-index methodology, GIPS TWR guidance, Kitces TWR-vs-IRR, Bailey & López de Prado PSR, IBKR realized/unrealized conventions, wheel-community cost-basis references.)

- **Headline 4:** Total P&L (realized + unrealized, split), TWR vs benchmark, XIRR, Max drawdown.
- **Wheel-specific tier 2:** RoC on capital-at-risk (CSP: `strike×100 − premium`; CC: raw share basis), **P&L per day per $ deployed** (the hold-time normalizer), per-cycle win rate + expectancy, assignment rate (calibration dial ≈ |put delta|), effective breakeven per open lot.
- **Banned:** premium-collected-as-income headline, annualized single-trade/cycle returns, per-contract win rate as KPI, Sharpe/Sortino/beta on <1y of skewed short-vol returns, ACB summed with realized premium (double-count), deployed-capital RoC presented as account return.
- **Benchmarking:** indexed equity curves on the same capital base (account TWR vs B&H vs strategy-class index); per-symbol B&H kept only as a labeled perfect-foresight reference.
- **Bot health:** decision funnel with baseline, gate hit-rates with anomaly flags, run-success SLO, reconciliation check as a first-class signal.
