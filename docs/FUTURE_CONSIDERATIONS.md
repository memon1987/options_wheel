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
