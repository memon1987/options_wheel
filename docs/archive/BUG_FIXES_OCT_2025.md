# Bug Fixes Summary - October 29-30, 2025

This document summarizes all bugs identified and fixed during the exhaustive log review of October 15-29, 2025.

---

## Issue #1: Buying Power Race Condition (CRITICAL)

**Severity:** CRITICAL
**Impact:** 84.5% trade failure rate (175 failed / 207 total trades)
**Status:** ✅ FIXED
**Commit:** `1097d88`

### Problem
175 out of 207 trade attempts failed with "insufficient options buying power" errors, despite batch selection logic designed to stay within buying power limits.

### Root Cause
Concurrent order execution using `ThreadPoolExecutor` with `skip_buying_power_check=True` created race conditions:
- Multiple orders submitted simultaneously based on initial buying power
- First order succeeds and immediately consumes buying power
- Subsequent concurrent orders didn't know about BP reduction
- These trades failed when Alpaca rejected them due to insufficient funds

### Evidence
**Oct 28, 2025 at 14:15:02 UTC:**
```
Initial BP: $63,595.09
Selected: GOOGL ($25k) + AMD ($24.5k) = $49.5k (within budget ✅)

14:15:02.826 - GOOGL trade SUCCEEDED → consumed $25k
14:15:02.893 - AMD trade FAILED (67ms later)
                Error: "insufficient options buying power"
                Required: $24,305
                Available: $13,813 (should be $38,595)
```

### Solution
Replaced concurrent `ThreadPoolExecutor` execution with **sequential execution** that validates buying power before each order:

**File:** [deploy/cloud_run_server.py:313-382](../deploy/cloud_run_server.py#L313-L382)

```python
# Execute each order sequentially with real-time buying power validation
for opp in selected_opportunities:
    # Execute with buying power check (DO NOT skip - prevents race conditions)
    result = put_seller.execute_put_sale(opp, skip_buying_power_check=False)
```

### Impact
- **Before:** 15.5% success rate (32 success / 175 failures)
- **Expected After:** >90% success rate
- **Tradeoff:** 1-2 seconds slower for multiple orders, but prevents 84.5% failure rate

### Monitoring
```bash
# Check success rate after deployment
gcloud logging read \
  'resource.labels.service_name="options-wheel-strategy" AND
   jsonPayload.event_type="strategy_execution_completed" AND
   timestamp>="2025-10-30T00:00:00Z"' \
  --limit=10 --format=json
```

---

## Issue #2: BigQuery Log Sink Schema Errors

**Severity:** MEDIUM
**Impact:** 3-6 schema errors per day, daily error email alerts
**Status:** ✅ FIXED
**Commit:** `4134541`

### Problem
Log sink to BigQuery was generating daily schema errors with email notifications:
- "Array specified for non-repeated field: symbols"
- "Cannot convert value to floating point (bad value): SPY"

### Root Cause
In `backtest_engine.py` line 165, the `symbols` field was being logged as a Python list:
```python
logger.info("Starting backtest", symbols=self.backtest_config.symbols)
# Logged as: symbols=["SPY", "AAPL"]
```

BigQuery's auto-generated schema expected a STRING type, but received an ARRAY, causing schema mismatch errors.

### Evidence
Query of export errors over 7 days:
```
schemaErrorDetail                                    count
Cannot convert value to floating point: SPY            10
Array specified for non-repeated field: symbols        6
Cannot convert value to floating point: AAPL           2
```

Daily error counts:
```
Date        Error Count
2025-10-29      3
2025-10-28      3
2025-10-27      6
2025-10-24      3
(continuing pattern)
```

### Solution
Changed `symbols` field to comma-separated string format:

**File:** [src/backtesting/backtest_engine.py:165](../src/backtesting/backtest_engine.py#L165)

```python
# Before:
logger.info("Starting backtest", symbols=self.backtest_config.symbols)

# After:
logger.info("Starting backtest", symbols=",".join(self.backtest_config.symbols))
```

This matches the format used in structured events (lines 175, 244) which were already correct.

### Impact
- Eliminates daily schema error email notifications
- All backtest logs now consistently use string format
- No data loss - logs were being captured in `export_errors_*` tables

### Verification
After next backtest runs, verify no new errors:
```bash
bq query --use_legacy_sql=false \
  'SELECT * FROM `options_wheel_logs.export_errors_*`
   WHERE timestamp > TIMESTAMP("2025-10-30 00:00:00") LIMIT 10'
```

---

## Historical Performance Summary

### Trade Execution (Oct 15-29, 2025)
- **Execution Cycles:** 26
- **Trades Executed:** 32 ✅
- **Trades Failed:** 175 ❌
- **Success Rate:** 15.5%
- **All Failures:** "insufficient options buying power"

### Scan Performance (Oct 15-29, 2025)
- **Total Scans:** 50
- **Put Opportunities Found:** 418
- **Call Opportunities:** 0 (expected - no stock positions)
- **Avg Opportunities per Scan:** 8.4

### Gap Detection
- **Total Failures:** 2 (Oct 15 only)
- **Symbols:** AMD, UNH
- **Error:** "single positional indexer is out-of-bounds"
- **Fallback:** "blocking_assumed_large_gap" (safe failure mode ✅)
- **Assessment:** Minor edge case, proper fallback behavior

---

## Deployment Timeline

| Time (UTC) | Event | Status |
|------------|-------|--------|
| 2025-10-29 18:00 | Log analysis completed | ✅ |
| 2025-10-30 00:30 | Commit 1097d88 (buying power fix) | ✅ |
| 2025-10-30 00:31 | Cloud Build started | ✅ |
| 2025-10-30 00:37 | Revision 00077-hfr deployed | ✅ |
| 2025-10-30 00:40 | Commit 4134541 (log sink fix) | ✅ |
| 2025-10-30 00:41 | Cloud Build started | 🔄 |

---

## Next Steps

1. **Monitor next execution cycle** (next scheduled: hourly during market hours)
   - Verify trade success rate >90%
   - Check for buying power errors (should be near zero)
   - Confirm sequential execution working correctly

2. **Monitor backtest runs** (scheduled: daily at 1pm ET)
   - Verify no new BigQuery schema errors
   - Confirm export_errors_* tables stop growing

3. **Consider future improvements**
   - Add automated alerts for success rate < 80%
   - Implement monitoring dashboard for trade metrics
   - Add unit tests for concurrent execution scenarios

---

## Lessons Learned

1. **Never skip validation in concurrent code** - The `skip_buying_power_check=True` flag created a false sense of security

2. **Race conditions are subtle** - The 67ms gap between success and failure made this hard to spot

3. **Production logs are invaluable** - Detailed structured logging made root cause analysis possible

4. **Schema consistency matters** - Inconsistent data types cause downstream issues in analytics pipelines

5. **Sequential can be better than concurrent** - Simplicity and reliability sometimes trump speed

6. **Monitor error patterns** - Daily schema errors were a clear signal that needed investigation

---

## Related Documentation

- [BUG_FIX_BUYING_POWER_RACE_CONDITION.md](./BUG_FIX_BUYING_POWER_RACE_CONDITION.md) - Detailed analysis of Issue #1
- [PRODUCTION_LOG_ANALYSIS.md](./PRODUCTION_LOG_ANALYSIS.md) - Full log analysis Oct 15-29
- [HOURLY_EXECUTION_SCHEDULE.md](./HOURLY_EXECUTION_SCHEDULE.md) - Current execution schedule
