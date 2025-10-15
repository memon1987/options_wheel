# BigQuery Export Fix - October 15, 2025

## Problem Identified

BigQuery sink was configured to filter on `jsonPayload.event_category=*`, but the application code was logging to `jsonPayload.event` field instead. This caused **zero logs to export to BigQuery** despite the application running successfully for a week.

## Solution Implemented

### Phase 1: Quick Fix (COMPLETED - Oct 15, 2025 04:50 UTC)

Updated BigQuery sink filter to match actual log structure:

```bash
gcloud logging sinks update options-wheel-logs \
  --log-filter='resource.type="cloud_run_revision"
resource.labels.service_name="options-wheel-strategy"
jsonPayload.event:*'
```

**Previous Filter:**
```
resource.type="cloud_run_revision"
resource.labels.service_name="options-wheel-strategy"
jsonPayload.event_category=*
```

**New Filter:**
```
resource.type="cloud_run_revision"
resource.labels.service_name="options-wheel-strategy"
jsonPayload.event:*
```

### Verification

✅ **Sink Updated:** 2025-10-15T04:50:05Z
✅ **Test Log Generated:** 2025-10-15T04:51:07Z
✅ **Log Contains Both Fields:**
- `jsonPayload.event`: "market_scan_completed"
- `jsonPayload.event_category`: "system"

⏳ **BigQuery Export:** Waiting for propagation (5-10 minutes typical)

## Monitoring Commands

### Check if logs are flowing to BigQuery:

```bash
bq query --use_legacy_sql=false '
SELECT
  COUNT(*) as log_count,
  MIN(timestamp) as first_log,
  MAX(timestamp) as latest_log
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
'
```

### Check recent scan events:

```bash
bq query --use_legacy_sql=false '
SELECT
  timestamp,
  JSON_VALUE(jsonPayload, "$.event") as event,
  JSON_VALUE(jsonPayload, "$.put_opportunities") as opportunities
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr`
WHERE JSON_VALUE(jsonPayload, "$.event") = "market_scan_completed"
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY timestamp DESC
LIMIT 10
'
```

### Verify sink configuration:

```bash
gcloud logging sinks describe options-wheel-logs
```

## Expected Timeline

- **T+0 min:** Sink filter updated
- **T+1 min:** New logs generated (test scan)
- **T+5-10 min:** Logs appear in BigQuery (propagation delay)
- **T+60 min:** Full backfill of recent logs (typical)

## Phase 2: Proper Fix (PENDING)

### Objective
Update `deploy/cloud_run_server.py` to use `event_category` consistently with the standardized logging functions from `src/utils/logging_events.py`.

### Current State
- Code uses direct `logger.info()` calls with `event` field
- Some logs already have `event_category` (from using standardized functions)
- Mix of both approaches creates inconsistency

### Recommended Approach
1. Audit all `logger.info()` calls in `cloud_run_server.py`
2. Replace with standardized functions where applicable:
   - `log_system_event()` for system events
   - `log_performance_metric()` for timing/metrics
   - `log_error_event()` for errors
3. For logs that must use direct logging, add `event_category` parameter

### Example Migration

**Before:**
```python
logger.info("Batch order selection complete",
           total_opportunities=len(opportunities),
           selected_count=len(selected_opportunities),
           initial_bp=available_buying_power,
           bp_to_use=available_buying_power - remaining_bp)
```

**After (Option 1 - Standardized Function):**
```python
log_system_event(
    logger,
    event_type="batch_order_selection_completed",
    status="completed",
    total_opportunities=len(opportunities),
    selected_count=len(selected_opportunities),
    initial_bp=available_buying_power,
    bp_to_use=available_buying_power - remaining_bp
)
```

**After (Option 2 - Add event_category):**
```python
logger.info("Batch order selection complete",
           event_category="system",
           event_type="batch_order_selection_completed",
           total_opportunities=len(opportunities),
           selected_count=len(selected_opportunities),
           initial_bp=available_buying_power,
           bp_to_use=available_buying_power - remaining_bp)
```

### Benefits of Proper Fix
1. **Consistency:** All logs follow same structure
2. **Documentation:** LOGGING_REFERENCE.md matches actual implementation
3. **Queryability:** Can filter by `event_category` in BigQuery
4. **Maintainability:** Standardized functions enforce field consistency

## Troubleshooting

### Issue: Logs not appearing in BigQuery after 10 minutes

**Check 1 - Logs exist in Cloud Logging:**
```bash
gcloud logging read 'resource.labels.service_name="options-wheel-strategy" AND jsonPayload.event:*' \
  --limit=5 --format=json --freshness=30m
```

**Check 2 - Sink filter is correct:**
```bash
gcloud logging sinks describe options-wheel-logs --format="value(filter)"
```

**Check 3 - Service account has permissions:**
```bash
gcloud projects get-iam-policy gen-lang-client-0607444019 \
  --flatten="bindings[].members" \
  --format="table(bindings.role)" \
  --filter="bindings.members:service-799970961417@gcp-sa-logging.iam.gserviceaccount.com"
```
Expected: `roles/bigquery.dataEditor`

**Check 4 - BigQuery dataset exists:**
```bash
bq ls gen-lang-client-0607444019:options_wheel_logs
```

**Check 5 - Check for export errors:**
```bash
gcloud logging read 'resource.type="bigquery_resource"
  AND protoPayload.serviceName="bigquery.googleapis.com"
  AND protoPayload.status.message:*error*' \
  --limit=10 --format=json --freshness=1h
```

### Issue: Export working but slow

This is **normal**. Cloud Logging → BigQuery export typically has:
- **Best case:** 2-3 minutes
- **Typical:** 5-10 minutes
- **Worst case:** Up to 30 minutes during high load

To verify export is working (even if delayed):
```bash
# Check logs from 1 hour ago (should be fully exported)
bq query --use_legacy_sql=false '
SELECT COUNT(*) FROM `options_wheel_logs.run_googleapis_com_stderr`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND timestamp < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
'
```

## Related Documentation

- [LOGGING_REFERENCE.md](LOGGING_REFERENCE.md) - Complete logging reference
- [bigquery_views.sql](bigquery_views.sql) - BigQuery view definitions
- [LOGGING_GUIDELINES.md](LOGGING_GUIDELINES.md) - Logging best practices

## Status

- ✅ **Phase 1 Complete:** Sink filter updated
- ⏳ **Verification Pending:** Waiting for first exports (5-10 min)
- 📋 **Phase 2 Pending:** Code migration to use event_category consistently
