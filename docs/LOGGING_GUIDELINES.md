# Logging Guidelines for Options Wheel Strategy

**CRITICAL**: All structured logs MUST include `event_category` to ensure BigQuery export.

---

## 🚨 Required: Always Include event_category

### Why event_category is Required

Our Cloud Logging → BigQuery sink is configured with this filter:
```
resource.labels.service_name="options-wheel-strategy"
jsonPayload.event_category=*
```

**This means**: Logs WITHOUT `event_category` will NOT be exported to BigQuery!

### Event Categories

Use ONE of these standardized categories for every log:

| Category | Use For | Examples |
|----------|---------|----------|
| `system` | Strategy cycles, service events | strategy_cycle_completed, service_started |
| `risk` | Gap detection, filtering, blocking | stock_filtered_by_gap_risk, execution_gap_exceeded |
| `trade` | Trading activity, orders | put_sale_executed, call_sale_executed |
| `performance` | Timing, metrics | market_scan_duration, execution_latency |
| `error` | Errors, failures | api_error, insufficient_funds |
| `position` | Wheel state transitions | position_assigned, wheel_cycle_completed |
| `backtest` | Backtesting events | backtest_completed, backtest_started |
| `filtering` | **NEW** - Filter stage logging | stage_1_complete, stage_2_complete |

---

## ✅ Correct Logging Examples

### Using Standardized Functions (PREFERRED)

```python
from src.utils.logging_events import (
    log_risk_event,
    log_trade_event,
    log_system_event,
    log_performance_metric
)

# Risk event (includes event_category automatically)
log_risk_event(
    logger,
    event_type="stock_filtered_by_gap_risk",
    symbol="AMD",
    risk_type="gap_risk",
    action_taken="stock_excluded",
    gap_risk_score=0.74
)

# Trade event (includes event_category automatically)
log_trade_event(
    logger,
    event_type="put_sale_executed",
    symbol="AMD251003P00155000",
    strategy="sell_put",
    success=True,
    premium=0.74
)
```

### Using Direct logger.info() (ADD event_category MANUALLY)

```python
# ✅ CORRECT - Includes event_category
logger.info("STAGE 1 COMPLETE: Price/Volume filtering",
           event_category="filtering",  # ← REQUIRED!
           total_analyzed=14,
           passed=12,
           rejected=2)

# ❌ WRONG - Missing event_category (will NOT export to BigQuery!)
logger.info("STAGE 1 COMPLETE: Price/Volume filtering",
           total_analyzed=14,
           passed=12,
           rejected=2)
```

---

## 📋 Logging Checklist for New Code

When adding ANY new log statement:

- [ ] **1. Choose appropriate `event_category`** (system, risk, trade, performance, error, position, backtest, filtering)
- [ ] **2. Include `event_category` field** in the log
- [ ] **3. Add descriptive `event` or `event_type` field** (what happened)
- [ ] **4. Include relevant context** (symbol, metrics, reasons)
- [ ] **5. Use consistent naming** (snake_case, descriptive)

---

## 🎯 Template for Filter Stage Logging

**For all 9 risk filtering stages**, use this pattern:

```python
# Stage completion summary
logger.info("STAGE N COMPLETE: Stage description",
           event_category="filtering",  # ← Always include!
           event_type="stage_N_complete",  # ← For querying
           total_input=X,
           passed=Y,
           rejected=Z,
           passed_symbols=["SYM1", "SYM2"],
           rejected_symbols=["SYM3"])

# Stage pass for individual stock
logger.info("STAGE N: Description - PASSED",
           event_category="filtering",
           event_type="stage_N_passed",
           symbol="AAPL",
           metric_1=value1,
           metric_2=value2)

# Stage block for individual stock
logger.info("STAGE N: Description - BLOCKED",
           event_category="filtering",
           event_type="stage_N_blocked",
           symbol="AAPL",
           reason="specific_reason",
           metric_1=value1)
```

### Example for Each Stage

