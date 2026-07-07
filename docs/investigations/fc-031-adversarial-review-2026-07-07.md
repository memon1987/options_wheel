# FC-031 Adversarial Review — Portfolio-Manager / Quant Attack (pre-implementation)

**Reviewer:** Claude (independent skeptical-PM persona, adversarial pass)
**Date:** 2026-07-07
**Subject:** `docs/plans/fc-031.md` (draft as of 2026-07-07, pre-revision)
**Disposition:** all 7 blockers and the strongly-recommended items were incorporated into the revised plan (see plan §"Adversarial review disposition"). This file preserves the full review verbatim for the record.

---

## CRITICAL findings

### F1 — CRITICAL: `wheel_mtm_pnl` double-subtracts the cost of held shares.

Plan proposed `wheel_mtm_pnl = total_realized_pnl + (price_now − raw_basis_per_share) × current_shares`. But `total_realized_pnl` = option `realized_pnl` + `share_side_pnl`, where `share_side_pnl = SUM(net_amount)` over **all** OPTRD events — *including the cash paid out to acquire shares still held*. It is a cash ledger, not a disposal-based realized P&L. Adding `(price − basis) × shares` subtracts the basis a second time.

Worked example: sell put for $100, assigned 100 sh @ $50 (OPTRD −$5,000), price now $55. Correct MTM = 100 − 5,000 + (100 × 55) = **+$600**. Plan formula = −$4,400 — off by exactly the basis. On AMD the error is ≈ $24,250 on one symbol. Cascades into vs-B&H, the reconciliation residual (permanently above threshold), the Total P&L tile, and the (tautological) verification invariant.

**Fix (adopted):** Option A — unrealized add-back for held shares is **full market value** (`price × shares`, or live position MV), because cost is already expensed in `share_side_pnl`. Relabel `total_realized_pnl` as **net cash P&L**. Option B (disposal-based realized) requires the FC-020 FIFO pairing the plan excludes.

### F2 — CRITICAL: `raw_basis_per_share` = `running_share_cost / running_shares` is inception-cumulative and polluted by prior closed cycles' residuals.

The view's own comment says residual losses from prior cycles carry forward. AMD: computes $242.50/sh while the actual open lot was bought at $245.00. Neither tax-lot basis nor broker basis. Also `running_share_cost` (OPASN↔OPTRD ±120s pairing with strike fallback) ≠ −Σ OPTRD in general.

**Fix (adopted):** open-lot basis needs a FIFO walk over OPTRD events (a small, display-only subset of FC-020's designed algorithm). Never present the cumulative ratio as "basis"; never use it in P&L sums or pause logic.

### F3 — CRITICAL: campaign expectancy computed from FC-020-mis-paired cycle rows, with open (losing) cycles excluded, is a fabricated number.

AMD's mis-paired rows (phantom −$20,500 loss + phantom +$750 win from one termination event) both enter the "closed" population; with ~11 wheel cycles ever, one garbage row IS the avg-loss statistic. Open cycles are excluded while losing cycles stay open longest by construction (drawdown pause guarantees it — AMZN 62d, AMD's real lot open ~157d).

**Fix (adopted):** exclude symbols with overlapping-lot history from cycle stats and disclose ("N cycles; M excluded pending FC-020"); always show open campaigns count + current MTM beside closed stats; no expectancy from mis-paired rows.

## HIGH findings

### F4 — HIGH: the campaign union re-imports the banned per-contract win rate through the back door.
~85% of the union is single-put trades, so "campaign win rate" ≈ 1 − |delta| — the banned delta artifact renamed. **Fix (adopted):** report wheel-cycle win rate and unassigned-put win rate as two separate stats with population counts in the label.

### F5 — HIGH: assignment rate denominator must not include early closes.
A put bought back at 50% capture never faced the expiry lottery. `assignments/(assignments+expirations+early_closes)` can read 17% (looks calibrated to delta) when the held-to-expiry rate is 48% (systematic adverse selection). **Fix (adopted):** calibration stat = `assignments / (assignments + expirations)`; "% closed early" shown separately.

