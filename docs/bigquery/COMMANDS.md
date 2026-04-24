# BigQuery Quick Commands

**Quick reference for common BigQuery operations**

---

## View Management

### List All Views
```bash
bq ls options_wheel_logs
```

### Describe a View
```bash
bq show --view options_wheel_logs.daily_operations_summary
```

### Drop a View
```bash
bq rm -f -t gen-lang-client-0607444019:options_wheel_logs.view_name
```

### Drop All Views (if needed)
```bash
bq rm -f -t gen-lang-client-0607444019:options_wheel_logs.daily_operations_summary
bq rm -f -t gen-lang-client-0607444019:options_wheel_logs.hourly_scan_execution_timeline
bq rm -f -t gen-lang-client-0607444019:options_wheel_logs.filtering_stage_summary
bq rm -f -t gen-lang-client-0607444019:options_wheel_logs.symbol_filtering_journey
bq rm -f -t gen-lang-client-0607444019:options_wheel_logs.stage1_price_volume_analysis
bq rm -f -t gen-lang-client-0607444019:options_wheel_logs.stage7_options_chain_analysis
bq rm -f -t gen-lang-client-0607444019:options_wheel_logs.trades_executed
bq rm -f -t gen-lang-client-0607444019:options_wheel_logs.execution_cycle_results
bq rm -f -t gen-lang-client-0607444019:options_wheel_logs.errors_all
bq rm -f -t gen-lang-client-0607444019:options_wheel_logs.errors_daily_summary
bq rm -f -t gen-lang-client-0607444019:options_wheel_logs.performance_detailed
bq rm -f -t gen-lang-client-0607444019:options_wheel_logs.backtest_results_complete
```

### Recreate All Views from SQL File
```bash
# Execute each CREATE VIEW statement from the SQL file
bq query --use_legacy_sql=false < docs/bigquery_views_enhanced_complete.sql
```

---

## Quick Queries

### Daily Summary
```bash
bq query --use_legacy_sql=false "
SELECT * FROM \`options_wheel_logs.daily_operations_summary\`
WHERE date_et = CURRENT_DATE('America/New_York')
"
```

### Today's Filtering Funnel
```bash
bq query --use_legacy_sql=false "
SELECT stage_number, stage_name, passed, blocked, found, not_found
FROM \`options_wheel_logs.filtering_stage_summary\`
WHERE date_et = CURRENT_DATE('America/New_York')
ORDER BY stage_number
"
```

### Trace Symbol Journey
```bash
bq query --use_legacy_sql=false "
SELECT timestamp_et, stage_number, stage_result, reason
FROM \`options_wheel_logs.symbol_filtering_journey\`
WHERE date_et = CURRENT_DATE('America/New_York')
  AND symbol = 'AAPL'
ORDER BY timestamp_et, stage_number
"
```

### Recent Errors
```bash
bq query --use_legacy_sql=false "
SELECT timestamp_et, severity, event, symbol
FROM \`options_wheel_logs.errors_all\`
WHERE date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 3 DAY)
ORDER BY timestamp_et DESC
LIMIT 20
"
```

### Hourly Timeline
```bash
bq query --use_legacy_sql=false "
SELECT hour_et, minute_et, event_phase, metric1, metric2
FROM \`options_wheel_logs.hourly_scan_execution_timeline\`
WHERE date_et = CURRENT_DATE('America/New_York')
ORDER BY hour_et, minute_et
"
```

---

## Data Export

### Export to CSV
```bash
bq extract --destination_format CSV \
  'options_wheel_logs.daily_operations_summary' \
  gs://your-bucket/exports/daily_summary_*.csv
```

### Export Query Results to CSV
```bash
bq query --use_legacy_sql=false --format=csv \
  "SELECT * FROM \`options_wheel_logs.daily_operations_summary\`" \
  > daily_summary.csv
```

