# Future Considerations

A running list of things we want to **research and write a plan for** before coding. This file is a **precursor to todos**, not a todo list itself. Entries here are ideas and open questions — they become actionable only after a plan file is published in `docs/plans/`.

## Lifecycle

```
1. Consideration  →  added here, loosely scoped, questions open
2. Research        →  investigation, data gathering, comments, alternatives
3. Plan published  →  a file in docs/plans/<slug>.md with the agreed approach
4. Execution       →  code changes are made against the plan
5. Archived        →  moved to "Completed" below with a link to the plan + PR
```

**Rule of thumb:** nothing graduates from this file into code until step 3 is done. See `docs/CLAUDE.md` ("Plan-First Development") for the enforcement rule.

---

## Entry template

Copy this when adding a new consideration. Keep it short — detail belongs in the eventual plan file, not here.

```markdown
### FC-NNN: <short title>

**Status:** Consideration | Researching | Plan drafted | Plan published | Executing | Done
**Size estimate:** S | M | L  (M/L require a plan file before code changes)
**Owner:** <who is thinking about this>
**Plan file:** `docs/plans/<slug>.md` (once published)

**Problem / opportunity:** 1–3 sentences on what prompted this.

**Open questions:**
- ...
- ...

**Links:** related evals (`PERFORMANCE_EVAL_CATALOG.md#EVAL-XXX`), issues, PRs, logs.
```

---

## Active Considerations

### FC-001: Symbol universe optimization

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** 8 of 14 configured symbols have never traded (AAPL, MSFT, QQQ, SPY, F, PFE, KMI, VZ). They burn ~6k API calls/month and slow scans. Before removing them or adding replacements, we need a plan covering rollout, monitoring, and reversion.

**Open questions:**
- Remove the 8 dead-weight symbols in one change or stage it?
- Which replacement candidates (META, TSLA, COIN, PLTR) clear our filters in a backtest?
- Do we raise `max_stock_price` from $400 to bring MSFT/QQQ/SPY into range, or leave them out?
- How do we validate the change hasn't reduced premium throughput?

**Links:** `PERFORMANCE_EVAL_CATALOG.md` EVAL-010.

---

### FC-002: AMD gap-risk filter re-tuning

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** AMD is our top premium generator but is gap-filtered on 47% of scans (262 of 553). Filter thresholds may be over-conservative for this symbol. A plan needs to weigh actual realized overnight gaps against the threshold and consider per-symbol tuning vs. a global change.

**Open questions:**
- What's the distribution of AMD's actual overnight gaps vs the current filter?
- Do we support per-symbol gap thresholds, or keep one global?
- How do we avoid over-fitting to AMD's recent history?

**Links:** `PERFORMANCE_EVAL_CATALOG.md` EVAL-010, `docs/AMD_GAP_RISK_ANALYSIS_2025.md`.

---

### FC-003: DTE target optimization (7 → 2–3?)

**Status:** Consideration
**Size estimate:** L
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** Current 7 DTE target may be suboptimal. Shorter DTE has higher per-trade ROI but potentially higher assignment risk. A change here touches strategy config, risk thresholds, profit-target DTE bands, and scan cadence.

**Open questions:**
- Does 2–3 DTE net ROI (after assignment losses) actually beat 7 DTE?
- Do profit-target bands need to be re-tuned for the new DTE?
- Do we ramp via A/B (some symbols at 3 DTE, others at 7) or flip the whole universe?

**Links:** `PERFORMANCE_EVAL_CATALOG.md` EVAL-004, EVAL-002.

---

### FC-004: Autonomous eval-driven parameter tuning

**Status:** Consideration
**Size estimate:** L
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** `PERFORMANCE_EVAL_CATALOG.md` describes a scheduled runner + results storage + threshold checker + config proposer + human-in-the-loop gate. This is a multi-component build that needs a plan before any code lands.

**Open questions:**
- What's the minimum viable first eval to automate (EVAL-011 share-commitment verification is the highest-safety candidate)?
- Where does the scheduled runner live (Cloud Scheduler + Cloud Run job, or inline with the strategy?)
- What schema for the `eval_results` audit table?
- What are the hard per-parameter safety bounds?

**Links:** `PERFORMANCE_EVAL_CATALOG.md` "Future Automation Architecture" section.

---

### FC-005: Per-symbol strategy parameters

**Status:** Consideration
**Size estimate:** L
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** Low-priced symbols (F, PFE, KMI, VZ) fail the global `min_put_premium` because their option premiums are structurally smaller. Either remove them or support per-symbol DTE/premium overrides. Touches config schema, filter code, docs, tests.

**Open questions:**
- Do we actually want these low-priced symbols, or is it simpler to drop them (see FC-001)?
- Config shape: per-symbol overrides map, or a tier system?
- How does this interact with the gap-risk controls (FC-002)?

**Links:** `PERFORMANCE_EVAL_CATALOG.md` EVAL-007, EVAL-010.

---

### FC-009: Duplicate early_close_executed (revised 2026-04-24 post-FC-012)

**Status:** Consideration (scope clarified, not narrowed)
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Original problem:** The bot logs `early_close_executed` multiple times (4-10 duplicates) for the same position when the close order doesn't fill quickly. The `_closed_today` dedup set in `cloud_run_server.py` is in-memory and resets on Cloud Run cold starts. Each monitor invocation on a fresh instance re-evaluates the position, finds it still meets the close criteria, and places another close order.

**What FC-012 changed:** the dashboard no longer reads from the structlog-sourced `options_wheel.trades` table. Dashboard counts are from `trades_with_outcomes` (Alpaca FILLs, deduped on `activity_id`). So duplicate log entries no longer corrupt dashboard numbers. **But the bug is about duplicate *orders*, not logs — the dashboard migration doesn't fix the underlying mechanism.**

**What FC-010 did NOT change:** FC-010 only disabled the call **stop-loss** branch. Call profit-target early-closes and put profit-target early-closes still flow through the same shared code path (`deploy/cloud_run_server.py:694-776`) with the same in-memory dedup. FC-010 reduced the *frequency* of vulnerable events but not the *mechanism*.

**Paths currently exposed to the bug:**
- Put profit-target early-closes (never touched by prior fixes)
- Call profit-target early-closes (stop-loss portion was silenced by FC-010, profit-target portion unchanged)

**Why duplicate orders can actually happen:**
1. Monitor fires → `should_close_*_early()` returns True → check `_closed_today` (empty on cold start) → place buy-to-close order → add symbol to `_closed_today`.
2. Before the order fills, Cloud Run scales to zero.
3. Next monitor fires on a new instance → `_closed_today` is empty again → position still exists at Alpaca (short option) → `should_close_*_early()` still returns True (position still meets profit-target threshold based on mark) → second close order placed.
4. Both orders sit in Alpaca's queue. Depending on timing, one or both may fill.

**Remaining work:**
1. **Verify** via BQ query against `trades_from_activities`:
   ```sql
   SELECT symbol, COUNT(*) AS close_fills, COUNT(DISTINCT order_id) AS close_orders
   FROM `options_wheel.trades_from_activities`
   WHERE side = 'buy_to_close'
     AND transaction_time >= '2026-04-01'
   GROUP BY symbol
   HAVING COUNT(DISTINCT order_id) > 1
   ```
   If the query returns rows where `close_orders > 1` on the same symbol on the same day → real duplicate orders confirmed.
2. **Fix** the dedup so it survives cold starts. Two viable options:
   - Persist `_closed_today` to GCS alongside the existing wheel state.
   - Before placing a close order, check Alpaca for open buy-to-close orders on the same option symbol. Skip if one is already pending.

The second option is more robust — it handles the "Cloud Run instance crashed mid-cycle" case that even GCS persistence wouldn't catch cleanly. Small M-sized change.

**Links:** FC-010, FC-012. Relevant code: `deploy/cloud_run_server.py:694-776`, `src/strategy/put_seller.py:523` (`should_close_put_early`), `src/strategy/call_seller.py:536` (`should_close_call_early`).

---

### FC-013: Gate health audit & earnings blackout symmetry

**Status:** Plan published
**Size estimate:** M
**Owner:** Claude
**Plan file:** `docs/plans/fc-013.md`

**Problem / opportunity:** A GOOG put executed 2026-04-28 the day before Google's 2026-04-29 earnings. The FC-007 `EarningsCalendarService` exists and works, but is only wired into `CallRoller.should_roll()` — never into `PutSeller.find_put_opportunity()` or `CallSeller.evaluate_covered_call_opportunity()`. The FC-007 execution note acknowledged this deferral. A holistic gate audit also surfaced that `config.earnings_blackout_days`, `config.earnings_avoidance_days`, and `RiskManager.validate_new_position()` are all defined but never read/invoked. FC-013 wires earnings into both sellers, flips fail-open → fail-closed, removes the dead `earnings_avoidance_days` knob, and publishes `docs/gates.md` as a single source of truth for all gates.

**Open questions:** see plan file.

**Links:** FC-006, FC-007, `docs/CLAUDE.md` Wheel Strategy Symmetry Principle. Sibling FCs spun off from the audit: FC-014, FC-015, FC-016.

---

### FC-014: Wire RiskManager.validate_new_position() into sellers (or retire it)

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** `RiskManager.validate_new_position()` (risk_manager.py:23) is defined but **never invoked**. It contains portfolio-level checks — max total positions, max positions per stock, max exposure per ticker, min cash reserve, portfolio allocation — that today are partially duplicated in `wheel_engine._can_open_new_positions` and partially absent. Only `validate_roll()` is wired (from `CallRoller`). Either consolidate the put/call seller paths through `validate_new_position` (and dedupe the engine-level checks) or formally retire the method and document where each portfolio-level check actually lives.

**Open questions:**
- Consolidate (route puts/calls through `validate_new_position`) or retire (delete the method, ensure engine-level checks cover everything)?
- If consolidating, do the engine-level early checks stay as a fast-fail before scanning, with the seller-level call as the authoritative gate?
- Are `max_exposure_per_ticker` and `min_cash_reserve` actually checked anywhere today, or are they silently disabled?

**Links:** FC-013 Phase-1 audit, `risk_manager.py:23-120`, `wheel_engine.py:220-249`.

---

### FC-015: Centralize hold-period state in WheelStateManager (cold-start safe)

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** Both `PutSeller._entry_times` (put_seller.py:30) and `CallSeller._entry_times` (call_seller.py:32) are local in-memory dicts that do not survive Cloud Run cold starts. The `profit_taking_min_hold_hours` gate inside `should_close_*_early()` silently fails open when the dict is empty (no `entry_time` → loop falls through). This is the same class of bug as FC-009 (the `_closed_today` cold-start dedup issue). Persist `_entry_times` to GCS alongside the existing wheel state so the hold-period gate enforces correctly across cold starts and parallel cycles.

**Open questions:**
- Persist to GCS (existing `WheelStateManager` GCS layer) or query Alpaca for fill timestamps?
- Should this share infrastructure with FC-009's `_closed_today` fix or stay independent?
- What's the migration path for currently-held positions whose entry times are unknown?

**Links:** FC-009, `put_seller.py:30,378,544`, `call_seller.py:32,300,557`.

---

### FC-016: Test coverage for orchestration & account-level gates

**Status:** Consideration
**Size estimate:** S
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** The Phase-1 gate audit for FC-013 found ~0 unit-test coverage for orchestration STAGES 3/4/5/6/9 in `wheel_engine._find_new_opportunities` (max stocks evaluated per cycle, execution gap check, wheel state phase guard, existing position blocking, max new positions per cycle) and account-level gates (`_can_open_new_positions`: max total positions, minimum buying power). These gates run on every cycle but no test asserts they fire when their conditions are met. Add unit-test coverage for each gate's positive and negative paths.

**Open questions:**
- Test directly against `WheelEngine` with mocked Alpaca, or extract the gates into pure helpers first?
- Does coverage of the Cloud-Run-server market-open / strategy-lock gates belong here too, or in a separate FC?

**Links:** FC-013 Phase-1 audit, `wheel_engine.py:220-400`.

---

### FC-020: FIFO cycle pairing in wheel_cycles_from_activities

**Status:** Plan published
**Size estimate:** S-M
**Owner:** Claude
**Plan file:** `docs/plans/fc-020.md`

**Problem / opportunity:** After FC-019 landed, the per-symbol scorecard reconciles correctly to actual cash flow (sum of Total P&L ~= account growth, modulo small Alpaca-side data anomalies). But the per-cycle drilldown still has a pairing bug: when multiple put assignments happen on the same underlying before any are called away (overlapping share lots), the view pairs each assigned put to the earliest subsequent called_away, so two puts can both pair to the same called_away. The result: OPTRD events get summed into the wrong cycle window, inflating one cycle's `capital_gain` and treating another cycle as still open.

**Concrete example (AMD):**
- 2025-11-22: put assigned at $230 (Lot A starts)
- 2025-11-29: called away at $192.50 (Lot A ends)
- 2026-01-10: put assigned at $212.50 (Lot B starts)
- 2026-01-31: put assigned at $245 (Lot C starts — concurrent with Lot B)
- 2026-04-17: called away at $252.50 (one lot ends)

The view shows:
- Cycle 1 (correct): put $230 → call $192.50, cap_gain -$3,750
- Cycle 2 (WRONG): put $212.50 → call $252.50, cap_gain -$20,500 — sums OPTRDs from the second assignment too
- Cycle 3 (WRONG): put $245 → call $252.50 — pairs to same called_away as Cycle 2

**Fix:** FIFO pairing. For each underlying:
1. Sort all OPTRD-buy events by `transaction_time` ascending → assigned-put queue.
2. Sort all OPTRD-sell events by `transaction_time` ascending → called-away queue.
3. Walk the events in time order. Each OPTRD-buy opens a lot; each OPTRD-sell closes the oldest open lot.
4. Each lot pair = one cycle. `capital_gain = sell_price − buy_price` × shares (using actual OPTRD prices, not put_strike/call_strike).
5. Lots without a matching sell remain open.

This requires a stateful walk over events, which BigQuery can express via `ARRAY_AGG` + `OFFSET` tricks or a JavaScript UDF. Alternative: do the walk in Python in the backend's `BigQueryService.get_wheel_cycles_for_symbol` method.

**Open questions:**
- SQL-only or Python-side walk? Python is simpler to write but harder to test against the view abstraction; SQL keeps the view as source of truth.
- How to handle the AMD-style data anomaly where OPTRDs net to non-zero shares but Alpaca reports zero? Surface as an "unaccounted_shares_loss" column in the per-symbol scorecard, computed as `current_shares (from OPTRD net) − live_alpaca_shares`?

**Links:** FC-018 (dashboard), FC-019 (the OPTRD ingest that exposed this).

---

### FC-017: Option chain snapshots at decision points (for retrospective decision-quality analysis)

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** The dashboard rebuild (proposed FC-018) would benefit from retrospective decision-quality analysis: "could I have rolled to a higher-strike call instead of closing?", "was there a same-DTE put at a similar delta with better premium I should have picked instead?", "how does my close-time strike compare to the strike chain that existed at that moment?". These questions are not retrospectively computable from current data — they require a snapshot of the option chain at decision time. EOD prices are not enough; we need the strikes/premiums that existed *when the close or open decision was made*.

**Scope:** capture option chain snapshots at three decision points:
1. **Close decision** — when `should_close_*_early()` returns True. Snapshot the chain near the position being closed (same expiry, ±5 strikes), plus next-week's chain (±5 strikes near current price) so a "should I have rolled?" counterfactual is possible.
2. **Open decision** — when an opportunity is selected for execution. Snapshot the chain wider for the selected symbol (±10 strikes, all available expirations within target DTE band) so a "was there a better strike?" counterfactual is possible.
3. **Skip decision** — when the scanner had a candidate but skipped it for a gate reason. Just the candidate's chain row (so we can later validate "was the gate right?").

**Storage:** new BQ table `options_wheel.option_chain_snapshots` partitioned by `snapshot_date`, clustered by `underlying`. Schema captures `snapshot_id`, `decision_type`, `decision_id` (FK to the trade/scan/close event), `underlying`, `snapshot_time`, `chain` (REPEATED RECORD with strike, expiration, type, bid, ask, mid, delta, theta, iv, volume, oi). Append-only, idempotent by `snapshot_id`.

**Open questions:**
- Storage cost — option chains can be 50-200 rows each. If we snapshot every scan + every close, that's potentially 5-10k chain rows/day. At BQ pricing this is trivial ($X/month) but worth a back-of-envelope check.
- Alpaca rate limits — pulling chains adds API load. Are we already pulling them for these decisions and just not persisting? (Yes for opens — `find_suitable_*` already calls the chain. Closes likely don't pull a wider chain — would be net-new API calls.)
- Decision-id schema — how does a close-decision row in this table link back to the actual close FILL? Use `order_id` of the buy-to-close as the natural FK.
- Retention — do we want this forever or roll off after 1 year?

**Why deferred from FC-018 (dashboard rebuild):** counterfactual analysis is high-value but expensive to build correctly. FC-018 ships v1 of the new dashboard with retrospective views that *don't* require chain snapshots (closed-trade % of max profit, vs-buy-and-hold per symbol, ACB walk). FC-017 unlocks a follow-up dashboard iteration that adds the harder counterfactual surfaces.

**Links:** FC-018 (dashboard rebuild — depends on this for full decision-quality views); `src/strategy/put_seller.py:should_close_put_early`, `src/strategy/call_seller.py:should_close_call_early`, `src/api/market_data.py:find_suitable_puts/find_suitable_calls`.

---

### FC-025: AMZN silent-exercise correction (paper-engine, Jan 16 2026)

**Status:** Consideration
**Size estimate:** S (data-only correction, same shape as FC-021)
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** Same Alpaca paper-engine bug as FC-021 (AMD silent-exercise), surfaced for AMZN by FC-024's view rewrite. Pre-FC-024 the `running_shares` field was always 0 so this anomaly was invisible. Post-FC-024, `acb_per_symbol_current` shows AMZN `current_shares = −100` — i.e., 1 OPASN put-assigned but 2 OPASN called-aways with no second matching assignment.

**Evidence:**
- AMZN $240 put `AMZN260116P00240000` sold 2026-01-12 for $73 premium, expiring 2026-01-16. `trades_with_outcomes.outcome = 'open'` despite the option having expired ~4 months ago.
- AMZN closed 2026-01-16 at **$239.09** — $0.91 ITM. Would auto-exercise on standard option settlement. No OPASN or OPTRD ingested.
- 2026-04-23 called-away `AMZN260422C00240000` at strike **$240** for OPTRD net `+$24,000`. Exact strike match to the silent-assignment cost basis is consistent with the bot writing covered calls against shares it knew it had.
- Net OPTRD: +$24,000 (Apr 23 call called-away) with no offsetting −$24,000 from a missing Jan 16 OPTRD-in. AMZN's `share_side_pnl` is currently inflated by exactly +$24,000.

**Expected impact post-correction (mirroring FC-021's pattern):**
- Insert one synthetic OPASN put + one synthetic OPTRD pair, prefix `synthetic-fc-025-`, dated 2026-01-16
- OPTRD `net_amount = -$24,000` (cash out for 100 shares × $240 strike)
- AMZN `share_side_pnl`: $20,500 → −$3,500 (matches actual cycle math: cycle 1 −$3,500 + cycle 2 round-trip $0)
- AMZN `total_realized_pnl`: $26,206 → $2,206 (option $5,706 + share −$3,500)
- AMZN `current_shares` returns to 0 (clean books)

**Cross-symbol scan for other silent exercises:** Ran `SELECT * FROM trades_with_outcomes WHERE outcome = 'open' AND expiration < CURRENT_DATE()` on 2026-05-07 — only AMZN260116P00240000 returned. Bug is confined to this single occurrence; no other corrections needed.

**Open questions:**
- Confirm via Alpaca account history that the 2026-01-16 silent assignment occurred (their order detail page may show it even though their activity API doesn't).
- Should the synthetic-row writer be promoted to a reusable utility (`tools/diagnostics/correct_silent_exercise.py`) given this is the second occurrence (FC-021 was the first)? Two data points isn't enough to justify pulling out a generic tool, but if a third occurs the answer becomes yes.

**Links:** FC-021 (AMD silent-exercise, same root cause), FC-024 (the view rewrite that surfaced this), FC-019 (introduced `share_side_pnl`), `docs/investigations/amd-reconciliation.md` (the prior playbook).

---

### FC-011: Support non-Friday option expirations (daily/weekly rolling expirations)

**Status:** Consideration
**Size estimate:** L
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** Some high-volume symbols (e.g., GOOGL, AMZN, SPY, QQQ) now have options expiring every trading day, not just Fridays. The current system assumes Friday-only expirations in multiple places:

1. **FC-006 rolling engine** — hardcoded Friday guard (`weekday()==4`) in both the `/roll` endpoint and Cloud Scheduler (`30 15 * * 5`). Positions expiring on a Wednesday won't be evaluated for rolling.
2. **DTE bands** — the 7→0 bands assume a Monday-sell, Friday-expire cadence. A position sold Monday with a Wednesday expiry has DTE=2 at open, hitting different (later) bands than intended.
3. **`call_target_dte: 7` / `put_target_dte: 7`** — assumes next-Friday expiry. With daily expirations available, shorter DTE targets (2-3 days) become viable, potentially improving theta capture per calendar day.
4. **Strike selection** — `find_suitable_calls/puts` filters by `dte <= target_dte` which works, but may miss better opportunities at non-Friday expirations.

**Open questions:**
- Which symbols in our universe have daily expirations vs Friday-only? Need to audit Alpaca's option chain data.
- Should the rolling engine run daily (not just Fridays) for symbols with daily expirations?
- Do DTE bands need to be reparameterized for shorter-DTE strategies (see FC-003)?
- Should we support mixed strategies — daily expirations for some symbols, weekly for others?
- How does this interact with FC-003 (DTE target optimization from 7 to 2-3)?

**Links:** FC-003 (DTE target optimization), FC-006 (rolling engine)

---

## Completed

_Move entries here once a plan has been published, executed, and merged. Include plan file + PR/commit link._

### FC-006: Covered call rolling engine (Friday EOW)
- Plan: `docs/plans/fc-006.md`
- PR: https://github.com/memon1987/options_wheel/pull/5 (merged 2026-04-16)
- Commit: `08fb876`
- Notes: Deployed with `rolling.enabled: false`. Pending paper testing on Fridays before enabling Cloud Scheduler job.

### FC-007: Earnings Calendar Service (Finnhub)
- Plan: `docs/plans/fc-007.md`
- PR: https://github.com/memon1987/options_wheel/pull/5 (merged 2026-04-16)
- Commit: `0ccf852`
- Notes: Finnhub API key in Secret Manager, injected into Cloud Run. Log enrichment active; PutSeller/CallSeller integration deferred.

### FC-010: Disable call stop-losses (assignment is profitable by design)
- Plan: `docs/plans/fc-010.md`
- PR: https://github.com/memon1987/options_wheel/pull/7 (merged 2026-04-17)
- Commit: `737db8a`
- Notes: Single config change (`use_call_stop_loss: false`). Deployed to Cloud Run revision `00142-vz6`.

### FC-012: Shift dashboard logging to Alpaca queries wherever authoritative
- Plan: `docs/plans/fc-012.md`
- PR: https://github.com/memon1987/options_wheel/pull/8 (merged 2026-04-24)
- Commit: `8b31a1b`
- Notes: All phases (2.1-2.7) shipped in one PR after user dropped the parity gate. New tables: `trades_from_activities` (465 rows backfilled) and `equity_history_from_alpaca` (124 rows). New views: `trades_with_outcomes`, `wheel_cycles_from_activities`. Three Cloud Scheduler jobs ingest on a split schedule. V1 tables (trades, wheel_cycles, position_snapshots, order_statuses) left inert pending manual `bq rm` — a follow-up remote routine on 2026-05-01 opens a cleanup PR. Follow-up fix PR #9 preserves `GCP_PROJECT` env var across bot deploys.

### FC-008: Stop-loss events mislabeled as profit_target_reached (superseded)
- No dedicated PR — superseded by FC-010 + FC-012.
- Closed: 2026-04-24
- Notes: Two independent mechanisms neutralized this. (1) FC-010 disabled call stop-losses, so `should_close_call_early` no longer returns True for losses — the mislabeling trigger is gone. (2) FC-012 cut dashboard reads over to `trades_with_outcomes` (Alpaca-sourced), so the corrupted `event_type=early_close_executed` + `reason=profit_target_reached` rows in the v1 `trades` table no longer affect analytics. Historical rows remain dirty but unread; the v1 table itself is scheduled for drop on 2026-05-01 via the FC-012 cleanup routine. If put early-closes ever start showing the same mislabel in structlog events, re-file as a new FC focused on the put-side path only.

### FC-018: Wheel-centric dashboard rebuild (frontend only)
- Plan: `docs/plans/fc-018.md`
- PRs: #12 (skeleton), #13 (backend), #14 (pages), #15-#18 (review fixes), #22 (Trade Log), #23 (gap-closing), #24 (PR F cutover), #25 (PR G cleanup) — final merge 2026-05-05
- Commits: `b7b9184` → `4eb74d2` (PR G)
- Notes: 3-page dashboard (Overview / By Symbol / Bot Health) shipped via strangler migration. Canonical paths are now bare (`/overview`, `/symbol`, `/bot-health`); `/v2/*` and legacy `/positions`, `/trades`, `/performance`, `/cycles` redirect for bookmark compatibility. Legacy frontend preserved under `dashboard/frontend.archive/` with emergency-revert README — recommend deletion after ~2 weeks of bake time. Mid-execution the gross-vs-net premium audit triggered FC-019; FIFO cycle pairing for overlapping share lots was scoped out as FC-020.

### FC-022: Trade Log contract IDs + ET timezone + By-Symbol summary table
- Plan: `docs/plans/fc-022.md`
- PR: https://github.com/memon1987/options_wheel/pull/26 (merged 2026-05-06)
- Commit: `cd1d47d`
- Notes: Trade Log gains OCC symbol + expiration + Alpaca order ↗ link per row. All date helpers (`fmtDate`, `fmtDateShort`, `fmtDateTime`) now ET-anchored with explicit `timeZone: 'America/New_York'` and `fmtDateTime` shows the EST/EDT marker. `/symbol` landing page replaces the pill grid with a sortable summary table (`SymbolUniverseTable`) backed by existing scorecard data. Backend `fc018_acb_timeline_per_symbol` view extended with `occ_symbol`, `order_id`, `expiration` columns. `positionState`/`stateColor` extracted from SymbolScorecard into a shared util. 4 new vitest tests assert ET-stability across system locales.

### FC-021: Synthetic activity correction for Alpaca paper-engine silent settlements
- Plan: `docs/plans/fc-021.md`
- Commit: `133ebb0` (no PR — data-only correction)
- Date: 2026-05-06
- Notes: Inserted two synthetic rows into `options_wheel.trades_from_activities` (`activity_id LIKE 'synthetic-fc-021-%'`) to reconcile the dashboard for `AMD260116C00212500`'s silent 2026-01-16 paper-engine exercise. Discovered during reconciliation diving (see `docs/investigations/amd-reconciliation.md`) — Alpaca's paper engine settled the deep-ITM call without logging OPASN/OPEXP/OPTRD; daily-P&L hypothesis fit confirmed only one silent event occurred, no second discrepancy. Effect on AMD scorecard: `share_pnl` −$24,250 → −$3,000, `total_pnl` −$17,319 → +$5,309, Cycle 2 `cap_gain` −$20,500 → $0 (clean wash). Headline Total Return remains pinned to NLV − sum(deposits) so it's unaffected; per-symbol sum across symbols ($44.9k) no longer ≈ headline ($20.1k) — accepted divergence reflecting the off-book silent settlement. Audit query: `WHERE activity_id LIKE 'synthetic-%'`. Rollback: `DELETE` same predicate.

### FC-023: Per-symbol Realized P&L reconciliation — single canonical number across drilldown
- Plan: `docs/plans/fc-023.md`
- PR: https://github.com/memon1987/options_wheel/pull/27 (merged 2026-05-07)
- Commit: `83bbd57`
- Notes: Top-of-page "Realized P&L" card and Wheel-vs-B&H "Wheel" total now both display canonical `total_realized_pnl` (option leg + share leg, FC-019) instead of two different disagreeing numbers. UNH pre-fix: top $4,334, wheel $10,222 (double-counted premium). UNH post-fix: both $2,584. View `fc018_vs_buy_and_hold_per_symbol.wheel_minus_bh` formula corrected from `realized_pnl + total_premium` to `total_realized_pnl`. B&H labeled "(price only)" — dividend-reinvested B&H is a deferred concern (FC-017's neighborhood).

### FC-024: ACB walk view rewrite — restore missing event types and ACB computation
- Plan: `docs/plans/fc-024.md`
- PRs: https://github.com/memon1987/options_wheel/pull/30 (merged 2026-05-07; replaces auto-closed [#28](https://github.com/memon1987/options_wheel/pull/28) which lost its base on FC-023's merge)
- Commit: `1a4e401`
- Notes: `fc018_acb_timeline_per_symbol` rewritten to source from `trades_from_activities` directly via four UNION-ALL blocks (opens / closes / OPASN with QUALIFY-guarded OPTRD pairing / OPEXP). Pre-fix every symbol had `rows_w_acb=0`; post-fix all 6 event types render correctly with ACB transitions during share-holding windows. Reference-dot positioning fixed (`dotAxisFor()` helper rides ACB axis when shares held, premium axis otherwise). Incidentally fixed Phase Timing observation #4 (UNH state machine now returns 4-phase split: cash 124d / short_put 61d / long_stock 10d / covered 17d). Surfaced AMZN silent-exercise data anomaly as a side discovery, filed as FC-025.

### FC-026: Decision Quality — surface Premium Received / Captured / Foregone macro stats
- Plan: `docs/plans/fc-026.md`
- PR: https://github.com/memon1987/options_wheel/pull/29 (merged 2026-05-07)
- Commit: `1b5559c`
- Notes: Capture-ratio math validated as correct against raw activities (no data fixes shipped). Three new dollar-magnitude aggregates rendered in the chart card: Received / Captured / Foregone (buybacks). UNH macros: **$5,888 / $4,334 (73.6%) / $1,554 (26.4%)** (verified 2026-05-07 against raw Alpaca activity feed). "Foregone" is qualified "(buybacks)" to disambiguate from the counterfactual reading (which would require option-chain snapshots — FC-017). Frontend-only; no view, no backend, no payload change.

### FC-027: Cycle Table — separate "Total Premium" from "Cycle P&L"
- Plan: `docs/plans/fc-027.md`
- PR: https://github.com/memon1987/options_wheel/pull/31 (merged 2026-05-07)
- Commit: `9928db8`
- Notes: Surfaced mid-trace during the FC-023/024/026 manual reconcile when the user noticed the Cycle Table column labeled "Cycle P&L" actually displayed `total_premium` only (option-side net), silently excluding `capital_gain` (share-side cash flow). For UNH Cycle 1 the column read +$1,218 but the true cycle outcome was $1,218 − $1,750 = −$532. Fix: rename existing column → "Total Premium" (matches the data), add new "Cycle P&L" column = `total_premium + capital_gain`. Same class of bug as FC-023 at cycle granularity. Peer review caught one defect (Cap Gain tooltip leaked internal nomenclature `Post-FC-019`/`OPTRD` — reverted to user-readable copy) and two test-strength suggestions (cell-position assertions) — all addressed pre-merge.

### FC-028: fmtDate calendar-date off-by-one (TZ shift on pure dates)
- PR: https://github.com/memon1987/options_wheel/pull/32 (merged 2026-05-07)
- Commit: `0c4d20d`
- Notes: Plan-exempt (single-file utility bug fix). User caught on Trade Log: OCC `UNH260424P00302500` (Apr 24 expiry) rendered "Apr 23" in the Expiration column. Root cause: `fmtDate()` parsed pure-date strings as UTC midnight then converted to ET (UTC−4) — rolled back to prior day. Same bug affected `event_date` Date column. Fix detects `YYYY-MM-DD`-shaped inputs and renders from year/month/day directly with no TZ conversion. Full ISO 8601 timestamps still ET-anchor per FC-022. 4 new vitests pin the contract; FC-022's ISO behavior verified preserved.

### FC-019: True P&L reconciliation — JNLC + OPTRD ingest, share-side P&L
- Plan: `docs/plans/fc-019.md` (written retroactively)
- PR: https://github.com/memon1987/options_wheel/pull/19 (merged 2026-05-05)
- Commit: `78acf92` (preceded by `4862159` — interim env-var-baseline fix that this PR replaces with the real JNLC sum)
- Notes: Per-symbol scorecard now reconciles to actual account growth (sum of Total P&L = $21,808 vs account growth $20,080, with the ~$1,600 unexplained gap concentrated entirely on AMD's Alpaca-side data anomaly). New scorecard columns: Option P&L (renamed from Net P&L), Share P&L (FC-019), Total P&L (sum). `wheel_cycles_from_activities.capital_gain` now uses real OPTRD cash flow within the cycle window. `BASELINE_DEPOSITS` env var becomes a fallback only — primary source is `SUM(net_amount) WHERE activity_type='JNLC'`. Per-cycle pairing for overlapping share lots is filed as **FC-020** for follow-up.