```python
# STAGE 1: Price/Volume
logger.info("STAGE 1 COMPLETE: Price/Volume filtering",
           event_category="filtering",
           event_type="stage_1_complete",
           total_analyzed=14,
           passed=12,
           rejected=2,
           passed_symbols=["AAPL", "MSFT"],
           rejected_symbols=["XYZ", "ABC"])

# STAGE 2: Gap Risk
logger.info("STAGE 2: Gap risk analysis - BLOCKED",
           event_category="filtering",
           event_type="stage_2_blocked",
           symbol="AMD",
           reason="high_gap_frequency",
           gap_frequency=0.206,
           threshold=0.15)

# STAGE 4: Execution Gap
logger.info("STAGE 4: Execution gap check PASSED",
           event_category="filtering",
           event_type="stage_4_passed",
           symbol="MSFT",
           gap_percent=0.45,
           threshold=1.5)

# STAGE 7: Options Chain
logger.info("STAGE 7 COMPLETE: Options chain criteria - puts found",
           event_category="filtering",
           event_type="stage_7_complete",
           symbol="MSFT",
           suitable_puts=7,
           best_strike=410.00,
           best_premium=1.25)
```

---

## 📊 BigQuery Benefits

When you include `event_category`, logs are automatically:

1. **Exported to BigQuery** (5-10 min batch delay)
2. **Organized by category** in dedicated views
3. **Queryable with SQL** for analytics
4. **Stored in partitioned tables** (date-based for cost optimization)

### Query Examples

```sql
-- All filtering events
SELECT * FROM `options_wheel_logs.cloud_run_logs_*`
WHERE jsonPayload.event_category = 'filtering'
  AND DATE(timestamp) = CURRENT_DATE();

-- Stage-by-stage analysis
SELECT
  jsonPayload.event_type,
  COUNT(*) as count
FROM `options_wheel_logs.cloud_run_logs_*`
WHERE jsonPayload.event_category = 'filtering'
GROUP BY jsonPayload.event_type
ORDER BY jsonPayload.event_type;

-- Gap risk rejections
SELECT
  jsonPayload.symbol,
  AVG(CAST(jsonPayload.gap_frequency AS FLOAT64)) as avg_gap_freq
FROM `options_wheel_logs.cloud_run_logs_*`
WHERE jsonPayload.event_category = 'filtering'
  AND jsonPayload.event_type = 'stage_2_blocked'
GROUP BY jsonPayload.symbol;
```

---

## 🔧 How to Update Existing Logs

### Current Issue
Our new STAGE logs don't include `event_category`:

```python
# ❌ Current (will NOT export to BigQuery)
logger.info("STAGE 1 COMPLETE: Price/Volume filtering",
           total_analyzed=14,
           passed=12)
```

### Fix Required
```python
# ✅ Fixed (will export to BigQuery)
logger.info("STAGE 1 COMPLETE: Price/Volume filtering",
           event_category="filtering",  # ← Add this!
           event_type="stage_1_complete",  # ← And this for querying
           total_analyzed=14,
           passed=12)
```

---

## 📝 Quick Reference: Field Naming

### Required Fields (All Logs)
- `event_category` - One of: system, risk, trade, performance, error, position, backtest, filtering
- `event` or `event_type` - Specific event name (snake_case)

### Recommended Fields
- `symbol` - Stock or option symbol
- `timestamp_ms` - Unix milliseconds (auto-added by logging_events.py functions)
- `timestamp_iso` - ISO format timestamp (auto-added by logging_events.py functions)

### Contextual Fields (As Needed)
- `reason` - Why something happened (rejections, blocks)
- `metric_name`, `metric_value` - For performance metrics
- `success` - Boolean for trade results
- `error_message` - For error logs
- Status fields: `passed`, `rejected`, `blocked`, `total_analyzed`, etc.

---

## 🎨 Logging Patterns by Use Case

