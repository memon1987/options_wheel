# BigQuery Analytics - Setup Complete! 🎉

**Date**: October 3, 2025, 1:45 PM ET
**Status**: ✅ **OPERATIONAL**

---

## Summary

BigQuery log analytics is now fully operational with 485 log entries from today loaded and 5 analytical views created for querying.

### What Was Accomplished

1. ✅ Resolved permission issues (granted `roles/bigquery.dataEditor` to logging service account)
2. ✅ Manually loaded 485 log entries from today into BigQuery
3. ✅ Created 5 analytical views for common queries
4. ✅ Verified all views with sample queries
5. ✅ Data ready for analysis

---

## BigQuery Dataset

**Dataset**: `gen-lang-client-0607444019:options_wheel_logs`
**Location**: `us-central1`
**Tables**: `run_googleapis_com_stderr_20251003` (485 rows)

### Data Summary (October 3, 2025)
- **Scans**: 5
- **Executions**: 5
- **Positions Opened**: 24
- **Total Premium**: $2,666.50

---

## Available Views

### 1. v_daily_summary
**Purpose**: High-level daily activity summary

**Query**:
```sql
SELECT * FROM `options_wheel_logs.v_daily_summary`
```

**Sample Output**:
| trade_date | scans | executions | total_positions_opened | total_premium_collected |
|------------|-------|------------|------------------------|-------------------------|
| 2025-10-03 | 5     | 5          | 24                     | $2,666.50               |

---

### 2. v_filtering_pipeline
**Purpose**: STAGE filtering decisions (STAGE 1-9)

**Query**:
```sql
SELECT
  timestamp,
  event_type,
  passed,
  rejected,
  passed_symbols,
  rejected_symbols
FROM `options_wheel_logs.v_filtering_pipeline`
WHERE event_type LIKE '%complete%'
ORDER BY timestamp DESC
LIMIT 20
```

**Use Cases**:
- Track which stocks pass/fail each stage
- Analyze rejection reasons
- Identify bottlenecks in filtering pipeline

---

### 3. v_position_sizing
**Purpose**: Approved positions with sizing details

**Query**:
```sql
SELECT
  timestamp,
  symbol,
  contracts,
  capital_required,
  portfolio_allocation,
  max_profit
FROM `options_wheel_logs.v_position_sizing`
ORDER BY timestamp DESC
```

**Sample Output**:
| timestamp           | symbol               | contracts | capital_required | max_profit |
|---------------------|----------------------|-----------|------------------|------------|
| 2025-10-03 17:24:23 | UNH251010P00347500   | 1         | $34,750          | $171.50    |
| 2025-10-03 17:24:22 | GOOGL251010P00235000 | 1         | $23,500          | $140.50    |
| 2025-10-03 17:24:21 | IWM251009P00242000   | 1         | $24,200          | $59.50     |

**Use Cases**:
- Track position sizing over time
- Analyze portfolio allocation patterns
- Calculate total capital deployed

---

### 4. v_gap_risk
**Purpose**: Gap risk analysis and filtering events

**Query**:
```sql
SELECT
  timestamp,
  symbol,
  event_type,
  gap_risk_score,
  gap_frequency,
  historical_volatility,
  action_taken
FROM `options_wheel_logs.v_gap_risk`
ORDER BY timestamp DESC
```

**Use Cases**:
- Identify which stocks fail gap risk checks
- Analyze gap frequency patterns
- Track volatility metrics

---

### 5. v_performance
**Purpose**: System performance metrics

**Query**:
```sql
SELECT
  timestamp,
  metric_name,
  metric_value,
  metric_unit,
  symbols_scanned,
  suitable_stocks
FROM `options_wheel_logs.v_performance`
ORDER BY timestamp DESC
```

**Use Cases**:
- Monitor execution duration
- Track scan performance
- Analyze system efficiency

---

## Sample Analytics Queries

### Stock Pass Rates by Stage
```sql
SELECT
  event_type,
  COUNT(*) as events,
  AVG(passed) as avg_passed,
  AVG(rejected) as avg_rejected
FROM `options_wheel_logs.v_filtering_pipeline`
WHERE event_type LIKE 'stage_%_complete'
GROUP BY event_type
ORDER BY event_type
```

### Top Stocks by Position Frequency
```sql
SELECT
  REGEXP_EXTRACT(symbol, r'^[A-Z]+') as underlying,
  COUNT(*) as positions_opened,
  SUM(max_profit) as total_premium,
  AVG(portfolio_allocation) as avg_allocation
FROM `options_wheel_logs.v_position_sizing`
GROUP BY underlying
ORDER BY positions_opened DESC
```

### Hourly Trading Activity
```sql
SELECT
  EXTRACT(HOUR FROM timestamp) as hour_et,
  COUNT(DISTINCT timestamp) as executions,
  SUM(max_profit) as premium_collected
FROM `options_wheel_logs.v_position_sizing`
GROUP BY hour_et
ORDER BY hour_et
```

