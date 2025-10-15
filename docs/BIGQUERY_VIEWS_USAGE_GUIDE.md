# BigQuery Views - Complete Usage Guide

**Last Updated**: October 15, 2025

## Overview

This guide covers all 13 BigQuery views created for comprehensive Options Wheel Strategy monitoring and analysis.

**Total Views**: 13 (organized into 6 categories)
**Date Range**: October 15, 2025 forward (`_TABLE_SUFFIX >= '20251015'`)

---

## View Categories & Structure

### Category 1: Daily Operations (2 views)
1. `daily_operations_summary` - Executive dashboard
2. `hourly_scan_execution_timeline` - Hour-by-hour breakdown

### Category 2: Risk Filtering (4 views)
3. `filtering_stage_summary` - Stage funnel analysis
4. `symbol_filtering_journey` - Per-symbol paths
5. `stage1_price_volume_analysis` - Price/volume filtering
6. `stage7_options_chain_analysis` - Options chain scanning

### Category 3: Trade Execution (2 views)
7. `trades_executed` - All trades log
8. `execution_cycle_results` - Cycle results

### Category 4: Error Tracking (2 views)
9. `errors_all` - Complete error log
10. `errors_daily_summary` - Daily error dashboard

### Category 5: Performance (1 view)
11. `performance_detailed` - Performance metrics

### Category 6: Backtesting (1 view)
12. `backtest_results_complete` - Backtest results

---

## Common Query Patterns

### Quick Health Check
```sql
-- Daily summary for last 7 days
SELECT
  date_et,
  total_scans,
  total_put_opportunities,
  total_executions,
  total_errors
FROM `options_wheel_logs.daily_operations_summary`
WHERE date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
ORDER BY date_et DESC;
```

### Weekly Performance Summary
```sql
-- Aggregate stats for current week
SELECT
  DATE_TRUNC(date_et, WEEK) as week_start,
  SUM(total_scans) as weekly_scans,
  SUM(total_put_opportunities) as weekly_opportunities,
  SUM(total_executions) as weekly_executions,
  AVG(avg_scan_duration_sec) as avg_scan_time,
  SUM(total_errors) as weekly_errors
FROM `options_wheel_logs.daily_operations_summary`
WHERE date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 30 DAY)
GROUP BY week_start
ORDER BY week_start DESC;
```

---

## Detailed View Documentation

### VIEW 1: daily_operations_summary

**Purpose**: Executive dashboard for daily/weekly performance tracking

**Columns**:
- `date_et` - Date in ET timezone
- `total_scans` - Number of market scans completed
- `avg_scan_duration_sec` - Average scan duration
- `total_put_opportunities` - Total put opportunities found
- `total_call_opportunities` - Total call opportunities found
- `total_opportunities` - Combined opportunities
- `total_executions` - Number of execution cycles
- `total_errors` - Count of errors
- `error_count` - Errors by severity=ERROR
- `warning_count` - Errors by severity=WARNING

**Example Queries**:

```sql
-- Today's operations summary
SELECT * FROM `options_wheel_logs.daily_operations_summary`
WHERE date_et = CURRENT_DATE('America/New_York');

-- Compare week-over-week
SELECT
  date_et,
  total_put_opportunities,
  LAG(total_put_opportunities) OVER (ORDER BY date_et) as prev_day_opps,
  total_put_opportunities - LAG(total_put_opportunities) OVER (ORDER BY date_et) as change
FROM `options_wheel_logs.daily_operations_summary`
ORDER BY date_et DESC
LIMIT 7;

-- Identify problem days (high errors or low opportunities)
SELECT * FROM `options_wheel_logs.daily_operations_summary`
WHERE total_errors > 5
   OR total_put_opportunities < 3
ORDER BY date_et DESC;
```

---

### VIEW 2: hourly_scan_execution_timeline

**Purpose**: Hour-by-hour breakdown of scans and executions

**Columns**:
- `date_et` - Date in ET timezone
- `hour_et` - Hour (0-23) in ET
- `minute_et` - Minute (0-59)
- `timestamp_et` - Full datetime ET
- `event_phase` - 'SCAN' or 'EXECUTION'
- `metric1` - Put opportunities (SCAN) / NULL (EXECUTION)
- `metric2` - Call opportunities (SCAN) / NULL (EXECUTION)
- `duration_seconds` - Execution time

