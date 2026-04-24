# BigQuery Logging Setup - Complete Guide

## Overview

This guide shows how to export Cloud Run logs to BigQuery with **fully unpacked JSON fields** for easy SQL queries.

### What You'll Get

**Before (Nested JSON):**
```sql
-- Hard to query
SELECT jsonPayload.symbol, jsonPayload.premium
FROM logs
```

**After (Unpacked Columns):**
```sql
-- Easy to query!
SELECT symbol, premium, strike_price, success
FROM logs
WHERE event_category = 'trade'
```

---

## Step 1: Create BigQuery Dataset (Cloud Console)

1. Go to BigQuery: https://console.cloud.google.com/bigquery
2. Click **Create Dataset**
   - Dataset ID: `options_wheel_logs`
   - Location: `us-central1` (same as Cloud Run)
   - Default table expiration: None (keep forever)
3. Click **Create Dataset**

---

## Step 2: Create Log Sink with Schema

### Option A: Using Cloud Console (Recommended)

1. Go to **Logging** → **Log Router**: https://console.cloud.google.com/logs/router
2. Click **Create Sink**

**Sink Configuration:**
```
Sink name: cloud-run-to-bigquery
Sink description: Export structured logs to BigQuery with unpacked schema
```

**Sink Destination:**
```
Sink service: BigQuery dataset
BigQuery dataset: options_wheel_logs
Use partitioned tables: ✓ Checked
Partition by: Day
```

**Include logs filter:**
```
resource.type="cloud_run_revision"
resource.labels.service_name="options-wheel-strategy"
jsonPayload.event_category=~"trade|risk|performance|error|system|position|backtest"
```

**Advanced Options:**
- ✓ Use partitioned tables
- ✓ Use the default table schema

3. Click **Create Sink**

### Option B: Using gcloud CLI

```bash
gcloud logging sinks create cloud-run-to-bigquery \
  bigquery.googleapis.com/projects/gen-lang-client-0607444019/datasets/options_wheel_logs \
  --log-filter='resource.type="cloud_run_revision"
    resource.labels.service_name="options-wheel-strategy"
    jsonPayload.event_category=~"trade|risk|performance|error|system|position|backtest"' \
  --use-partitioned-tables
```

---

## Step 3: Understanding BigQuery Schema

### Automatic Schema Detection

BigQuery **automatically creates columns** from your JSON fields!

**Your Log:**
```json
{
  "event_category": "trade",
  "event_type": "put_sale_executed",
  "symbol": "AMD251003P00155000",
  "strategy": "sell_put",
  "success": true,
  "underlying": "AMD",
  "strike_price": 155.0,
  "premium": 0.74,
  "contracts": 1,
  "order_id": "abc123"
}
```

**BigQuery Table Schema (auto-created):**
```
cloud_run_logs_YYYYMMDD
├── timestamp (TIMESTAMP)
├── severity (STRING)
├── textPayload (STRING)
├── jsonPayload (RECORD) - Contains all fields below:
│   ├── event_category (STRING)
│   ├── event_type (STRING)
│   ├── symbol (STRING)
│   ├── strategy (STRING)
│   ├── success (BOOLEAN)
│   ├── underlying (STRING)
│   ├── strike_price (FLOAT)
│   ├── premium (FLOAT)
│   ├── contracts (INTEGER)
│   └── order_id (STRING)
├── resource (RECORD)
│   ├── type (STRING)
│   └── labels (RECORD)
└── ... other Cloud Logging fields
```

### Querying Unpacked Fields

**Simple queries work directly:**
```sql
-- All trade events
SELECT
  timestamp,
  jsonPayload.symbol,
  jsonPayload.premium,
  jsonPayload.success
FROM `gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*`
WHERE jsonPayload.event_category = 'trade'
```

---

## Step 4: Create Materialized Views (Recommended)

For even easier querying, create views that flatten the data:

### View 1: Trades (Fully Flattened)

