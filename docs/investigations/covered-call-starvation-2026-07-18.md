# Covered-call starvation + roller autopsy — 2026-07-18

**Trigger:** AAPL (100 shares, basis $303.50, price ~$333.74, +$3,024 unrealized) had no covered call since 7/14 despite being deep in profit. Question asked: "why didn't we sell more calls?"

**Method:** code trace + production ground truth (Alpaca order history, GCS scan blobs, Cloud Logging, BigQuery), followed by an independent adversarial review that verified every claim and corrected two mechanisms. This doc is the durable record; FC-038/039/040 are the fixes.

---

## Headline findings

### F1. Covered calls are charged phantom cash collateral in execution selection (→ FC-038)

The production path is `/scan` → GCS blob (`gs://options-wheel-opportunities/opportunities/...`) → `/run` → `ExecutionEngine.rank_opportunities` → `select_batch` → `execute_batch`. In that path:

- `rank_opportunities` (execution_engine.py:140-187) runs **every** opportunity through `put_seller._calculate_position_size`, whose buying-power cap (`buying_power // (strike*100)`, put_seller.py:154) **silently drops calls** when BP < strike×100.
- `select_batch` (execution_engine.py:189-251) charges `collateral = strike × 100 × contracts` against the BP budget **for calls too**. Covered calls need $0 cash — shares are the cover.
- Ranking is `premium/collateral` — the scanner's `attractiveness_score` is ignored.

**Exact reproduction (Friday 2026-07-17 14:15 UTC run):** logged BP $67,142.50. Scan blob held 12 opportunities; AAPL calls were the top-scored (87.2) in the batch. Greedy selection: GOOGL 7/24 370C (best premium/strike ROI 0.0106) charged **$37,000 phantom** → $30,142.50 left → all three AAPL calls ($33,750–$34,000 phantom) dropped → IWM 289P ($28,900) selected → $1,242.50 left. Executed: GOOGL + IWM — matching the blob's `execution_results` and Alpaca fills byte-for-byte.

**Compounding wasted-slot bug:** after GOOGL's call filled, every subsequent `/run` cycle re-selected GOOGL (shares already committed), charged phantom BP, then failed `execute_batch`'s available-shares check ("0 available shares (100 owned - 100 committed)") — while AAPL was never selected. The share check runs only at execution time, after selection has spent the budget.

**Blast radius:** AAPL uncovered 7/15–7/18 (~$75–$190/day scanned premium foregone); fleet-wide, ~50–90 opportunities/day convert to 1–3 trades (the `executions.trades_failed` column is `found − executed`, not errors). On 7/14, runs with BP $621/$383 dropped every opportunity at the *sizing* stage — same defect, different door.

**Zero observability:** neither ranking-stage sizing drops nor selection-stage BP drops log anything per-opportunity. AAPL was dropped 20+ times over 4 days without one AAPL-specific log line.

### F2. The FC-006 roller has never executed a roll (→ FC-039)

Proven two ways: all `roll_cycle_completed` events in retention (6/19, 6/26, 7/3, 7/10, 7/17 — Fridays 15:30 ET) show `rolls_evaluated=1, rolls_executed=0`; and full Alpaca order history (459 orders) has no option order in any Friday roll window, ever.

Four stacked causes:

1. **Quote-key mismatch (fatal):** `call_roller.py:102` reads `last_price`/`ask_price`; `get_stock_quote` (alpaca_client.py:317-324) returns `bid`/`ask` → price 0 → unlogged `return None` **before any gate**. On 7/10 it evaluated exactly the user's AAPL 317.5C and silently skipped it. (`get_stock_quote` raises on failure, so the `if not quote` branch is also unreachable-as-intended.)
2. **Eligibility gap:** monitor profit-taking churn means the call open on any given Friday is 5–7 DTE — never ≤ `max_current_dte: 1`. Corrected mechanism per adversarial review: 48% of call sales DO expire on Fridays (a Friday-expiry ITM call at 15:30 would be eligible); it's the churn (buyback within days + immediate 7-DTE re-sell) that keeps Friday evaluations ineligible, plus 52% mid-week expiries that a Friday-only job can never see.
3. **State amnesia:** `STATE_STORAGE_BUCKET` unset on Cloud Run → `WheelStateManager` persistence is a no-op (no state blob exists in any bucket) → `original_premium` = 0 → `debit_pct_of_premium` = 999 → `_check_debit_tolerance` rejects any debit roll; `roll_count` never increments. Setting the bucket is **insufficient**: `/run` builds `CallSeller` with no wheel_state (cloud_run_server.py:381), so `set_active_call_details` never fires regardless. The stateless fix (read the opening STO's `filled_avg_price` from Alpaca) is strictly more robust.
4. The fatal skip path logs nothing.

What looked like a "GOOGL roll chain" (395C→380C→370C, 7/16–7/17) was monitor profit-taking + fresh `/run` sells (395C sold @4.10 → bought back same day @2.00 at the day-0 35% profit band; 380C sell expired unfilled; 370C fresh sell next morning). The 42210000 "contract not tradable" GOOGL rejections on 7/15–7/16 additionally burned selected slots for cycles in a row.

### F3. Observability defects that misled the investigation (→ FC-040)

- `trade_journal.record_trade` defaults `strategy→'sell_put'`, `option_type→'put'` (trade_journal.py:148,161); scanner call-opportunities lack those keys → **29 covered-call rows in `options_wheel.trades` are labeled as puts** (verified via OCC-symbol regex). This mislabeling sent the 07-17 session down the wrong path.
- The `options-wheel-logs` BQ sink died **2025-11-22** (newest export table `run_googleapis_com_stderr_20251122`); `errors_all` errors on the repeated-field schema conflict (`jsonPayload.symbols`). Use `gcloud logging read` (30-day retention) for anything after November.

### F4. Correction of the 2026-07-17 session's conclusion

The prior session blamed `RiskManager.validate_new_position`'s substring bug for blocking covered calls. The bug is real (risk_manager.py:57 — counts the stock position itself; `F` matches `PFE`) but **the method has zero call sites** — it is dead code everywhere, not just in the scheduled path. Production behavior is fully explained by F1. Recorded against FC-014.

## Adversarial review verdict (independent agent, full data access)

- C1–C3, C5–C8 CONFIRMED with evidence (code, blobs, logs, BQ, Alpaca); C4 conclusion confirmed, mechanism corrected (churn, not calendar).
- DIAGNOSIS-SOUND; SOLUTION-DIRECTION: REVISE. Required revisions (all folded into the FC entries / fc-038 plan): fix the sizing-stage BP gate too, not just select_batch; explicit call-ranking metric (naïve `collateral=0` makes `roi=0` and sorts calls last); reserve **shares** per underlying at selection time (also closes the wasted-slot bug); roller must not rely on `STATE_STORAGE_BUCKET` alone — derive premium from Alpaca order history; retain an expiry-day ~15:30 check (last monitor is 14:55 ET); sink restore must handle the repeated-field schema conflict; add selection-drop logging.

## Verified-working (for the record)

- Scanner call scan: cost-basis floor from `position['cost_basis']` correct here (AAPL 303.50); AAPL calls found and top-scored every scan. Deep-drawdown symbols (NVDA −7.1%, AMZN −5.3%) naturally excluded because no delta-range strike clears their basis — equivalent protection to the FC-029 R3 pause on this path.
- Monitor profit-taking works as configured (DTE-band targets; the churn is the de-facto roll substitute).
- Alpaca order history, scan blobs, and Cloud Logging mutually reconcile.
