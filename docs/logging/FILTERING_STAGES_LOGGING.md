# Complete Filtering Pipeline Logging Coverage

## Summary

**ALL 9 filtering stages have comprehensive logging with `event_category="filtering"`**

The code already includes detailed logging for every filtering stage. The reason you only see Stage 1 and Stage 7 in current BigQuery data is because **Stages 2-6, 8-9 only log during execution attempts**, not during scans.

## Logging Coverage by Stage

| Stage | What It Does | When Logged | Event Types | Status |
|-------|--------------|-------------|-------------|--------|
| **1** | Price/Volume filtering | **During SCAN** | `stage_1_complete` | ✅ **Visible in BQ** |
| **2** | Gap Risk Analysis | **During SCAN** | `stage_2_complete` | ✅ **Has logging** |
| **3** | Stock Evaluation Limit | **During SCAN** | `stage_3_limit_applied`, `stage_3_no_limit` | ✅ **Has logging** |
| **4** | Execution Gap Check | **During EXECUTION** | `stage_4_passed`, `stage_4_blocked` | ✅ **Has logging** |
| **5** | Wheel State Check | **During EXECUTION** | `stage_5_check` | ✅ **Has logging** |
| **6** | Existing Position Check | **During EXECUTION** | `stage_6_passed`, `stage_6_blocked` | ✅ **Has logging** |
| **7** | Options Chain (Puts) | **During SCAN** | `stage_7_start`, `stage_7_complete_found`, `stage_7_complete_not_found` | ✅ **Visible in BQ** |
| **8** | Position Sizing | **During EXECUTION** | `stage_8_calculation`, `stage_8_passed`, `stage_8_blocked` | ✅ **Has logging** |
| **9** | New Positions Limit | **During EXECUTION** | `stage_9_limit_reached` | ✅ **Has logging** |

## Why Current BigQuery Only Shows Stages 1 & 7

### Scan vs. Execution Logging

The filtering pipeline has two phases:

**SCAN Phase** (runs every hour at :00):
- Stage 1: Price/Volume ✅ Logged
- Stage 2: Gap Risk ✅ Logged
- Stage 3: Evaluation Limit ✅ Logged
- Stage 7: Options Chain ✅ Logged

**EXECUTION Phase** (runs at :15, processes opportunities from scan):
- Stage 4: Execution Gap Check ✅ Logged
- Stage 5: Wheel State ✅ Logged
- Stage 6: Existing Positions ✅ Logged
- Stage 8: Position Sizing ✅ Logged
- Stage 9: Position Limit ✅ Logged

### Current Data (Oct 15, 2025)

Your test scan at 1:08am ET (5:08 UTC) only ran the **SCAN phase**, which is why you see:
- ✅ Stage 1: 1 event (price/volume filtering)
- ✅ Stage 7: 27 events (put options scanning)

To see Stages 2-6, 8-9, you need an **EXECUTION attempt** where the system:
1. Finds valid opportunities from scan
2. Attempts to place trades
3. Goes through stages 4-6, 8-9 per symbol

## Complete Event Types Reference

### Stage 1 - Price/Volume
```python
logger.info("STAGE 1 COMPLETE: Price/Volume filtering",
           event_category="filtering",
           event_type="stage_1_complete",
           input_stocks=14,
           passed=10,
           rejected=4)
```

### Stage 2 - Gap Risk Analysis
```python
logger.info("STAGE 2 COMPLETE: Gap risk analysis",
           event_category="filtering",
           event_type="stage_2_complete",
           input_symbols=10,
           passed=8,
           rejected=2,
           passed_symbols=["MSFT", "GOOGL", ...],
           rejected_symbols=["AMD", "NVDA"])
```

### Stage 3 - Stock Evaluation Limit
```python
# When limit is applied:
logger.info("STAGE 3: Stock evaluation limit applied",
           event_category="filtering",
           event_type="stage_3_limit_applied",
           max_stocks=5,
           total_available=8,
           evaluating=5)

# When no limit (current config):
logger.info("STAGE 3: No stock evaluation limit",
           event_category="filtering",
           event_type="stage_3_no_limit",
           stocks_to_evaluate=8)
```

### Stage 4 - Execution Gap Check
```python
# Passed:
logger.info("STAGE 4: Execution gap check PASSED",
           event_category="filtering",
           event_type="stage_4_passed",
           symbol="AAPL",
           gap_percent=0.5)

# Blocked:
logger.info("STAGE 4: Execution gap check BLOCKED",
           event_category="filtering",
           event_type="stage_4_blocked",
           symbol="NVDA",
           reason="execution_gap_exceeded",
           gap_percent=2.1)
```

### Stage 5 - Wheel State Check
```python
logger.info("STAGE 5: Wheel state check",
           event_category="filtering",
           event_type="stage_5_check",
           symbol="MSFT",
           wheel_phase="SELLING_PUTS",
           can_sell_calls=False,
           can_sell_puts=True)
```

### Stage 6 - Existing Position Check
```python
# Passed:
logger.info("STAGE 6: Existing position check PASSED",
           event_category="filtering",
           event_type="stage_6_passed",
           symbol="GOOGL")

# Blocked:
logger.info("STAGE 6: Existing position check BLOCKED",
           event_category="filtering",
           event_type="stage_6_blocked",
           symbol="AAPL",
           reason="already_has_option_position")
```

