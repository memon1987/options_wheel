# Critical Bug Fix: Buying Power Race Condition

**Date:** October 29, 2025
**Severity:** CRITICAL
**Impact:** 84.5% trade failure rate (175 failed / 207 total trades)

## Problem Summary

The options trading system was experiencing an extremely high failure rate where 175 out of 207 trade attempts failed with "insufficient options buying power" errors, despite having a batch selection algorithm designed to stay within buying power limits.

## Root Cause Analysis

### The Bug
Concurrent order execution using `ThreadPoolExecutor` with `skip_buying_power_check=True` created a race condition:

1. Multiple orders were submitted simultaneously based on initial buying power
2. When the first trade succeeded, it immediately consumed buying power
3. Subsequent concurrent trades didn't know about the BP reduction
4. These trades failed when Alpaca rejected them due to insufficient funds

### Evidence from Production Logs

**Execution on October 28, 2025 at 14:15:02 UTC:**

```
14:15:02.438 - Initial buying power: $63,595.09
14:15:02.773 - Selected GOOGL (collateral $25,000) → remaining BP $38,595 ✅
14:15:02.774 - Selected AMD (collateral $24,500) → remaining BP $14,095 ✅
14:15:02.826 - GOOGL trade SUCCEEDED (consumed $25,000)
14:15:02.893 - AMD trade FAILED (67ms later)
                Error: "insufficient options buying power"
                Required: $24,305
                Available: $13,813
```

**Key Observation:** Both trades were selected within budget ($49.5k < $63.6k), but AMD failed because GOOGL had already consumed $25k by the time AMD's order reached Alpaca.

### Code Location
[deploy/cloud_run_server.py:313-400](../deploy/cloud_run_server.py#L313-L400)

**Previous Implementation:**
```python
# Submit all orders concurrently
with ThreadPoolExecutor(max_workers=min(10, len(selected_opportunities))) as executor:
    # Submit all orders
    future_to_opp = {
        executor.submit(execute_single_order, opp): opp
        for opp in selected_opportunities
    }
    # Process results as they complete...
```

With orders executing via:
```python
result = put_seller.execute_put_sale(opp, skip_buying_power_check=True)
```

## Solution

### Fix Implementation
Replaced concurrent execution with **sequential execution** that validates buying power before each order:

```python
# Execute each order sequentially with real-time buying power validation
for opp in selected_opportunities:
    # Execute with buying power check (DO NOT skip - prevents race conditions)
    result = put_seller.execute_put_sale(opp, skip_buying_power_check=False)
```

### How It Works
1. Orders execute one at a time (sequentially)
2. Each order checks actual available buying power via Alpaca API before submitting
3. If buying power is insufficient, the order is skipped gracefully
4. No race conditions possible - each order sees the latest BP state

### Tradeoff
- **Slower execution:** 1-2 seconds for multiple orders vs concurrent submission
- **Much higher reliability:** Prevents 84.5% failure rate
- **Expected result:** >90% success rate

## Deployment

**Commit:** `1097d88`
**Deployed:** October 29, 2025
**Build ID:** `45152dcc-07f7-4b73-bfcd-370e9488ebcd`

## Monitoring

### Success Metrics to Track
1. Trade success rate (target: >90%)
2. "insufficient buying power" errors (target: near zero)
3. Execution duration (expected: slight increase)

### Log Queries

**Check success rate after deployment:**
```bash
gcloud logging read \
  'resource.labels.service_name="options-wheel-strategy" AND
   jsonPayload.event_type="strategy_execution_completed" AND
   timestamp>="2025-10-30T00:00:00Z"' \
  --limit=10 --format=json
```

**Check for buying power errors:**
```bash
gcloud logging read \
  'resource.labels.service_name="options-wheel-strategy" AND
   jsonPayload.error_message=~"insufficient.*buying.*power" AND
   timestamp>="2025-10-30T00:00:00Z"' \
  --limit=20 --format=json
```

## Historical Performance

### Before Fix (Oct 15-29, 2025)
- Execution Cycles: 26
- Trades Executed: 32 ✅
- Trades Failed: 175 ❌
- **Success Rate: 15.5%**
- All failures: "insufficient options buying power"

### Expected After Fix
- **Success Rate: >90%**
- Failures only when legitimately insufficient BP (e.g., market moved, positions changed)

## Related Files
- [deploy/cloud_run_server.py](../deploy/cloud_run_server.py) - Main fix
- [src/strategy/put_seller.py](../src/strategy/put_seller.py) - Buying power validation logic
- [docs/PRODUCTION_LOG_ANALYSIS.md](./PRODUCTION_LOG_ANALYSIS.md) - Full log analysis

## Lessons Learned

1. **Never skip validation in concurrent code** - The `skip_buying_power_check=True` flag created a false sense of security
2. **Test concurrent execution thoroughly** - Race conditions are difficult to spot in single-threaded testing
3. **Monitor production metrics closely** - The 84.5% failure rate should have triggered alerts
4. **Defensive programming** - Always validate critical resources (like buying power) before consumption
5. **Sequential can be better than concurrent** - Sometimes simplicity and reliability trump speed

## Future Improvements

1. Add automated alerts for trade success rate < 80%
2. Implement thread-safe buying power tracking if concurrent execution is needed for performance
3. Add unit tests for concurrent execution scenarios
4. Consider implementing a "dry-run" mode to validate orders before submission
