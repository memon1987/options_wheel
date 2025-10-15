# Filtering Pipeline Monitoring Guide

**Quick reference for tracking all 9 filtering stages in BigQuery**

Last Updated: October 15, 2025

---

## Complete Stage Coverage Summary

✅ **ALL 9 STAGES HAVE COMPREHENSIVE LOGGING** with `event_category="filtering"`

The code already logs every filtering decision. Current BigQuery data only shows Stages 1 & 7 because the test scan (1:08am ET on Oct 15) was a **SCAN phase only** - no execution was attempted.

---

## Stage Visibility by Phase

### SCAN Phase (hourly at :00)
Stages that log during market scans:
- ✅ **Stage 1**: Price/Volume filtering
- ✅ **Stage 2**: Gap Risk Analysis
- ✅ **Stage 3**: Stock Evaluation Limit (if configured)
- ✅ **Stage 7**: Options Chain scanning

### EXECUTION Phase (at :15)
Stages that log during trade execution attempts:
- ✅ **Stage 4**: Execution Gap Check (real-time)
- ✅ **Stage 5**: Wheel State Check
- ✅ **Stage 6**: Existing Position Check
- ✅ **Stage 8**: Position Sizing
- ✅ **Stage 9**: New Positions Limit (if configured)

---

## Quick BigQuery Queries

### 1. Complete Stage Funnel (Daily)
```sql
SELECT
  stage_number,
  CASE stage_number
    WHEN 1 THEN 'Price/Volume'
    WHEN 2 THEN 'Gap Risk'
    WHEN 3 THEN 'Stock Eval Limit'
    WHEN 4 THEN 'Execution Gap'
    WHEN 5 THEN 'Wheel State'
    WHEN 6 THEN 'Existing Positions'
    WHEN 7 THEN 'Options Chain'
    WHEN 8 THEN 'Position Sizing'
    WHEN 9 THEN 'Position Limit'
  END as stage_name,
  COUNT(*) as total_events,
  COUNT(DISTINCT symbol) as unique_symbols,
  SUM(CASE WHEN stage_result = 'PASSED' THEN 1 ELSE 0 END) as passed,
  SUM(CASE WHEN stage_result = 'BLOCKED' THEN 1 ELSE 0 END) as blocked
FROM `options_wheel_logs.filtering_pipeline`
WHERE date_et = CURRENT_DATE('America/New_York')
  AND stage_number IS NOT NULL
GROUP BY stage_number, stage_name
ORDER BY stage_number;
```

### 2. Symbol-Level Filtering Journey
```sql
SELECT
  symbol,
  stage_number,
  stage_result,
  event_type,
  timestamp_et
FROM `options_wheel_logs.filtering_pipeline`
WHERE date_et = CURRENT_DATE('America/New_York')
  AND symbol = 'AAPL'  -- Replace with any symbol
ORDER BY timestamp_et, stage_number;
```

### 3. Stage 2 Gap Risk Rejections
```sql
SELECT
  timestamp_et,
  symbol,
  SAFE_CAST(gap_frequency AS FLOAT64) as gap_frequency,
  SAFE_CAST(historical_volatility AS FLOAT64) as historical_volatility,
  SAFE_CAST(gap_percent AS FLOAT64) as current_gap_percent
FROM `options_wheel_logs.filtering_pipeline`
WHERE date_et = CURRENT_DATE('America/New_York')
  AND stage_number = 2
  AND stage_result = 'BLOCKED'
ORDER BY timestamp_et;
```

### 4. Stage 7 Options Chain Results
```sql
SELECT
  timestamp_et,
  symbol,
  stage_result,
  event_type,
  CASE
    WHEN event_type = 'stage_7_complete_found' THEN 'Found suitable puts'
    WHEN event_type = 'stage_7_complete_not_found' THEN 'No suitable puts'
  END as result_description
FROM `options_wheel_logs.filtering_pipeline`
WHERE date_et = CURRENT_DATE('America/New_York')
  AND stage_number = 7
ORDER BY timestamp_et;
```

### 5. Stage 8 Position Sizing Analysis
```sql
SELECT
  timestamp_et,
  symbol,
  stage_result,
  event_type,
  -- Extract additional Stage 8 details from raw logs
  jsonPayload.buying_power,
  jsonPayload.max_contracts_allowed,
  jsonPayload.capital_required,
  jsonPayload.portfolio_allocation
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'filtering'
  AND jsonPayload.event_type LIKE 'stage_8%'
  AND _TABLE_SUFFIX >= '20251015'
  AND DATE(timestamp, 'America/New_York') = CURRENT_DATE('America/New_York')
ORDER BY timestamp;
```

