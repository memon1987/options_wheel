# Options Wheel Strategy - Claude Instructions

## Wheel Strategy Symmetry Principle

**IMPORTANT**: The options wheel strategy has two main phases that function symmetrically:

1. **Put Selling Phase** (Initial entry)
   - Sell cash-secured puts to enter positions
   - Filtering logic in `find_suitable_puts()` in `src/api/market_data.py`
   - Execution logic in `src/strategy/put_seller.py`

2. **Call Selling Phase** (Position management)
   - Sell covered calls on assigned stock positions
   - Filtering logic in `find_suitable_calls()` in `src/api/market_data.py`
   - Execution logic in `src/strategy/call_seller.py`

### Symmetry Rule

**When making logging, filtering, or structural changes to one side of the wheel (puts OR calls), always apply equivalent changes to the other side.**

This includes:
- **Logging enhancements**: If you add detailed rejection tracking to puts, add it to calls
- **Filtering improvements**: If you enhance criteria checking for puts, enhance it for calls
- **Error handling**: If you improve error messages for puts, improve them for calls
- **Performance metrics**: If you track metrics for puts, track them for calls
- **Documentation**: If you document put logic, document call logic

### Examples

✅ **Correct Approach**:
- Add `_check_put_criteria_detailed()` → Also add `_check_call_criteria_detailed()`
- Track put rejection stats → Also track call rejection stats
- Log Stage 7 filtering details → Also log Stage 8 filtering details

❌ **Incorrect Approach**:
- Only enhance put filtering without updating call filtering
- Add detailed put logging but leave call logging basic
- Improve put error handling without touching call error handling

### Why This Matters

The wheel strategy is a **complete lifecycle**:
1. Sell put → 2. Get assigned stock → 3. Sell call → 4. Stock called away → Repeat

Both phases must have:
- **Equal observability** for debugging and analysis
- **Consistent logging** for BigQuery reporting
- **Symmetric filtering** for fair opportunity evaluation
- **Parallel error handling** for reliable execution

### File Locations

When working on wheel symmetry, these are the key files:

| Component | Put Side | Call Side |
|-----------|----------|-----------|
| Filtering | `src/api/market_data.py::find_suitable_puts()` | `src/api/market_data.py::find_suitable_calls()` |
| Criteria checking | `src/api/market_data.py::_check_put_criteria_detailed()` | `src/api/market_data.py::_check_call_criteria_detailed()` |
| Execution | `src/strategy/put_seller.py` | `src/strategy/call_seller.py` |
| Configuration | `src/config/config.yaml` (put_* params) | `src/config/config.yaml` (call_* params) |

### Reminder

**Before completing any wheel-related task, ask yourself**: "Did I apply this change symmetrically to both puts and calls?"