### Export to JSON
```bash
bq query --use_legacy_sql=false --format=prettyjson \
  "SELECT * FROM \`options_wheel_logs.daily_operations_summary\`" \
  > daily_summary.json
```

---

## Table Operations

### List All Tables and Views
```bash
bq ls --max_results 100 options_wheel_logs
```

### Check Table Size
```bash
bq show --format=prettyjson options_wheel_logs.run_googleapis_com_stderr_20251015
```

### Query Raw Logs
```bash
bq query --use_legacy_sql=false "
SELECT *
FROM \`gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*\`
WHERE _TABLE_SUFFIX = '20251015'
  AND jsonPayload.event_category = 'filtering'
LIMIT 10
"
```

---

## Monitoring Commands

### Count Events by Category
```bash
bq query --use_legacy_sql=false "
SELECT
  jsonPayload.event_category,
  COUNT(*) as count
FROM \`gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*\`
WHERE _TABLE_SUFFIX >= '20251015'
GROUP BY jsonPayload.event_category
ORDER BY count DESC
"
```

### Check Latest Log Timestamp
```bash
bq query --use_legacy_sql=false "
SELECT MAX(timestamp) as latest_log
FROM \`gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*\`
WHERE _TABLE_SUFFIX >= '20251015'
"
```

### View Counts by Table
```bash
bq query --use_legacy_sql=false "
SELECT
  _TABLE_SUFFIX as date,
  COUNT(*) as rows
FROM \`gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*\`
WHERE _TABLE_SUFFIX >= '20251015'
GROUP BY _TABLE_SUFFIX
ORDER BY _TABLE_SUFFIX DESC
"
```

---

## Sink Management

### List Log Sinks
```bash
gcloud logging sinks list
```

### Describe Sink
```bash
gcloud logging sinks describe options-wheel-logs
```

### Update Sink Filter
```bash
gcloud logging sinks update options-wheel-logs \
  --log-filter='resource.type="cloud_run_revision"
    AND resource.labels.service_name="options-wheel-strategy"
    AND jsonPayload.event_category:*'
```

---

## Scheduled Queries (Future)

### Create Daily Summary Scheduled Query
```bash
# Via BigQuery Console: Transfer Service > Create Transfer
# Schedule: Daily at 9am ET
# Query: SELECT * FROM `options_wheel_logs.daily_operations_summary`
# Destination: Email or another table
```

---

## Useful Aliases (Add to ~/.bashrc or ~/.zshrc)

```bash
# Add to shell config
export BQ_PROJECT="gen-lang-client-0607444019"
export BQ_DATASET="options_wheel_logs"

alias bq-views='bq ls $BQ_DATASET'
alias bq-daily='bq query --use_legacy_sql=false "SELECT * FROM \`$BQ_DATASET.daily_operations_summary\` WHERE date_et = CURRENT_DATE(\"America/New_York\")"'
alias bq-funnel='bq query --use_legacy_sql=false "SELECT stage_number, stage_name, passed, blocked FROM \`$BQ_DATASET.filtering_stage_summary\` WHERE date_et = CURRENT_DATE(\"America/New_York\") ORDER BY stage_number"'
alias bq-errors='bq query --use_legacy_sql=false "SELECT timestamp_et, severity, event FROM \`$BQ_DATASET.errors_all\` WHERE date_et = CURRENT_DATE(\"America/New_York\") ORDER BY timestamp_et DESC LIMIT 20"'
```

Then use:
```bash
bq-views      # List all views
bq-daily      # Today's summary
bq-funnel     # Today's filtering funnel
bq-errors     # Recent errors
```

---

## Documentation Links

- [View Summary](BIGQUERY_VIEWS_SUMMARY.md) - Overview of all 12 views
- [Usage Guide](BIGQUERY_VIEWS_USAGE_GUIDE.md) - Detailed examples
- [SQL Definitions](bigquery_views_enhanced_complete.sql) - CREATE VIEW statements
- [Filtering Guide](FILTERING_PIPELINE_MONITORING.md) - Pipeline monitoring
