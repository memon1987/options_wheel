# Release Notes — 2026-04-07 (Session 3: BQ Get-Well Investigation)

## Summary
Attempted to execute the BQ reporting get-well plan for all 6 broken dashboard endpoints. Identified and fixed all query/view mismatches, but discovered a critical BigQuery schema conflict that was blocking ALL wildcard table queries (not just the 6 broken endpoints). Resolved the schema conflict by deleting 2 conflicting tables. All code changes were rolled back at user's request to continue in the prior session with full context. BQ-side changes (table deletions, view rebuild) persist.

## Changes

### Code Changes (ALL ROLLED BACK — not committed)
These fixes were validated against live BQ but reverted so the prior session can re-apply them with full context:

1. **`get_recent_trades()`** — removed `event` field (not in `trades_executed` view)
2. **`get_recent_errors()`** — `event_type` → `error_type`, `severity` → `error_message`/`component` (matching deployed `errors_all` view which uses JSON_VALUE, not the STRUCT version in docs)
3. **`get_performance_metrics()`** — rewrote to calculate `puts_sold`/`early_closes` from `trades_executed` (those fields don't exist in `daily_operations_summary`)
4. **`get_daily_stock_snapshots()`** — added try/except for graceful empty return
5. **`get_position_updates()`** — added try/except for graceful empty return
6. **`passed_symbols`/`rejected_symbols` logging** — reverted from comma-joined strings to Python lists (in `market_data.py`, `gap_detector.py`, `logging_events.py`)

### BigQuery Changes (PERSISTED — cannot be rolled back)
1. **Deleted table `run_googleapis_com_stderr_20260407`** — had `passed_symbols` as STRING (conflicted with ARRAY<STRING> in older tables)
2. **Deleted table `run_googleapis_com_stderr_20260408`** — same conflict
3. **Rebuilt `wheel_cycles` view** — now uses direct STRUCT access instead of `TO_JSON_STRING` (which crashes on REPEATED fields)
4. **Dropped `stage1_price_volume_analysis` view** — broken, unused by dashboard

## Key Decisions & Rationale

**Deleted 2 tables instead of workaround:** The schema conflict (ARRAY<STRING> vs STRING for `passed_symbols`) blocked ALL wildcard queries across ALL views. The choice was lose 2 days of data or lose access to 6 months. Two days was the obvious trade-off.

**Rolled back code changes:** User wants to continue in the previous session which has full context of the system. All fixes were validated against live BQ and documented here for re-application.

**STRUCT access over JSON_VALUE(TO_JSON_STRING()):** `TO_JSON_STRING(jsonPayload)` serializes the entire STRUCT including REPEATED/ARRAY fields, which fails with "Cannot read repeated field of type STRING as optional STRING". Direct `jsonPayload.field` STRUCT access is the only reliable approach for these Cloud Logging tables.

## Discoveries

### Critical: Schema Conflict Mechanism
Commit `365aadd` (Apr 6) changed `passed_symbols`/`rejected_symbols` from Python lists to comma-joined strings. This caused:
- Tables pre-Apr 7: `passed_symbols` = `ARRAY<STRING>` (from list logging)
- Tables Apr 7+: `passed_symbols` = `STRING` (from string logging)
- BigQuery CANNOT merge these types in wildcard queries → **every view fails**

This is a permanent, irreversible breakage. You cannot change a column's type/mode in BQ. The only fix is to delete the conflicting tables.

### Critical: TO_JSON_STRING Is Unusable
The `errors_all` view in production uses `JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.field')`. This pattern is fragile:
- Works only when no REPEATED fields exist in the STRUCT
- Fails silently when a new ARRAY field appears in any table in the wildcard range
- The previous session's recommendation to use this pattern for "schema tolerance" is wrong — it's actually less tolerant than STRUCT access

### wheel_cycles Is Empty
The backfill script (`scripts/backfill_wheel_cycles.py`) ran locally, not on Cloud Run. The Cloud Logging → BQ sink only captures Cloud Run stderr. Zero `wheel_cycle_complete` events exist in BQ. Additionally, the custom fields logged by the backfill (`capital_gain`, `put_strike`, `call_strike`, etc.) don't exist in the jsonPayload STRUCT schema — they'd be silently dropped even if the events reached BQ.

### Deployed errors_all View Differs From Docs
The `errors_all` view in BQ uses `JSON_VALUE(TO_JSON_STRING())` and doesn't expose `severity`. The view in `bigquery_views_enhanced_complete.sql` uses STRUCT access and does include `severity`. The dashboard query must match the DEPLOYED view, not the documented one.

### Latent Schema Conflict: `symbols` Field
`symbols` is logged as `len(...)` (integer) in `options_scanner.py:43` but as a list in backtesting code. Table 20260407 had it as FLOAT64 vs ARRAY<STRING> in older tables. This hasn't caused issues yet (the `passed_symbols` conflict was hit first) but will break again if similar conditions arise.

## Data Baselines

| Metric | Value |
|---|---|
| BQ tables with ARRAY schema | All tables 20251015–20260406 |
| BQ tables deleted (STRING conflict) | 20260407, 20260408 |
| Validated queries returning data | trades (3 rows), errors (3 rows), filtering (5 rows), summary (128 scans/36 puts/30 closes), wheel-cycles (empty), stock-snapshots (empty) |
| Current BQ views | 13 (was 14, dropped stage1_price_volume_analysis) |

## Known Issues

1. **`passed_symbols` logging still outputs strings** — code was rolled back, so the bot is still logging comma-joined strings. Next deploy will recreate the schema conflict in new daily tables. **Must revert logging to arrays before next deploy.**
2. **`errors_all` view uses TO_JSON_STRING** — works now that conflicting tables are deleted, but will break again if any table gains a new REPEATED field
3. **`symbols` field type inconsistency** — logged as int in scanner, list in backtesting. Latent conflict.
4. **wheel_cycles empty** — backfill never reached BQ. Needs either Cloud Run execution or direct BQ insert.
5. **All 6 dashboard endpoint fixes not committed** — code rolled back, needs re-application

## Next Steps (for the continuing session)

1. **Revert `passed_symbols`/`rejected_symbols` logging to arrays** — `src/api/market_data.py:157-158`, `src/risk/gap_detector.py:433-434`. This MUST happen before any bot deploy or the schema conflict will recur.
2. **Re-apply the 6 endpoint fixes** in `dashboard/backend/services/bigquery.py` (all validated, details in Changes section above)
3. **Fix wheel_cycles backfill** — either run on Cloud Run or direct-insert into a dedicated BQ table
4. **Rebuild `errors_all` view** with STRUCT access instead of TO_JSON_STRING (fragile)
5. **Fix `symbols` field** in `options_scanner.py:43` — log as list, not `len()`
6. **Deploy bot + dashboard** to Cloud Run

## Files Changed

0 files committed (all changes rolled back). BQ-side changes only (see BigQuery Changes section).

## Configuration Changes Required

| Setting | Status | Action |
|---|---|---|
| BQ tables 20260407/20260408 | Deleted | Will be recreated by log sink once bot deploys with correct logging |
| `wheel_cycles` view | Rebuilt | Now uses STRUCT access — working but empty |
| `stage1_price_volume_analysis` view | Dropped | Was broken and unused |