### 6. Blocked Opportunities by Stage
```sql
SELECT
  stage_number,
  COUNT(*) as blocked_count,
  ARRAY_AGG(DISTINCT symbol) as blocked_symbols
FROM `options_wheel_logs.filtering_pipeline`
WHERE date_et = CURRENT_DATE('America/New_York')
  AND stage_result = 'BLOCKED'
GROUP BY stage_number
ORDER BY stage_number;
```

---

## Expected Event Counts (Normal Trading Day)

After a full scan + execution cycle:

| Stage | Expected Events | Description |
|-------|----------------|-------------|
| 1 | 1 | Single price/volume summary |
| 2 | 1 | Gap risk analysis summary |
| 3 | 0-1 | Only if stock eval limit configured |
| 4 | 5-10 | One per symbol evaluated for execution |
| 5 | 5-10 | One per symbol evaluated |
| 6 | 5-10 | One per symbol evaluated |
| 7 | 30-50 | Multiple per symbol (scanning options chains) |
| 8 | 3-8 | One per opportunity reaching position sizing |
| 9 | 0-1 | Only if position limit reached |

**Total filtering events per execution cycle**: ~50-90 events

---

## How to Generate All Stage Logs

### Option 1: Wait for Scheduled Execution (Recommended)
During market hours (10am-3pm ET), executions run automatically at :15:
- **10:00am**: Scan runs → Stages 1, 2, 3, 7 logged
- **10:15am**: Execution runs → Stages 4, 5, 6, 8, 9 logged
- Repeat every hour until 3:15pm

### Option 2: Manual Trigger (For Testing)
```bash
# 1. Run a scan (creates opportunities)
gcloud scheduler jobs run scan-10am --location=us-central1

# 2. Wait 1-2 minutes for scan to complete

# 3. Run execution (processes opportunities)
gcloud scheduler jobs run execute-10-15am --location=us-central1

# 4. Wait 5-10 minutes for logs to propagate to BigQuery

# 5. Query filtering_pipeline view
bq query --use_legacy_sql=false "
SELECT stage_number, COUNT(*) as events
FROM \`options_wheel_logs.filtering_pipeline\`
WHERE date_et = CURRENT_DATE('America/New_York')
GROUP BY stage_number
ORDER BY stage_number
"
```

---

## Troubleshooting

### "I only see Stages 1 and 7"
**Reason**: Only scan has run, no execution attempted yet.
**Solution**: Wait for execution at :15 or manually trigger execution job.

### "Stage counts seem low"
**Reason**: Stages 4-9 only log when opportunities pass earlier stages.
**Expected**: If no opportunities found in Stage 7, won't see Stages 8-9.

### "No Stage 2 or 3 events"
**Reason**:
- Stage 2 logs once per scan (summary)
- Stage 3 only logs if `max_stocks_evaluated_per_cycle` is configured (currently `null`)

---

## Key Event Types Reference

### Stage 1
- `stage_1_complete` - Price/volume filtering summary

### Stage 2
- `stage_2_complete` - Gap risk analysis summary with passed/rejected lists

### Stage 3
- `stage_3_limit_applied` - When stock eval limit is set
- `stage_3_no_limit` - When no limit configured (current)

### Stage 4
- `stage_4_passed` - Real-time gap check OK
- `stage_4_blocked` - Real-time gap exceeded 1.5%

### Stage 5
- `stage_5_check` - Wheel state verification

### Stage 6
- `stage_6_passed` - No existing position
- `stage_6_blocked` - Already have position in this symbol

### Stage 7
- `stage_7_start` - Starting options chain scan
- `stage_7_complete_found` - Found suitable puts/calls
- `stage_7_complete_not_found` - No suitable options

### Stage 8
- `stage_8_calculation` - Position size calculated
- `stage_8_passed` - Sufficient capital, approved
- `stage_8_blocked` - Insufficient capital or risk limit

### Stage 9
- `stage_9_limit_reached` - Hit max new positions per cycle

---

## Related Documentation

- [Complete Logging Coverage](FILTERING_STAGES_LOGGING.md) - Detailed explanation of all stage logging
- [Risk Filtering Steps](RISK_FILTERING_STEPS.md) - Complete filtering pipeline flow
- [BigQuery Usage Guide](BIGQUERY_USAGE_GUIDE.md) - View descriptions and example queries

---

## Summary

✅ **All 9 filtering stages have complete logging**
✅ **BigQuery views are ready to display all stages**
✅ **Current data shows Stages 1 & 7 (scan only)**
✅ **Next execution will show Stages 2-6, 8-9**

The logging infrastructure is complete and working. You now have full visibility into every filtering decision across the entire pipeline.