**Example Queries**:

```sql
-- Verify scheduled runs for today
SELECT
  hour_et,
  minute_et,
  event_phase,
  metric1 as opportunities
FROM `options_wheel_logs.hourly_scan_execution_timeline`
WHERE date_et = CURRENT_DATE('America/New_York')
ORDER BY hour_et, minute_et;

-- Expected: 6 scans at :00 (10am-3pm) + 6 executions at :15

-- Find missing scheduled runs
WITH expected_scans AS (
  SELECT hour FROM UNNEST([10, 11, 12, 13, 14, 15]) as hour
),
actual_scans AS (
  SELECT DISTINCT hour_et
  FROM `options_wheel_logs.hourly_scan_execution_timeline`
  WHERE date_et = CURRENT_DATE('America/New_York')
    AND event_phase = 'SCAN'
)
SELECT e.hour as missing_hour
FROM expected_scans e
LEFT JOIN actual_scans a ON e.hour = a.hour_et
WHERE a.hour_et IS NULL;

-- Opportunity discovery by hour
SELECT
  hour_et,
  AVG(metric1) as avg_put_opps,
  AVG(metric2) as avg_call_opps
FROM `options_wheel_logs.hourly_scan_execution_timeline`
WHERE event_phase = 'SCAN'
  AND date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
GROUP BY hour_et
ORDER BY hour_et;
```

---

### VIEW 3: filtering_stage_summary

**Purpose**: Daily stage-by-stage pass/block rates for all 9 filtering stages

**Columns**:
- `date_et` - Date in ET timezone
- `stage_number` - 1-9
- `stage_name` - Descriptive name
- `total_events` - Total events for this stage
- `unique_symbols` - Distinct symbols processed
- `passed` - Count of PASSED results
- `blocked` - Count of BLOCKED results
- `found` - Count of FOUND results (Stage 7)
- `not_found` - Count of NOT_FOUND results (Stage 7)
- `stage1_passed_count` - Stage 1 specific: stocks passed
- `stage1_rejected_count` - Stage 1 specific: stocks rejected
- `stage1_total_analyzed` - Stage 1 specific: total analyzed

**Example Queries**:

```sql
-- Today's complete filtering funnel
SELECT
  stage_number,
  stage_name,
  total_events,
  unique_symbols,
  passed,
  blocked,
  found,
  not_found
FROM `options_wheel_logs.filtering_stage_summary`
WHERE date_et = CURRENT_DATE('America/New_York')
ORDER BY stage_number;

-- Stage efficiency over time
SELECT
  date_et,
  stage_number,
  stage_name,
  ROUND(passed / NULLIF(passed + blocked, 0) * 100, 1) as pass_rate_pct
FROM `options_wheel_logs.filtering_stage_summary`
WHERE stage_number IN (4, 6, 8)  -- Key execution stages
  AND date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
ORDER BY date_et DESC, stage_number;

-- Identify bottleneck stages
SELECT
  stage_number,
  stage_name,
  AVG(blocked) as avg_blocked_per_day,
  AVG(passed) as avg_passed_per_day,
  ROUND(AVG(blocked) / NULLIF(AVG(blocked + passed), 0) * 100, 1) as block_rate_pct
FROM `options_wheel_logs.filtering_stage_summary`
WHERE date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
GROUP BY stage_number, stage_name
HAVING AVG(blocked + passed) > 0
ORDER BY block_rate_pct DESC;
```

---

### VIEW 4: symbol_filtering_journey

**Purpose**: Per-symbol path through all 9 filtering stages

**Columns**:
- `date_et` - Date in ET timezone
- `timestamp_et` - Exact time of event
- `symbol` - Stock symbol
- `stage_number` - 1-9
- `event_type` - Specific event type
- `event` - Event description
- `stage_result` - PASSED/BLOCKED/FOUND/NOT_FOUND/COMPLETE
- `reason` - Rejection reason (if blocked)

**Example Queries**:

```sql
-- Trace why AAPL wasn't traded today
SELECT
  timestamp_et,
  stage_number,
  stage_result,
  event_type,
  reason
FROM `options_wheel_logs.symbol_filtering_journey`
WHERE date_et = CURRENT_DATE('America/New_York')
  AND symbol = 'AAPL'
ORDER BY timestamp_et, stage_number;

-- All symbols that reached Stage 8 (position sizing)
SELECT DISTINCT
  symbol,
  COUNT(*) as stage_8_attempts
FROM `options_wheel_logs.symbol_filtering_journey`
WHERE date_et = CURRENT_DATE('America/New_York')
  AND stage_number = 8
GROUP BY symbol
ORDER BY stage_8_attempts DESC;

-- Find symbols blocked at each stage
SELECT
  stage_number,
  symbol,
  reason
FROM `options_wheel_logs.symbol_filtering_journey`
WHERE date_et = CURRENT_DATE('America/New_York')
  AND stage_result = 'BLOCKED'
ORDER BY stage_number, symbol;

-- Symbols that passed all filtering stages
WITH all_stages AS (
  SELECT
    symbol,
    MAX(stage_number) as max_stage_reached
  FROM `options_wheel_logs.symbol_filtering_journey`
  WHERE date_et = CURRENT_DATE('America/New_York')
    AND stage_result IN ('PASSED', 'FOUND')
  GROUP BY symbol
)
SELECT * FROM all_stages
WHERE max_stage_reached >= 8
ORDER BY max_stage_reached DESC, symbol;
```

---

### VIEW 5: stage1_price_volume_analysis

**Purpose**: Daily Stage 1 results with passed/rejected symbols

**Columns**:
- `date_et` - Date in ET timezone
- `timestamp_et` - Exact time of scan
- `total_stocks` - Total symbols analyzed
- `passed_count` - Symbols that passed
- `rejected_count` - Symbols rejected
- `pass_rate_pct` - Pass rate percentage
- `passed_symbols` - Array of passed symbols
- `rejected_symbols` - Array of rejected symbols

**Example Queries**:

```sql
-- Today's Stage 1 results
SELECT
  timestamp_et,
  total_stocks,
  passed_count,
  rejected_count,
  pass_rate_pct,
  passed_symbols,
  rejected_symbols
FROM `options_wheel_logs.stage1_price_volume_analysis`
WHERE date_et = CURRENT_DATE('America/New_York');

-- Track which symbols are consistently rejected
SELECT
  rejected_symbol,
  COUNT(*) as times_rejected
FROM `options_wheel_logs.stage1_price_volume_analysis`,
  UNNEST(rejected_symbols) as rejected_symbol
WHERE date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
GROUP BY rejected_symbol
ORDER BY times_rejected DESC;

-- Monitor if universe is shrinking
SELECT
  date_et,
  passed_count,
  LAG(passed_count) OVER (ORDER BY date_et) as prev_day_passed,
  passed_count - LAG(passed_count) OVER (ORDER BY date_et) as change
FROM `options_wheel_logs.stage1_price_volume_analysis`
ORDER BY date_et DESC
LIMIT 14;
```

---

### VIEW 6: stage7_options_chain_analysis

**Purpose**: Options chain scanning results by symbol with rejection reasons

**Columns**:
- `date_et` - Date in ET timezone
- `timestamp_et` - Exact time of scan
- `symbol` - Stock symbol
- `event_type` - stage_7_start/complete_found/complete_not_found
- `result` - SCANNING/FOUND/NOT_FOUND
- `suitable_puts_count` - Number of suitable puts found
- `rejection_reason` - Why no suitable puts

**Example Queries**:

```sql
-- Today's options chain results by symbol
SELECT
  symbol,
  MAX(CASE WHEN result = 'FOUND' THEN 1 ELSE 0 END) as found_puts,
  MAX(suitable_puts_count) as max_suitable_puts,
  STRING_AGG(DISTINCT rejection_reason) as rejection_reasons
FROM `options_wheel_logs.stage7_options_chain_analysis`
WHERE date_et = CURRENT_DATE('America/New_York')
  AND event_type LIKE 'stage_7_complete%'
GROUP BY symbol
ORDER BY found_puts DESC, symbol;

-- Symbols with options availability issues
SELECT
  symbol,
  COUNT(*) as scans,
  SUM(CASE WHEN result = 'NOT_FOUND' THEN 1 ELSE 0 END) as not_found_count,
  ROUND(SUM(CASE WHEN result = 'NOT_FOUND' THEN 1 ELSE 0 END) / COUNT(*) * 100, 1) as not_found_pct
FROM `options_wheel_logs.stage7_options_chain_analysis`
WHERE date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
  AND event_type LIKE 'stage_7_complete%'
GROUP BY symbol
HAVING not_found_pct > 50
ORDER BY not_found_pct DESC;

-- Count rejection reasons across all symbols
SELECT
  rejection_reason,
  COUNT(*) as occurrences
FROM `options_wheel_logs.stage7_options_chain_analysis`
WHERE date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
  AND result = 'NOT_FOUND'
  AND rejection_reason IS NOT NULL
GROUP BY rejection_reason
ORDER BY occurrences DESC;
```