```sql
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.trades` AS
SELECT
  timestamp,
  DATE(timestamp) as trade_date,
  jsonPayload.event_type,
  jsonPayload.symbol,
  jsonPayload.underlying,
  jsonPayload.strategy,
  CAST(jsonPayload.strike_price AS FLOAT64) as strike_price,
  CAST(jsonPayload.premium AS FLOAT64) as premium,
  CAST(jsonPayload.contracts AS INT64) as contracts,
  jsonPayload.success,
  jsonPayload.order_id,
  CAST(jsonPayload.collateral_required AS FLOAT64) as collateral_required,
  CAST(jsonPayload.limit_price AS FLOAT64) as limit_price
FROM `gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*`
WHERE jsonPayload.event_category = 'trade'
  AND jsonPayload.event_type IN ('put_sale_executed', 'call_sale_executed', 'position_closed');
```

**Now query is super simple:**
```sql
SELECT * FROM `options_wheel_logs.trades`
WHERE trade_date >= '2025-01-01'
  AND underlying = 'AMD';
```

### View 2: Risk Events

```sql
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.risk_events` AS
SELECT
  timestamp,
  DATE(timestamp) as event_date,
  jsonPayload.event_type,
  jsonPayload.symbol,
  jsonPayload.risk_type,
  jsonPayload.action_taken,
  CAST(jsonPayload.gap_percent AS FLOAT64) as gap_percent,
  CAST(jsonPayload.threshold AS FLOAT64) as threshold,
  jsonPayload.reason
FROM `gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*`
WHERE jsonPayload.event_category = 'risk';
```

### View 3: Performance Metrics

```sql
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.performance_metrics` AS
SELECT
  timestamp,
  DATE(timestamp) as metric_date,
  jsonPayload.metric_name,
  CAST(jsonPayload.metric_value AS FLOAT64) as metric_value,
  jsonPayload.metric_unit,
  CAST(jsonPayload.symbols_scanned AS INT64) as symbols_scanned,
  CAST(jsonPayload.opportunities_found AS INT64) as opportunities_found
FROM `gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*`
WHERE jsonPayload.event_category = 'performance';
```

### View 4: Errors

```sql
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.errors` AS
SELECT
  timestamp,
  DATE(timestamp) as error_date,
  severity,
  jsonPayload.error_type,
  jsonPayload.error_message,
  jsonPayload.component,
  jsonPayload.recoverable,
  jsonPayload.symbol,
  CAST(jsonPayload.required AS FLOAT64) as required_amount,
  CAST(jsonPayload.available AS FLOAT64) as available_amount
FROM `gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*`
WHERE jsonPayload.event_category = 'error'
  OR severity IN ('ERROR', 'CRITICAL');
```

### View 5: System Events

```sql
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.system_events` AS
SELECT
  timestamp,
  DATE(timestamp) as event_date,
  jsonPayload.event_type,
  jsonPayload.status,
  CAST(jsonPayload.duration_seconds AS FLOAT64) as duration_seconds,
  CAST(jsonPayload.actions_taken AS INT64) as actions_taken,
  CAST(jsonPayload.new_positions AS INT64) as new_positions,
  CAST(jsonPayload.closed_positions AS INT64) as closed_positions
FROM `gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*`
WHERE jsonPayload.event_category = 'system';
```

---

## Step 5: Example Queries

### Trade Performance Analysis

```sql
-- Daily trade summary
SELECT
  trade_date,
  underlying,
  strategy,
  COUNT(*) as total_trades,
  SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_trades,
  AVG(premium) as avg_premium,
  SUM(premium * contracts * 100) as total_premium_collected
FROM `options_wheel_logs.trades`
WHERE trade_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY trade_date, underlying, strategy
ORDER BY trade_date DESC, total_premium_collected DESC;
```

### Gap Risk Analysis

```sql
-- Stocks with frequent gap events
SELECT
  symbol,
  COUNT(*) as gap_events,
  AVG(gap_percent) as avg_gap,
  MAX(gap_percent) as max_gap,
  COUNT(CASE WHEN action_taken = 'trade_blocked' THEN 1 END) as trades_blocked
FROM `options_wheel_logs.risk_events`
WHERE risk_type = 'gap_risk'
  AND event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY symbol