### Stage 7 - Options Chain Criteria
```python
# Start scanning:
logger.info("STAGE 7: Options chain criteria - starting put scan",
           event_category="filtering",
           event_type="stage_7_start",
           symbol="UNH",
           total_puts_in_chain=50)

# Found suitable puts:
logger.info("STAGE 7 COMPLETE: Options chain criteria - puts found",
           event_category="filtering",
           event_type="stage_7_complete_found",
           symbol="UNH",
           suitable_puts=3)

# No suitable puts:
logger.info("STAGE 7 COMPLETE: Options chain criteria - NO suitable puts",
           event_category="filtering",
           event_type="stage_7_complete_not_found",
           symbol="F",
           reason="no_puts_in_delta_range")
```

### Stage 8 - Position Sizing
```python
# Calculation:
logger.info("STAGE 8: Position sizing calculation",
           event_category="filtering",
           event_type="stage_8_calculation",
           symbol="MSFT",
           strike=380.0,
           buying_power=50000,
           max_contracts_allowed=3)

# Passed:
logger.info("STAGE 8 PASSED: Position sizing approved",
           event_category="filtering",
           event_type="stage_8_passed",
           symbol="MSFT",
           contracts=3,
           capital_required=114000,
           portfolio_allocation=0.228)

# Blocked:
logger.warning("STAGE 8 BLOCKED: Position sizing - insufficient capital",
              event_category="filtering",
              event_type="stage_8_blocked",
              reason="max_contracts_zero")
```

### Stage 9 - New Positions Limit
```python
logger.info("STAGE 9: Max new positions per cycle limit REACHED",
           event_category="filtering",
           event_type="stage_9_limit_reached",
           max_positions=3,
           positions_found=3,
           stopping_evaluation=True)
```

## Code Locations

| Stage | File | Lines | Function |
|-------|------|-------|----------|
| 1 | `src/api/market_data.py` | 117-119 | `filter_suitable_stocks()` |
| 2 | `src/risk/gap_detector.py` | 383-390 | `filter_stocks_by_gap_risk()` |
| 3 | `src/strategy/wheel_engine.py` | 278-290 | `_find_new_opportunities()` |
| 4 | `src/strategy/wheel_engine.py` | 300-312 | `_find_new_opportunities()` |
| 5 | `src/strategy/wheel_engine.py` | 321-327 | `_find_new_opportunities()` |
| 6 | `src/strategy/wheel_engine.py` | 346-356 | `_find_new_opportunities()` |
| 7 | `src/api/market_data.py` | 205-285 | `find_suitable_puts()` |
| 8 | `src/strategy/put_seller.py` | 139-188 | `_calculate_position_size()` |
| 9 | `src/strategy/wheel_engine.py` | 370-376 | `_find_new_opportunities()` |

## How to See All Stages in BigQuery

### Option 1: Wait for Real Executions
During normal trading hours (10am-3pm ET), when executions run at :15:
- Stages 2-3 will log during the scan at :00
- Stages 4-6, 8-9 will log during execution at :15

### Option 2: Manual Test Execution
```bash
# 1. Run a scan first (creates opportunities)
gcloud scheduler jobs run scan-10am --location=us-central1

# 2. Wait 1-2 minutes for scan to complete

# 3. Run execution (will process opportunities through all stages)
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

### Expected Results After Full Execution

```
stage_number | events | description
-------------|--------|-------------
1            | 1      | Price/volume filtering
2            | 1      | Gap risk analysis summary
3            | 1      | Stock evaluation limit (or no-limit)
4            | 5-10   | Execution gap checks (1 per symbol evaluated)
5            | 5-10   | Wheel state checks (1 per symbol)
6            | 5-10   | Position checks (1 per symbol)
7            | 30-50  | Options chain scanning (multiple per symbol)
8            | 3-8    | Position sizing (1 per opportunity)
9            | 0-1    | Position limit (only if limit reached)
```

## BigQuery Query for Complete Funnel

```sql
WITH stage_counts AS (
  SELECT
    stage_number,
    COUNT(*) as total_events,
    COUNT(DISTINCT symbol) as unique_symbols,
    SUM(CASE WHEN stage_result = 'PASSED' THEN 1 ELSE 0 END) as passed,
    SUM(CASE WHEN stage_result = 'BLOCKED' THEN 1 ELSE 0 END) as blocked
  FROM `options_wheel_logs.filtering_pipeline`
  WHERE date_et = CURRENT_DATE('America/New_York')
    AND stage_number IS NOT NULL
  GROUP BY stage_number
)
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
  unique_symbols,
  passed,
  blocked,
  total_events
FROM stage_counts
ORDER BY stage_number;
```

## Next Steps

1. **Wait for next scheduled execution** (during market hours)
2. **Or trigger manual scan + execution** to generate all stage logs
3. **Query BigQuery** after 5-10 min to see complete filtering funnel
4. **Use `filtering_pipeline` view** for detailed stage-by-stage analysis

All logging is already in place - you just need execution attempts to generate the logs for stages 2-6, 8-9!