---

### VIEW 7: trades_executed

**Purpose**: All trades with complete details

**Columns**:
- `timestamp_utc` - UTC timestamp
- `timestamp_et` - ET timestamp
- `date_et` - Date in ET
- `event_type` - Trade event type
- `symbol` - Options symbol
- `event` - Event description

**Example Queries**:

```sql
-- All trades today
SELECT * FROM `options_wheel_logs.trades_executed`
WHERE date_et = CURRENT_DATE('America/New_York')
ORDER BY timestamp_et DESC;

-- Trades by date
SELECT
  date_et,
  COUNT(*) as total_trades
FROM `options_wheel_logs.trades_executed`
WHERE date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 30 DAY)
GROUP BY date_et
ORDER BY date_et DESC;
```

---

### VIEW 8: execution_cycle_results

**Purpose**: Results of each execution cycle (every :15)

**Columns**:
- `timestamp_utc` - UTC timestamp
- `timestamp_et` - ET timestamp
- `date_et` - Date in ET
- `hour_et` - Hour in ET
- `status` - Execution status

**Example Queries**:

```sql
-- Today's execution cycles
SELECT
  hour_et,
  timestamp_et,
  status
FROM `options_wheel_logs.execution_cycle_results`
WHERE date_et = CURRENT_DATE('America/New_York')
ORDER BY hour_et;

-- Execution success rate by hour
SELECT
  hour_et,
  COUNT(*) as total_executions,
  SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful
FROM `options_wheel_logs.execution_cycle_results`
WHERE date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
GROUP BY hour_et
ORDER BY hour_et;
```

---

### VIEW 9: errors_all

**Purpose**: Complete error log with context and recovery status

**Columns**:
- `timestamp_utc` - UTC timestamp
- `timestamp_et` - ET timestamp
- `date_et` - Date in ET
- `severity` - ERROR/WARNING/CRITICAL
- `event_type` - Error event type
- `event` - Error description
- `symbol` - Related symbol (if applicable)
- `logger_name` - Logger that recorded error

**Example Queries**:

```sql
-- All errors today
SELECT * FROM `options_wheel_logs.errors_all`
WHERE date_et = CURRENT_DATE('America/New_York')
ORDER BY timestamp_et DESC;

-- Errors by logger component
SELECT
  logger_name,
  severity,
  COUNT(*) as error_count
FROM `options_wheel_logs.errors_all`
WHERE date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
GROUP BY logger_name, severity
ORDER BY error_count DESC;

-- Critical errors requiring attention
SELECT * FROM `options_wheel_logs.errors_all`
WHERE severity = 'CRITICAL'
  AND date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
ORDER BY timestamp_et DESC;
```

---

### VIEW 10: errors_daily_summary

**Purpose**: Daily error counts by type and severity

**Columns**:
- `date_et` - Date in ET timezone
- `total_errors` - Total error count
- `errors` - Count with severity=ERROR
- `warnings` - Count with severity=WARNING
- `critical` - Count with severity=CRITICAL

**Example Queries**:

```sql
-- Error trends over time
SELECT * FROM `options_wheel_logs.errors_daily_summary`
WHERE date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 14 DAY)
ORDER BY date_et DESC;

-- Days with abnormal error counts
SELECT * FROM `options_wheel_logs.errors_daily_summary`
WHERE total_errors > (
  SELECT AVG(total_errors) * 2
  FROM `options_wheel_logs.errors_daily_summary`
)
ORDER BY date_et DESC;
```

---

### VIEW 11: performance_detailed

**Purpose**: All performance metrics with trends

**Columns**:
- `timestamp_utc` - UTC timestamp
- `timestamp_et` - ET timestamp
- `date_et` - Date in ET
- `metric_name` - Name of metric
- `metric_value` - Metric value
- `metric_unit` - Unit of measurement

**Example Queries**:

