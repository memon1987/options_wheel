# BigQuery Views Usage Guide

## Overview

Fresh BigQuery views created on **October 15, 2025** based on the current logging schema. These views query tables from Oct 15 forward (`_TABLE_SUFFIX >= '20251015'`) to avoid conflicts with older schema versions.

## Available Views

### 1. `daily_execution_summary`
**Purpose**: High-level daily dashboard
**Use case**: Daily monitoring and tracking

```sql
SELECT * FROM `options_wheel_logs.daily_execution_summary`
ORDER BY date_et DESC
LIMIT 7;
```

**Columns**:
- `date_et` - Date in Eastern Time
- `total_scans` - Number of market scans completed
- `total_put_opportunities` - Total put opportunities found
- `total_call_opportunities` - Total call opportunities found
- `avg_scan_duration_seconds` - Average scan time
- `first_event_utc` / `last_event_utc` - Activity time range

**Example Output** (Oct 15, 2025):
```
date_et: 2025-10-15
total_scans: 1
total_put_opportunities: 8
total_call_opportunities: 0
avg_scan_duration_seconds: 7.99
```

---

### 2. `scan_details`
**Purpose**: Detailed scan-by-scan results
**Use case**: Analyze individual scan performance

```sql
SELECT
  timestamp_et,
  hour_et,
  put_opportunities,
  call_opportunities,
  duration_seconds,
  stored_for_execution
FROM `options_wheel_logs.scan_details`
WHERE date_et = CURRENT_DATE('America/New_York')
ORDER BY timestamp_et DESC;
```

**Columns**:
- `timestamp_et` - Scan timestamp (Eastern Time)
- `hour_et` - Hour of day (0-23)
- `put_opportunities` / `call_opportunities` - Opportunities found
- `total_opportunities` - Combined total
- `duration_seconds` - Scan execution time
- `stored_for_execution` - Whether opportunities were saved for trading
- `blob_path` - GCS path to opportunity data

**Use Cases**:
- Track hourly scan performance (6 scans per day: 10am-3pm)
- Identify slow scans
- Verify opportunity storage

---

### 3. `filtering_pipeline`
**Purpose**: Stage-by-stage filtering analysis
**Use case**: Understand which stocks pass/fail at each stage

```sql
-- See which stocks passed/failed stage 7
SELECT
  symbol,
  stage_result,
  COUNT(*) as occurrences
FROM `options_wheel_logs.filtering_pipeline`
WHERE date_et = CURRENT_DATE('America/New_York')
  AND stage_number = 7
GROUP BY symbol, stage_result
ORDER BY occurrences DESC;
```

**Columns**:
- `timestamp_et` - Event timestamp
- `event_type` - Stage event (e.g., `stage_7_complete_found`)
- `symbol` - Stock symbol
- `stage_number` - Filter stage (1-9)
- `stage_result` - PASSED / BLOCKED / UNKNOWN
- `reason` - Why stock was blocked (if applicable)
- `price`, `avg_volume`, `volatility` - Stock metrics
- `total_puts_in_chain` - Available put contracts
- `min_premium`, `target_dte` - Option criteria

**Use Cases**:
- Debug why a stock was filtered out
- Analyze filtering effectiveness by stage
- Identify stocks that consistently fail certain stages

**Example Query - Stock Filtering Analysis**:
```sql
SELECT
  symbol,
  stage_number,
  stage_result,
  reason,
  price,
  avg_volume
FROM `options_wheel_logs.filtering_pipeline`
WHERE date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
  AND symbol = 'NVDA'
ORDER BY timestamp_et DESC
LIMIT 20;
```

---

### 4. `performance_metrics`
**Purpose**: All performance and timing metrics
**Use case**: Performance optimization and analysis

```sql
-- Scan duration trend
SELECT
  date_et,
  AVG(CASE WHEN metric_name = 'market_scan_duration' THEN metric_value END) as avg_duration,
  MAX(CASE WHEN metric_name = 'market_scan_duration' THEN metric_value END) as max_duration
FROM `options_wheel_logs.performance_metrics`
GROUP BY date_et
ORDER BY date_et DESC;
```

**Columns**:
- `metric_name` - Metric identifier (e.g., `market_scan_duration`)
- `metric_value` - Numeric value
- `metric_unit` - Unit (seconds, count, etc.)
- `opportunities_found` - Opportunities discovered
- `symbols_scanned` - Total symbols evaluated
- `suitable_stocks` - Stocks passing initial filters
- `avg_score` - Average opportunity score
- `avg_annual_return` - Average projected return

