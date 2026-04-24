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

### FC-009: Duplicate early_close_executed logging (narrowed 2026-04-24 post-FC-012)

**Status:** Consideration (scope narrowed)
**Size estimate:** S
**Owner:** unassigned
**Plan file:** not yet

**Original problem:** The bot logs `early_close_executed` multiple times (4-10 duplicates) for the same position when the close order doesn't fill. The `_closed_today` dedup set in `cloud_run_server.py` is in-memory and resets on Cloud Run cold starts.

**What FC-012 changed:** the dashboard no longer reads from `options_wheel.trades` (the structlog-populated table where the duplicate rows landed). It reads `trades_with_outcomes`, which projects over `trades_from_activities` — Alpaca-sourced, deduped on `activity_id`. Duplicate structlog events no longer corrupt dashboard numbers.

**Remaining scope:** one open question from the original FC is still unanswered:

> Does the duplicate logging cause duplicate *orders*, or just duplicate *log entries*?

If only log entries, this FC is fully superseded — close without work. If real duplicate orders, FC-010 already reduces the blast radius (call stop-loss early-closes disabled, so the main offender is gone), but put early-closes use the same path and could still double-fire.

**Action needed:** verification only — check Alpaca order history for the affected dates (e.g., NVDA260415P00165000 on Apr 8-9) and count distinct `buy_to_close` orders vs. the number of `early_close_executed` log entries for that symbol. Could be done via a single BQ query now that `trades_from_activities` has the real fill stream:

```sql
SELECT symbol, COUNT(DISTINCT order_id) AS real_close_orders
FROM `options_wheel.trades_from_activities`
WHERE side = 'buy_to_close'
  AND symbol = 'NVDA260415P00165000'
  AND DATE(transaction_time, 'America/New_York') BETWEEN '2026-04-08' AND '2026-04-09'
GROUP BY symbol
```

If `real_close_orders = 1`, the duplicates were log-only → close FC-009. Otherwise keep open with narrowed scope (fix the dedup, not the logging).

**Links:** BQ query above; FC-010, FC-012.

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