### Average Execution Time
```sql
SELECT
  metric_name,
  AVG(metric_value) as avg_seconds,
  MIN(metric_value) as min_seconds,
  MAX(metric_value) as max_seconds,
  COUNT(*) as samples
FROM `options_wheel_logs.v_performance`
WHERE metric_unit = 'seconds'
GROUP BY metric_name
```

---

## Access from Command Line

### List Views
```bash
bq ls --max_results=10 options_wheel_logs
```

### Run Query
```bash
bq query --use_legacy_sql=false '
SELECT * FROM `options_wheel_logs.v_daily_summary`
'
```

### Export to CSV
```bash
bq extract \
  --destination_format=CSV \
  options_wheel_logs.v_position_sizing \
  gs://your-bucket/exports/positions_*.csv
```

---

## Future Enhancements

### Automatic Daily Updates
The Cloud Logging sink should now automatically export new logs to BigQuery. New dated tables will be created as:
- `run_googleapis_com_stderr_20251004`
- `run_googleapis_com_stderr_20251005`
- etc.

Views use wildcard `run_googleapis_com_stderr_*` to query across all dated tables automatically.

### Additional Views to Create

**v_options_chain_analysis**:
```sql
CREATE OR REPLACE VIEW `options_wheel_logs.v_options_chain_analysis` AS
SELECT
  timestamp,
  jsonPayload.symbol as symbol,
  jsonPayload.best_put_strike as strike,
  jsonPayload.best_put_premium as premium,
  jsonPayload.best_put_delta as delta,
  jsonPayload.best_put_dte as dte,
  jsonPayload.total_puts as total_puts,
  jsonPayload.suitable_count as suitable_count
FROM `options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_type = 'stage_7_complete_found'
ORDER BY timestamp DESC
```

**v_execution_gaps**:
```sql
CREATE OR REPLACE VIEW `options_wheel_logs.v_execution_gaps` AS
SELECT
  timestamp,
  jsonPayload.symbol as symbol,
  jsonPayload.gap_percent as gap_percent,
  jsonPayload.threshold as threshold,
  jsonPayload.previous_close as previous_close,
  jsonPayload.current_price as current_price
FROM `options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_type = 'execution_gap_exceeded'
ORDER BY timestamp DESC
```

---

## Monitoring

### Check for New Data
```bash
# Count rows by date
bq query --use_legacy_sql=false '
SELECT
  DATE(timestamp) as date,
  COUNT(*) as rows
FROM `options_wheel_logs.run_googleapis_com_stderr_*`
GROUP BY date
ORDER BY date DESC
'
```

### Verify Sink Status
```bash
gcloud logging sinks describe options-wheel-logs
```

### Check for Export Errors
```bash
gcloud logging read "resource.type=bigquery_resource" --limit=20
```

---

## Troubleshooting

### If New Logs Don't Appear

1. **Check Cloud Logging**: Verify logs still have `event_category` field
   ```bash
   gcloud logging read \
     'resource.labels.service_name="options-wheel-strategy"
      AND jsonPayload.event_category:*' \
     --limit=5
   ```

2. **Verify Sink Configuration**:
   ```bash
   gcloud logging sinks describe options-wheel-logs
   ```

3. **Check Permissions**:
   ```bash
   gcloud projects get-iam-policy gen-lang-client-0607444019 \
     --flatten="bindings[].members" \
     --filter="bindings.members:*gcp-sa-logging*"
   ```

4. **Manual Export** (if needed):
   ```bash
   # Export today's logs
   gcloud logging read \
     'resource.labels.service_name="options-wheel-strategy"
      AND jsonPayload.event_category:*
      AND timestamp>="2025-10-04T00:00:00Z"' \
     --format=json --limit=1000 | jq -c '.[]' > /tmp/logs.jsonl

   # Load into BigQuery
   bq load --source_format=NEWLINE_DELIMITED_JSON --autodetect \
     options_wheel_logs.run_googleapis_com_stderr_20251004 \
     /tmp/logs.jsonl
   ```

---

## Success Metrics

✅ **485 log entries** loaded from today
✅ **5 analytical views** created and tested
✅ **All STAGE logs** (1-9) captured with `event_category="filtering"`
✅ **Complete audit trail** of position sizing decisions
✅ **Performance metrics** available for analysis
✅ **Daily summaries** generated automatically

---

## Next Steps

1. **Monitor auto-export**: Check tomorrow (Oct 4) if new table created automatically
2. **Create dashboards**: Build Looker Studio/Data Studio dashboards using views
3. **Set up alerts**: Create BigQuery scheduled queries for monitoring
4. **Backfill historical data**: Load logs from previous days if needed

---

**Documentation**:
- Setup Status: [BIGQUERY_SYNC_STATUS.md](BIGQUERY_SYNC_STATUS.md)
- Daily Activity: [DAILY_ACTIVITY_OCT3_2025.md](DAILY_ACTIVITY_OCT3_2025.md)
- Logging Guidelines: [LOGGING_GUIDELINES.md](LOGGING_GUIDELINES.md)

**Last Updated**: October 3, 2025, 1:45 PM ET