### Pattern 1: Filter Stage Summary
```python
logger.info(f"STAGE {N} COMPLETE: {description}",
           event_category="filtering",
           event_type=f"stage_{N}_complete",
           total_input=len(input_list),
           passed=len(passed_list),
           rejected=len(rejected_list),
           passed_symbols=[s['symbol'] for s in passed_list],
           rejected_symbols=rejected_list)
```

### Pattern 2: Per-Stock Decision
```python
# Pass
logger.info(f"STAGE {N}: {description} PASSED",
           event_category="filtering",
           event_type=f"stage_{N}_passed",
           symbol=symbol,
           **metrics)

# Block
logger.info(f"STAGE {N}: {description} BLOCKED",
           event_category="filtering",
           event_type=f"stage_{N}_blocked",
           symbol=symbol,
           reason=reason,
           **metrics)
```

### Pattern 3: Error with Recovery
```python
from src.utils.logging_events import log_error_event

log_error_event(
    logger,
    error_type="api_timeout",
    error_message=str(e),
    component="alpaca_client",
    recoverable=True,
    symbol=symbol,
    retry_count=retries
)
```

### Pattern 4: Performance Metric
```python
from src.utils.logging_events import log_performance_metric

log_performance_metric(
    logger,
    metric_name="stage_1_duration",
    metric_value=duration_seconds,
    metric_unit="seconds",
    stocks_processed=14
)
```

---

## 🚀 Best Practices

### DO ✅
- Always include `event_category`
- Use descriptive `event_type` values
- Include relevant symbols, metrics, reasons
- Use snake_case for field names
- Log both success and failure cases
- Add context that helps debugging

### DON'T ❌
- Never omit `event_category` (logs won't reach BigQuery!)
- Don't use inconsistent field names
- Don't log sensitive data (API keys, credentials)
- Don't use deeply nested JSON (BigQuery prefers flat)
- Don't log excessive data (keep it relevant)

---

## 🔍 Verification

### Check if Your Logs Reach BigQuery

1. **Check Cloud Logging** (immediate):
```bash
gcloud logging read 'jsonPayload.event_category=filtering' --limit=10
```

2. **Check BigQuery** (5-10 min delay):
```bash
bq query --use_legacy_sql=false \
  "SELECT timestamp, jsonPayload.event, jsonPayload.event_category
   FROM \`gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*\`
   WHERE jsonPayload.event_category = 'filtering'
   ORDER BY timestamp DESC
   LIMIT 10"
```

3. **Verify in Console**:
   - Cloud Logging: https://console.cloud.google.com/logs
   - BigQuery: https://console.cloud.google.com/bigquery?project=gen-lang-client-0607444019&d=options_wheel_logs

---

## 📚 References

- **Logging Events Utility**: [src/utils/logging_events.py](../src/utils/logging_events.py)
- **BigQuery Setup**: [docs/BIGQUERY_LOGGING_SETUP.md](BIGQUERY_LOGGING_SETUP.md)
- **BigQuery Status**: [docs/BIGQUERY_STATUS_OCT3_2025.md](BIGQUERY_STATUS_OCT3_2025.md)
- **Monitoring Checklist**: [docs/BIGQUERY_MONITORING_CHECKLIST.md](BIGQUERY_MONITORING_CHECKLIST.md)

---

## 🎯 Action Items for Developers

**When adding new logging**:
1. Read this guide first
2. Choose appropriate `event_category`
3. Use `log_*_event()` functions when possible
4. Always include `event_category` if using direct logger calls
5. Test in Cloud Logging immediately
6. Verify in BigQuery after 10 minutes

**When reviewing code**:
1. Check all logger.info/warning/error calls have `event_category`
2. Verify category is one of the standard 8: system, risk, trade, performance, error, position, backtest, filtering
3. Ensure field names are descriptive and use snake_case
4. Confirm no sensitive data is being logged

---

**Last Updated**: October 3, 2025
**Applies To**: All Python code in options_wheel strategy
**Enforcement**: Required for BigQuery integration