### F6 — HIGH: reconciliation banner cries wolf; `known_gaps` as a hardcoded constant is a rot-and-gaming vector.
Open short-option premium float routinely exceeds a $300 threshold → permanent yellow → dead signal. **Fix (adopted):** residual formula includes open-option premium (cash on opens) and live position MV (marks); `known_gaps` entries carry as_of/reason and the payload reports live share-count mismatches so a *new* anomaly is distinguishable from the known one; threshold reviewed after a week of residuals.

### F7 — HIGH: anomaly detector's trading-day calendar was circular (derived from the scheduler's own events) — blind to total scheduler failure, the FC-006 failure mode re-implemented.
**Fix (adopted):** calendar from SPY bars in `stock_history_from_alpaca` (independent ingest path); self-derived calendar only as labeled fallback.

### F8 — HIGH: drawdown-pause card measured a different quantity than the bot (wrong reference price, env-var threshold drift, phantom AMD shares, inferred-state vs events).
**Fix (adopted):** reference = latest OPASN assignment strike; intersect with live Alpaca share counts (mismatch → anomaly badge, not a pause row); pause window bounded at acquisition date; threshold read from the bot's live `/config` proxy with labeled fallback; card labeled "inferred from prices — not bot telemetry."

## MEDIUM findings

- **F9:** with one deposit ever, XIRR ≡ the retired CAGR. Total Return/Total P&L keeps the tile; XIRR is the sub-line labeled "single deposit: equals annualized since inception." (Adopted.)
- **F10:** TWR edge rules pinned: flows attach to next equity observation; live NLV *replaces* a same-date equity row; stale-terminal labeling propagates to the DD tile; report **dollar** max drawdown (flow-adjusted) alongside the % (close-to-close labeled). (Adopted.)
- **F11:** `$/day per $1k` needs `GREATEST(duration_days, 1)`; per-row only — any aggregate must be `Σ P&L / Σ collateral-dollar-days`; collateral documented as put-strike-notional approximation. (Adopted.)
- **F12:** NULL propagation for zero-share symbols — explicit `IF(current_shares > 0, …, 0)` in SQL spec; `price_now_date` stamp on the vs-B&H card too. (Adopted.)
- **F13:** "open option marks are small at ≤7 DTE" is false in the known worst case (rolled-down ITM calls). Include marks from live positions per symbol when available; quantify the exclusion otherwise. (Adopted.)
- **F14:** benchmark biased toward the wheel twice — SPY dividends (~$900–1,000/9mo omitted) and 0% idle cash (live would earn T-bills, ~$1,500+). Footnotes quantify both. (Adopted as captions.)
- **F15:** the verification "invariant" was a tautology (residual defined by the same equation). Replaced with a falsifiable check: `|residual − known gaps − fees|` within threshold. (Adopted.)
- **F16:** capital-deployed % — numerator/denominator mark treatment stated in tooltip; share-count mismatch badge; acknowledge Alpaca BP as the broker's competing number. (Adopted.)

## LOW findings

- **F17:** remove the contradictory legacy `/api/metrics/pnl-by-symbol` endpoint (options-leg only, no v2 consumers). (Adopted.)
- **F18:** `price_at_start_date` exposed and flagged when it trails `first_trade_date` by more than a few days. (Adopted.)
- **F19:** FC-029/030/031 numbering in strategy-review §5 conflicts with the FC ledger; ledger wins, note added. (Adopted.)
- **F20:** `open_put_count`/`open_call_count` inherit activities-ingest lag; tooltip. (Adopted.)

## PM-demanded omissions

1. **FC-029 before/after regime split** on cycle/put stats (deploy date 2026-05-08) — adopted; answers the live strategy question.
2. **Concentration / limit compliance** — per-symbol exposure vs equity with config limit flag — adopted (deployment strip).
3. **Delta-equivalent exposure** — needs entry-delta join from `scans`; deferred to a follow-up FC (noted in plan non-goals with reason).
4. **Fee-readiness** — FEE activity ingested and carried as a first-class reconciliation component — adopted (tiny ingest extension).
5. **Dollar max drawdown** — adopted (see F10).

## Verdict

Blockers F1, F2, F3, F6, F7, F8, F15 must land before execution; strongly recommended F4, F5, F9, F11, F12, F13, F14 + omission #1. The plan's instincts (fewer metrics, one convention, auditability) are right; the defect was reusing FC-019's *cash* columns as if they were *disposal-based realized P&L*. All incorporated in the revised plan.