**Available Metrics**:
- `market_scan_duration` - Full scan time in seconds
- `put_opportunities_discovered` - Put opportunities count
- `call_opportunities_discovered` - Call opportunities count

**Use Cases**:
- Track scan performance over time
- Identify performance regressions
- Analyze opportunity quality (avg_score, avg_annual_return)

---

## Common Queries

### Daily Activity Summary
```sql
SELECT
  date_et,
  total_scans,
  total_put_opportunities,
  avg_scan_duration_seconds,
  ROUND(total_put_opportunities / NULLIF(total_scans, 0), 2) as avg_opps_per_scan
FROM `options_wheel_logs.daily_execution_summary`
WHERE date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
ORDER BY date_et DESC;
```

### Hourly Scan Pattern
```sql
SELECT
  hour_et,
  COUNT(*) as scan_count,
  AVG(put_opportunities) as avg_puts,
  AVG(duration_seconds) as avg_duration
FROM `options_wheel_logs.scan_details`
WHERE date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
GROUP BY hour_et
ORDER BY hour_et;
```

### Stock Filtering Funnel
```sql
SELECT
  stage_number,
  COUNT(DISTINCT symbol) as unique_symbols,
  COUNT(*) as total_events,
  SUM(CASE WHEN stage_result = 'PASSED' THEN 1 ELSE 0 END) as passed,
  SUM(CASE WHEN stage_result = 'BLOCKED' THEN 1 ELSE 0 END) as blocked
FROM `options_wheel_logs.filtering_pipeline`
WHERE date_et = CURRENT_DATE('America/New_York')
GROUP BY stage_number
ORDER BY stage_number;
```

### Most Filtered Stocks
```sql
SELECT
  symbol,
  COUNT(*) as filter_events,
  SUM(CASE WHEN stage_result = 'BLOCKED' THEN 1 ELSE 0 END) as times_blocked,
  SUM(CASE WHEN stage_result = 'PASSED' THEN 1 ELSE 0 END) as times_passed,
  ROUND(100.0 * SUM(CASE WHEN stage_result = 'BLOCKED' THEN 1 ELSE 0 END) / COUNT(*), 1) as block_rate_pct
FROM `options_wheel_logs.filtering_pipeline`
WHERE date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
  AND symbol IS NOT NULL
GROUP BY symbol
HAVING times_blocked > 0
ORDER BY times_blocked DESC
LIMIT 20;
```

## Schema Notes

### Date Range
- All views filter `_TABLE_SUFFIX >= '20251015'`
- Only queries tables from October 15, 2025 forward
- Older tables (before Oct 15) have different schemas and are excluded

### Timezone Handling
- All timestamps stored in UTC
- Views provide both UTC (`timestamp_utc`) and ET (`timestamp_et`, `date_et`)
- Use `date_et` for daily aggregations aligned with trading hours

### Missing Fields
- Execution fields (`trades_executed`, `opportunities_evaluated`) will appear once executions run
- Backtest view not created yet (no backtest data in current logs)
- Trade-specific fields (strike_price, premium, contracts) will be added when trades occur

## Maintenance

### Adding New Fields
When new fields are added to logging:
1. New fields automatically appear in `_20251015` and later tables
2. Update view definitions in `docs/bigquery_views_production.sql`
3. Recreate affected views with `bq query` command

### Extending Date Range
To include older data, update `_TABLE_SUFFIX` filter:
```sql
WHERE _TABLE_SUFFIX >= '20251001'  -- Include October 1 onward
```

Note: Older tables may have different schemas, causing field mismatches.

## Troubleshooting

### Error: Field does not exist
- Means the field doesn't exist across ALL tables in the wildcard range
- Solution: Use `SAFE_CAST()` or query specific dated tables
- Example: `SAFE_CAST(jsonPayload.new_field AS INT64)`

### Empty Results
- Check if logs exist for the date range: `SELECT COUNT(*) FROM run_googleapis_com_stderr_20251015`
- Verify event_category filter matches your logs
- Check `_TABLE_SUFFIX` is set correctly

### Performance Issues
- Add `LIMIT` clauses for testing
- Use `date_et` filters to reduce scan size
- Consider partitioning if querying large date ranges

## Next Steps

Once executions and trades start running:
1. Add `execution_details` view for trade tracking
2. Add `trades` view for individual trade analysis
3. Add `backtest_results` view when backtests are logged
4. Create daily/weekly aggregation tables for faster queries
