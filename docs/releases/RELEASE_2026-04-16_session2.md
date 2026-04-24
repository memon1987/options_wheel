# Release Notes — 2026-04-16 (Session 2)

## Summary

Comprehensive session covering FC-006 (call rolling engine), FC-007 (earnings calendar), FC-010 (disable call stop-losses), profit-taking optimization, and docs reorganization. Driven by investigation into NVDA Apr 15-16 trades that revealed quick-close churn and destructive stop-loss behavior. Three PRs merged (#5, #6, #7), three Cloud Run deploys, one Cloud Scheduler job created. The system now has earnings awareness, Friday call rolling, smarter profit-taking, and no more cash-destructive call stop-losses.

## Changes

### New Features

- **FC-006: Call Rolling Engine** — Friday-only engine that buys-to-close expiring ITM short calls and sells-to-open new calls at higher strikes. Sequential BTC→STO execution with percentage-based debit tolerance (25% of original premium, 0.5% notional backstop), 2-roll max, partial fill tracking. POST /roll endpoint + Cloud Scheduler job (Fridays 3:30 PM ET).
- **FC-007: Earnings Calendar Service** — Finnhub-based shared service providing `is_earnings_within_n_days()` for trade gating and `get_earnings_proximity()` for log enrichment. In-memory cache, 24h TTL, graceful degradation (fails open). Secret Manager integration.
- **Profit-taking optimization** — 4-hour minimum hold period prevents quick closes on lucky overnight moves. Raised early DTE bands (7→35%, 6→40%, 5→35%, 4→45%). Stop-loss still fires immediately.
- **FC-010: Disabled call stop-losses** — `use_call_stop_loss: true → false`. Assignment is profitable by construction; FC-006 handles ITM management.
- **call_rolls BigQuery view** + `/api/history/call-rolls` dashboard endpoint for roll analytics.

### Bug Fixes

- **position_updates BQ view filter mismatch** — View filtered on `event_category='position_update'` but `log_position_update()` sets `event_category='position'`. Position events weren't reaching BQ. Fixed.
- **Date-sensitive test** — `test_blocked_dte_too_high` used hardcoded April 2026 dates that expired. Fixed to use dynamic dates.

### Infrastructure

- **Cloud Scheduler:** `options-wheel-roll-friday` job (Fridays 3:30 PM ET, OIDC auth)
- **Secret Manager:** `finnhub-api-key` created, injected into Cloud Run
- **3 Cloud Run deploys:** Revisions 00158-kal (FC-006/007), 00165-zal (profit-taking), 00142-vz6 (FC-010)
- **3 PRs merged:** #5 (FC-006+007), #6 (profit-taking), #7 (FC-010)

### Code Quality

- **23 new CallRoller tests** — trigger gates, debit tolerance, economics, validate_roll, state tracking
- **195 total tests passing** throughout all changes
- **Docs reorganized** — 57 loose files into 7 subdirectories (bigquery/, deployment/, logging/, operations/, analysis/, archive/, plans/)

## Key Decisions & Rationale

### FC-006 plan review found 5 issues before implementation
1. Earnings blackout claimed "inherited from gap_detector" — gap_detector has no earnings awareness → created FC-007 as dependency
2. Original premium had no data source for debit tolerance → extended WheelStateManager with active_call_details
3. validate_new_position doesn't fit rolls (checks position count, concentration) → new validate_roll()
4. Partial fills unaddressed → track and alert, Monday cycle covers uncovered shares
5. STO pricing asymmetric (5% BTC, 2% STO) → symmetric 5% for thin Friday PM liquidity

### DTE uses calendar days — this is correct
Theta decay in options pricing models is calendar-based. Weekend theta gets priced into Friday close and reflected Monday open. Switching to trading days would misalign profit targets with actual decay curves.

### Call stop-losses are harmful, not protective
Data: 65 profitable closes (+$5,882) vs 13 stop-loss closes (-$20,391) = net -$14,509. Stop-losses pay real cash to avoid assignment, but assignment on covered calls is profitable by construction (strike > cost basis). With FC-006 rolling engine live, the panic-buyback stop-loss is redundant. GOOGL alone lost $17,590 across 10 duplicate stop-loss events on a $493 premium position.

### Profit-taking bands too aggressive at early DTEs
54% of closes happened within 0-1 days of opening (DTE 7-8), netting $17-88 per trade. The bands don't distinguish hold time from time remaining — a lucky overnight move triggers a close at 25% (DTE=6) just one day after opening at DTE=7. Raised early bands + added 4-hour minimum hold period.

### Finnhub over Alpaca for earnings
Alpaca corporate actions API has no earnings calendar (only dividends/splits/mergers). Evaluated 4 alternatives: Finnhub (60 calls/min free, per-symbol query, official SDK — winner), Yahoo Finance (unreliable scraping), Alpha Vantage (25 calls/day too low), Polygon (paid only).

### One PR per FC
Established rule for clean rollback. FC-006+007 were bundled in PR #5 (dependency), but going forward each FC gets its own PR.

### Plan files for all trading behavior changes
Even single-line config changes (FC-010: `true → false`) get a plan file if they alter trading behavior, per plan-first rules.

## Discoveries

- **Alpaca Position objects have no `created_at` field.** Hold period tracking uses in-memory dict within each seller. Survives within Cloud Run instance lifetime; on cold starts, positions are old enough that hold period doesn't matter.
- **`_closed_today` dedup set resets on Cloud Run cold starts** — root cause of duplicate close events (FC-009). Each monitor invocation on fresh instance retries close and logs "executed" again.
- **Stop-loss and profit-target closes share the same logging path** — `should_close_call_early()` returns True for both without distinguishing. Monitor endpoint logs everything as `profit_target_reached` (FC-008).
- **Finnhub `hour` field empty for smaller caps** (PLTR, MARA) — doesn't affect blackout logic but limits timing analysis.

## Data Baselines

### Profit-taking (60-day window, pre-optimization)
| Close Type | Count | Total P/L | Avg P/L |
|---|---|---|---|
| Profitable closes | 65 | +$5,882 | +$90.50 |
| Stop-loss closes | 13 | -$20,391 | -$1,568.54 |
| Net | 78 | -$14,509 | |

### Close frequency by DTE band (pre-optimization)
- DTE 7-8: 54% of all closes (within 0-1 days of opening)
- DTE 6-8: 73% of all closes
- Quick close profit range: $17-$88 per trade

### Finnhub earnings data quality
- 7/7 active symbols returned valid data
- `hour` field populated for large caps (GOOGL, AMD, SOFI, HOOD, INTC), empty for smaller (PLTR, MARA)

## Known Issues

- **FC-008: Stop-loss mislabeling** — Closes at -75% to -81% logged as `profit_target_reached`. Severity: medium (corrupts BQ analytics, no trading impact since stop-losses now disabled for calls). Still relevant for historical data queries.
- **FC-009: Duplicate close logging** — `_closed_today` dedup resets on cold starts. Severity: medium (inflates trade counts, may cause duplicate Alpaca orders). Investigation needed on whether duplicates are log-only or order-level.

## Next Steps

1. **Monitor Friday roll execution** — check Cloud Logging for `call_roll_*` events after first scheduled run
2. **Monitor profit-taking changes** — compare hold times and P/L per trade over next week vs baselines above
3. **FC-008** — fix stop-loss mislabeling (plan + implement)
4. **FC-009** — fix duplicate close logging (plan + implement)
5. **Execute BQ call_rolls view** — SQL is in `docs/bigquery/views.sql` but needs to be run in BQ console
6. **Integrate earnings log enrichment** into PutSeller and CallSeller trade events

## Files Changed

80 files changed, +2,083/-111 lines (includes 53 file renames from docs reorg)

## Configuration Changes Required

All configuration has been applied:
- `finnhub-api-key` in Secret Manager, injected into Cloud Run
- `rolling.enabled: true` in settings.yaml
- `use_call_stop_loss: false` in settings.yaml
- `profit_taking.min_hold_hours: 4` in settings.yaml
- Raised DTE bands (7→35%, 6→40%, 5→35%, 4→45%)
- `options-wheel-roll-friday` Cloud Scheduler job active
- 3 Cloud Run deploys completed