```sql
-- Today's performance metrics
SELECT
  metric_name,
  AVG(metric_value) as avg_value,
  MIN(metric_value) as min_value,
  MAX(metric_value) as max_value,
  metric_unit
FROM `options_wheel_logs.performance_detailed`
WHERE date_et = CURRENT_DATE('America/New_York')
GROUP BY metric_name, metric_unit;

-- Scan duration trends
SELECT
  date_et,
  AVG(metric_value) as avg_scan_seconds
FROM `options_wheel_logs.performance_detailed`
WHERE metric_name = 'market_scan_duration'
  AND date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 14 DAY)
GROUP BY date_et
ORDER BY date_et;
```

---

### VIEW 12: backtest_results_complete

**Purpose**: Full backtest results with all metrics

**Columns**:
- `timestamp_utc` - UTC timestamp
- `timestamp_et` - ET timestamp
- `date_et` - Date in ET
- `event` - Backtest event
- `event_type` - Event type

**Example Queries**:

```sql
-- All backtest runs
SELECT * FROM `options_wheel_logs.backtest_results_complete`
ORDER BY timestamp_et DESC;

-- Recent backtests
SELECT * FROM `options_wheel_logs.backtest_results_complete`
WHERE date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
ORDER BY timestamp_et DESC;
```

---

## Advanced Query Examples

### Complete Daily Report
```sql
WITH daily_summary AS (
  SELECT * FROM `options_wheel_logs.daily_operations_summary`
  WHERE date_et = CURRENT_DATE('America/New_York')
),
stage_funnel AS (
  SELECT
    stage_number,
    stage_name,
    passed + blocked as total_processed,
    passed,
    blocked
  FROM `options_wheel_logs.filtering_stage_summary`
  WHERE date_et = CURRENT_DATE('America/New_York')
    AND stage_number IN (1, 4, 6, 8)
  ORDER BY stage_number
),
error_summary AS (
  SELECT * FROM `options_wheel_logs.errors_daily_summary`
  WHERE date_et = CURRENT_DATE('America/New_York')
)
SELECT
  'Operations' as section,
  CAST(total_scans AS STRING) as metric,
  'scans' as description
FROM daily_summary
UNION ALL
SELECT
  'Operations',
  CAST(total_put_opportunities AS STRING),
  'put opportunities'
FROM daily_summary
UNION ALL
SELECT
  'Filtering',
  CONCAT(stage_name, ': ', CAST(passed AS STRING), '/', CAST(total_processed AS STRING)),
  'passed/total'
FROM stage_funnel
UNION ALL
SELECT
  'Errors',
  CAST(total_errors AS STRING),
  'total errors'
FROM error_summary;
```

### Weekly Filtering Efficiency Report
```sql
SELECT
  DATE_TRUNC(date_et, WEEK) as week_start,
  stage_name,
  ROUND(AVG(passed / NULLIF(passed + blocked, 0)) * 100, 1) as avg_pass_rate_pct,
  SUM(passed) as total_passed,
  SUM(blocked) as total_blocked
FROM `options_wheel_logs.filtering_stage_summary`
WHERE date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 30 DAY)
  AND stage_number IN (4, 6, 8)
GROUP BY week_start, stage_name, stage_number
ORDER BY week_start DESC, stage_number;
```

---

## Troubleshooting

### No results returned
**Reason**: Data range filter (`_TABLE_SUFFIX >= '20251015'`)
**Solution**: Check if querying dates before Oct 15, 2025

### Field does not exist errors
**Reason**: View designed for fields that appear during execution, not just scans
**Solution**: Wait for execution cycles or manually trigger execution

### Empty filtering stages
**Reason**: Stages 2-6, 8-9 only log during EXECUTION phase
**Solution**: Check `execution_cycle_results` to confirm executions are running

---

## Next Steps

1. **Schedule daily reports** using these queries
2. **Create BigQuery scheduled queries** for automatic dashboards
3. **Set up monitoring alerts** based on error thresholds
4. **Export to Data Studio** for visualization

---

## Related Documentation

- [Enhanced Views Plan](BIGQUERY_ENHANCED_VIEWS_PLAN.md) - Complete view design
- [Filtering Pipeline Monitoring](FILTERING_PIPELINE_MONITORING.md) - Stage-by-stage guide
- [Filtering Stages Logging](FILTERING_STAGES_LOGGING.md) - Complete logging coverage
