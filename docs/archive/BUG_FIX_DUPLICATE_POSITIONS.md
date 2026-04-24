# Bug Fix: Duplicate Positions Race Condition

**Date**: October 15, 2025
**Issue**: Two AMD positions created simultaneously
**Root Cause**: Race condition between order placement and position checking
**Status**: ✅ FIXED

---

## Problem Summary

User ended up with **two AMD positions open simultaneously**, violating the risk parameter of only one position per underlying stock.

## Root Cause Analysis

### Timeline of the Bug

1. **Execution Cycle 1** (e.g., 10:15am ET)
   - Stage 6 checks Alpaca positions: No AMD position exists ✓
   - AMD passes all filtering stages
   - Order placed for AMD251017P00207500
   - Order logged as "trade_executed"
   - **Order sits in OPEN/PENDING state** (not yet filled)

2. **Execution Cycle 2** (e.g., 11:15am ET) - 1 hour later
   - Stage 6 checks Alpaca positions again
   - **First AMD order still not filled** (shows as open order, not position)
   - `_has_existing_option_position('AMD')` returns **False** ❌
   - AMD passes Stage 6 again
   - **Second AMD order placed**

3. **Both orders eventually fill**
   - Result: 2 AMD positions simultaneously

### Code Issue

The original `_has_existing_option_position()` function only checked **filled positions**:

```python
def _has_existing_option_position(self, underlying_symbol: str) -> bool:
    positions = self.alpaca.get_positions()  # Only checks FILLED positions
    option_positions = [p for p in positions
                      if p['asset_class'] == 'us_option' and underlying_symbol in p['symbol']]
    return len(option_positions) > 0
```

**Missing**: Check for OPEN/PENDING orders that haven't filled yet.

---

## The Fix

### Three-Tier Position Check

Updated `_has_existing_option_position()` to check THREE sources:

```python
def _has_existing_option_position(self, underlying_symbol: str) -> bool:
    # Check 1: Pending orders in current cycle (local tracking)
    if underlying_symbol in self._pending_underlyings:
        return True  # BLOCKED: Pending order in current cycle

    # Check 2: Open/pending orders from Alpaca API (race condition fix)
    open_orders = self.alpaca.get_orders(status='open')
    pending_orders = self.alpaca.get_orders(status='pending_new')
    for order in open_orders + pending_orders:
        if underlying_symbol in order['symbol']:
            return True  # BLOCKED: Open order exists

    # Check 3: Filled positions from Alpaca
    positions = self.alpaca.get_positions()
    option_positions = [p for p in positions
                      if p['asset_class'] == 'us_option' and underlying_symbol in p['symbol']]
    return len(option_positions) > 0  # BLOCKED: Position exists
```

### Key Changes

1. **Added local tracking** (`_pending_underlyings` set)
   - Tracks orders placed within current execution cycle
   - Cleared at start of each cycle

2. **Added Alpaca API open order check**
   - Checks orders with status='open' or status='pending_new'
   - Catches orders placed in previous cycles that haven't filled
   - **This is the critical fix for the race condition**

3. **Enhanced logging** for Stage 6
   - Logs specific reason for blocking (pending_order, open_order, filled_position)
   - Includes order_id and order_status for open orders
   - Logs PASSED events when no conflicts found

---

## Impact

### Before Fix
- ❌ Could create duplicate positions if orders slow to fill
- ❌ Violated one-position-per-underlying risk rule
- ❌ No visibility into open orders during Stage 6 check

### After Fix
- ✅ Checks open/pending orders before allowing new trades
- ✅ Enforces one-position-per-underlying across all execution cycles
- ✅ Comprehensive logging shows why stocks are blocked at Stage 6
- ✅ Three-tier defense against duplicates:
  1. Local tracking (current cycle)
  2. Alpaca open orders (previous cycles)
  3. Alpaca filled positions (existing positions)

---

## Evidence from Logs

### Oct 13, 2025 - When Duplicate AMD Would Have Occurred

```
2025-10-13T14:15:06.497038Z - Selected opportunity for batch execution - Symbol: AMD
2025-10-13T14:15:06.497235Z - Skipping duplicate underlying in batch selection - Symbol: AMD
  reason: already_selected_for_execution
2025-10-13T14:15:06.553542Z - trade_executed - Symbol: AMD - Option: AMD251017P00207500
```

**Within-cycle duplicate prevention worked**, but between-cycle checks failed.

### What Will Happen After Fix

If AMD trade at 10:15am hasn't filled by 11:15am execution:

```
2025-10-XX 11:15:06 - STAGE 6: Existing position check BLOCKED - open order exists
  event_category: filtering
  event_type: stage_6_blocked
  symbol: AMD
  reason: open_order_exists
  order_id: 2aed9624-cb79-4f43-9a03-48eb1a58f19b
  order_status: open
  order_symbol: AMD251017P00207500
```

---

## Testing Recommendations

### Manual Test
1. Place a limit order for AMD with very low premium (won't fill immediately)
2. Wait for order to show status='open' in Alpaca
3. Run next execution cycle
4. Verify Stage 6 blocks AMD with reason="open_order_exists"

### Expected Log Output
```json
{
  "event": "STAGE 6: Existing position check BLOCKED - open order exists",
  "event_category": "filtering",
  "event_type": "stage_6_blocked",
  "symbol": "AMD",
  "reason": "open_order_exists",
  "order_id": "xxx",
  "order_status": "open"
}
```

### BigQuery Monitoring
```sql
-- Check for Stage 6 blocks due to open orders
SELECT
  date_et,
  symbol,
  reason,
  COUNT(*) as block_count
FROM `options_wheel_logs.symbol_filtering_journey`
WHERE stage_number = 6
  AND stage_result = 'BLOCKED'
  AND reason = 'open_order_exists'
GROUP BY date_et, symbol, reason
ORDER BY date_et DESC, block_count DESC;
```

---

## Performance Considerations

### API Call Overhead
- **Before**: 1 API call to get_positions()
- **After**: 3 API calls (get_positions + 2x get_orders)

### Mitigation
- Open order checks are fast (typically <100ms)
- Happens only during Stage 6 (once per symbol per cycle)
- Maximum ~14 symbols = ~42 extra API calls per cycle
- Well within Alpaca rate limits (200 req/min)

### Optimization (if needed)
```python
# Cache open orders for entire cycle (call once, use many times)
if not hasattr(self, '_cached_open_orders'):
    self._cached_open_orders = self.alpaca.get_orders(status='open') + \
                               self.alpaca.get_orders(status='pending_new')
```

---

## Related Files

- [wheel_engine.py:422-501](../src/strategy/wheel_engine.py#L422-L501) - Fixed method
- [alpaca_client.py:356-385](../src/api/alpaca_client.py#L356-L385) - get_orders() method
- [cloud_run_server.py:272-290](../deploy/cloud_run_server.py#L272-L290) - Batch deduplication

---

## Conclusion

This fix prevents the race condition that allowed duplicate positions when orders were slow to fill. The three-tier checking system ensures robust enforcement of the one-position-per-underlying rule across all execution cycles.

**Key Insight**: Always check **open orders** in addition to **filled positions** when making trading decisions that depend on position state.
