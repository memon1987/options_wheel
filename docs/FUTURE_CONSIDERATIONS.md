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

### FC-008: Stop-loss events mislabeled as profit_target_reached

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** Multiple early close events in BQ show -75% to -81% P/L but are logged with `event_type=early_close_executed` and `reason=profit_target_reached`. These are clearly stop-loss triggers (config: 50% loss × 1.5 multiplier = 75% threshold) being logged under the wrong event type. This corrupts BQ analytics — any query filtering on `profit_target_reached` includes large losses.

Affected positions (Apr 8-15): IWM call (-$927), GOOGL call (-$2,095), AMD call (-$970), AMZN call (-$904).

**Open questions:**
- Root cause: does `should_close_call_early()` return True for both profit targets and stop losses without distinguishing?
- Should the return type change from `bool` to `Tuple[bool, str]` (close, reason)?
- Does the monitor endpoint need to propagate the reason to logging?

**Links:** BQ query: `SELECT * FROM trades WHERE event_type = 'early_close_executed' AND profit_pct < 0`

---

### FC-009: Duplicate early_close_executed logging

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** The bot logs `early_close_executed` multiple times (4-10 duplicates) for the same position when the close order doesn't fill. The `_closed_today` dedup set in `cloud_run_server.py` is in-memory and resets on Cloud Run cold starts. Each monitor invocation on a fresh instance retries the close and logs "executed" again.

Affected positions: NVDA260410P00167500 (6 duplicates on Apr 3), NVDA260415P00165000 (~10 duplicates Apr 8-9), GOOGL260415C00312500 (~8 duplicates Apr 14).

**Open questions:**
- Should the dedup set be persisted to GCS (alongside wheel state)?
- Or should the bot check Alpaca order history for pending close orders before placing a new one?
- Does the duplicate logging cause duplicate orders, or just duplicate log entries?

**Links:** BQ query: `SELECT symbol, DATE(timestamp), COUNT(*) FROM trades WHERE event_type = 'early_close_executed' GROUP BY 1, 2 HAVING COUNT(*) > 1`

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

### FC-012: Shift dashboard logging to Alpaca queries wherever authoritative (+ historical backfill)

**Status:** Plan published
**Size estimate:** L
**Owner:** Claude
**Plan file:** `docs/plans/fc-012.md`

**Problem / opportunity:** Dashboard data today is produced at runtime by the bot via two paths: (1) structlog → Cloud Logging → BigQuery sink into `options_wheel.trades`, and (2) direct inserts through `AnalyticsWriter` (`src/data/analytics_writer.py`). Runtime-generated data ties dashboard correctness to bot uptime and to our own event schemas staying in sync. If the bot crashes after a fill but before the event emits, the dashboard is blind. Every new strategy change risks a log-schema change that has to propagate through the pipeline.

Alpaca maintains authoritative records for a meaningful subset of what we log — executions, assignments, expirations, exercises, order history, portfolio/equity history, account activity. We already use `/v2/account/activities` for reconciliation in `src/api/alpaca_client.py`. Where Alpaca is authoritative, **querying Alpaca is preferable to logging our own events** — simpler, idempotent, survives bot crashes, backfillable from inception (pending retention validation).

**Guiding principle — anchor of the eventual plan:** for any piece of dashboard data, prefer an Alpaca-sourced pull over a runtime-emitted event *when* Alpaca can reproduce it faithfully. Things Alpaca genuinely cannot cover stay on the structlog pipeline:
- Scan decisions, filtered symbols, risk-manager rejections, gap-detector triggers
- Strategy-context fields (earnings proximity, gap status, DTE-at-close, fill vs bid/ask spread)
- Errors, circuit-breaker trips, execution timing, dedup/attempt counts
- Anything describing *why* the bot chose to act or not act

Everything else is fair game to migrate — including `AnalyticsWriter` tables, but not limited to them. Fill events, assignment events, expiration events, order-status transitions, position snapshots, and equity history are all candidates if an Alpaca endpoint covers them.

**Plan requirement:** When this graduates to `docs/plans/fc-012.md`, the plan **must** begin with an extensive **current vs future state** audit: inventory every table and field the dashboard reads today (both `AnalyticsWriter` outputs and structlog-sourced tables), and map each to one of:
- **(a)** Fully replaceable by an Alpaca endpoint (`/v2/account/activities`, `/v2/orders`, `/v2/account/portfolio/history`, `/v2/positions`, etc.) — migrate.
- **(b)** Derivable from Alpaca data + light computation — migrate.
- **(c)** Partially covered — document the gap and decide per-field whether to migrate-with-enrichment or leave on structlog.
- **(d)** Not covered by Alpaca — stays on structlog pipeline, untouched.

Only (a) and (b) migrate without caveat. (c) items require explicit per-field decisions in the plan. No field moves off the structlog pipeline without a documented Alpaca equivalent.

**Open questions:**
- Does Alpaca actually retain activity history from account inception? Docs don't specify — needs empirical test (`after=2020-01-01` against a long-running paper account) *before* the plan commits to "backfill to beginning of time."
- Which endpoints beyond `/v2/account/activities` are worth auditing? `/v2/orders` (order history + status), `/v2/account/portfolio/history` (equity curves), `/v2/positions` (current holdings). Are there others?
- Backfill strategy: drop-and-reload from Alpaca vs. incremental dedup against existing rows by `order_id` / activity ID? Risk of double-counting if keys don't align cleanly across the two sources.
- Schema: new Alpaca-sourced tables alongside existing, or in-place rebuild? In-place is cleaner for dashboard queries but higher-risk during transition.
- Polling cadence and rate-limit budget (200 req/min) once backfill pagination + ongoing pulls are both active.
- Enrichment fields (earnings_proximity, gap status, DTE-at-close) currently attached at write-time — join at read-time from a separate enrichment table keyed by `order_id`, or drop them from the Alpaca-sourced rows?
- Interaction with FC-008 (mislabeled stop-loss events) and FC-009 (duplicate close logging) — does sourcing executions from Alpaca sidestep these bugs, or do they remain on whatever structlog events still fire?
- Migration order: start with the easiest Alpaca-covered slice (e.g., fills) to prove the pattern, then expand? Or all-at-once rebuild?

**Links:** `src/api/alpaca_client.py` `get_account_activities()`, `src/utils/logging_events.py`, `src/data/analytics_writer.py`, `dashboard/backend/services/bigquery.py`. Alpaca docs: https://docs.alpaca.markets/reference/getaccountactivities

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