ORDER BY gap_events DESC;
```

### Error Rate Monitoring

```sql
-- Error rate by component
SELECT
  component,
  error_type,
  COUNT(*) as error_count,
  SUM(CASE WHEN recoverable THEN 1 ELSE 0 END) as recoverable_errors,
  SUM(CASE WHEN NOT recoverable THEN 1 ELSE 0 END) as critical_errors
FROM `options_wheel_logs.errors`
WHERE error_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY component, error_type
ORDER BY error_count DESC;
```

### Performance Tracking

```sql
-- Average scan duration over time
SELECT
  metric_date,
  AVG(metric_value) as avg_duration_seconds,
  AVG(symbols_scanned) as avg_symbols,
  AVG(opportunities_found) as avg_opportunities
FROM `options_wheel_logs.performance_metrics`
WHERE metric_name = 'market_scan_duration'
  AND metric_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY metric_date
ORDER BY metric_date DESC;
```

### Win Rate by Symbol

```sql
-- Calculate win rate for each underlying symbol
WITH trade_outcomes AS (
  SELECT
    underlying,
    strategy,
    success,
    premium * contracts * 100 as premium_value
  FROM `options_wheel_logs.trades`
  WHERE trade_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
    AND event_type = 'put_sale_executed'
)
SELECT
  underlying,
  COUNT(*) as total_trades,
  SUM(CASE WHEN success THEN 1 ELSE 0 END) as winning_trades,
  ROUND(SUM(CASE WHEN success THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as win_rate_pct,
  SUM(premium_value) as total_premium
FROM trade_outcomes
GROUP BY underlying
ORDER BY win_rate_pct DESC;
```

---

## Step 6: Cost Optimization

### Partitioned Tables

Your sink is configured to create **daily partitioned tables**:
- Table name pattern: `cloud_run_logs_YYYYMMDD`
- Queries only scan relevant days
- **Huge cost savings** for date-filtered queries

**Example - Cost Optimized:**
```sql
-- Only scans last 7 days (cheap)
SELECT * FROM `options_wheel_logs.cloud_run_logs_*`
WHERE _TABLE_SUFFIX BETWEEN
  FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY))
  AND FORMAT_DATE('%Y%m%d', CURRENT_DATE())
  AND jsonPayload.event_category = 'trade';
```

### Query Cost Estimation

Before running a query, check cost:
1. Click "MORE" → "Query settings"
2. Enable "Enable cache" (free repeated queries)
3. See "Bytes processed" estimate

**Typical Costs:**
- First 1TB/month: **FREE**
- After 1TB: $5/TB
- Your monthly usage: Estimated <100GB = **FREE**

---

## Step 7: Create Dashboard (Optional)

Use **Looker Studio** (free) to visualize:

1. Go to: https://lookerstudio.google.com
2. Create → Data Source → BigQuery
3. Select: `options_wheel_logs.trades` view
4. Create charts:
   - Line chart: Premium collected over time
   - Bar chart: Trades by symbol
   - Scorecard: Win rate %
   - Table: Recent trades

---

## Verification

Test that logs are flowing:

```sql
-- Check recent logs
SELECT
  timestamp,
  jsonPayload.event_category,
  jsonPayload.event_type,
  jsonPayload.symbol
FROM `gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*`
ORDER BY timestamp DESC
LIMIT 10;
```

If you see data, you're all set! 🎉

---

## Troubleshooting

**No tables created?**
- Wait 10-15 minutes for first logs
- Check sink filter matches your logs
- Verify Cloud Run service is generating logs

**Schema errors?**
- Check `_bqlog_errors` table for mismatches
- Ensure consistent data types (don't mix string/number)

**High costs?**
- Use partitioned table suffixes in WHERE clause
- Enable caching in query settings
- Create materialized views for frequent queries

---

## Summary

✅ **Setup**: 30 minutes one-time
✅ **Code changes**: Already done (structured logging)
✅ **Cost**: ~$5-20/month
✅ **Retention**: Unlimited
✅ **Queries**: Simple SQL, no nested JSON

**Next**: Implement enhanced logging in code (Phase 1 continues...)
