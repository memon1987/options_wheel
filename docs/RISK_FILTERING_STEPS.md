# Risk Filtering Steps During Market Scan

**Complete flow diagram of all risk filters applied during each hourly market scan**

Generated: October 3, 2025
Strategy: Options Wheel (Cash-Secured Puts → Assignment → Covered Calls)

---

## Overview

Each hourly scan at `:15` (execution time) filters the 14-stock universe through **7 major filter stages** before considering any trade.

**Stock Universe**: 14 symbols
→ `AAPL`, `MSFT`, `GOOGL`, `AMZN`, `NVDA`, `AMD`, `QQQ`, `SPY`, `IWM`, `UNH`, `F`, `PFE`, `KMI`, `VZ`

---

## Filter Pipeline

### STAGE 1: Basic Stock Suitability
**Component**: `market_data.filter_suitable_stocks()` → `get_stock_metrics()`
**Location**: [src/api/market_data.py:33-62](../src/api/market_data.py#L33-L62)

#### Filters Applied:

1. **Price Range Filter**
   - **Min**: $10.00
   - **Max**: $400.00
   - **Config**: [config/settings.yaml:30-31](../config/settings.yaml#L30-L31)
   - **Rejects**: Stocks outside price range

2. **Volume Filter**
   - **Minimum**: 2,000,000 shares/day average (30-day)
   - **Config**: [config/settings.yaml:32](../config/settings.yaml#L32)
   - **Rejects**: Illiquid stocks

3. **Combined Check**
   - Must pass BOTH price AND volume criteria
   - **Result**: `suitable_for_wheel = true/false`

**Output**: `suitable_stocks` (sorted by volume descending, volatility ascending)

---

### STAGE 2: Gap Risk Analysis (Historical)
**Component**: `gap_detector.filter_stocks_by_gap_risk()`
**Location**: [src/risk/gap_detector.py:304-341](../src/risk/gap_detector.py#L304-L341)

For each suitable stock, performs historical analysis:

#### Sub-Filter 2A: Historical Gap Frequency
**Function**: `_calculate_overnight_gaps()`
**Lookback**: 30 days
**Config**: [config/settings.yaml:66-67](../config/settings.yaml#L66-L67)

**Analysis**:
- Counts overnight gaps > 2.0% (quality_gap_threshold)
- Calculates: `gap_frequency = significant_gaps / total_days`
- **Rejects if**: `gap_frequency > 0.15` (15%)

**Example from Oct 2**:
- AMD: gap_frequency = 20.6% → **REJECTED** ❌
- UNH: gap_frequency = 8.8% → Passes this check ✅

#### Sub-Filter 2B: Historical Volatility
**Function**: `_calculate_historical_volatility()`
**Config**: [config/settings.yaml:82](../config/settings.yaml#L82)

**Analysis**:
- Calculates annualized volatility from 30-day returns
- Formula: `std(returns) * sqrt(252)`
- **Rejects if**: `volatility > 0.40` (40%)

#### Sub-Filter 2C: Current Day Gap (if market open)
**Function**: `_detect_current_gap()`
**Config**: [config/settings.yaml:65](../config/settings.yaml#L65)

**Analysis**:
- Compares today's open vs yesterday's close
- **Rejects if**: Current gap > 5.0% (max_overnight_gap_percent)

**Combined Decision**: `_is_suitable_for_trading()`
- Must pass ALL THREE: gap frequency, volatility, current gap
- If ANY fail → stock excluded from `gap_filtered_symbols`

**Output**: `gap_filtered_symbols` (list of symbols passing gap risk)

---

### STAGE 3: ~~Position Limit Check~~ REMOVED
**Previously**: Limited to top 5 stocks only
**Now**: All gap-filtered stocks are evaluated
**Rationale**: Let Stage 6 (existing positions) and Stage 8 (position sizing) control portfolio limits instead of arbitrary caps

---

### STAGE 4: Execution Gap Check (Real-time)
**Component**: `gap_detector.can_execute_trade()`
**Location**: [src/risk/gap_detector.py:343-426](../src/risk/gap_detector.py#L343-L426)

**Per-stock real-time check before any trade consideration:**

#### Real-Time Gap Calculation:
1. Get current market price (mid of bid/ask)
2. Get previous trading day's close
3. Calculate: `gap_percent = ((current - previous) / previous) * 100`

**Hard Stop**:
- **Threshold**: 1.5% (execution_gap_threshold)
- **Config**: [config/settings.yaml:74](../config/settings.yaml#L74)
- **Action**: If `|gap_percent| > 1.5%` → **Block trade**, skip to next stock

**Failure Modes**:
- `no_previous_close_data` - Can't find previous close
- `execution_gap_exceeded` - Gap too large
- `gap_check_error` - Exception during check

**Log Output**: "Trade execution blocked by gap check" with reason

---

### STAGE 5: Wheel State Check
**Component**: `wheel_state.can_sell_puts()` / `can_sell_calls()`
**Location**: [src/strategy/wheel_engine.py:291-304](../src/strategy/wheel_engine.py#L291-L304)

**Checks**:

1. **For Calls**: `wheel_state.can_sell_calls(symbol)`
   - Only if we're in `HOLDING_STOCK` phase
   - Already own the underlying stock
   - Used for covered calls

2. **For Puts**: `wheel_state.can_sell_puts(symbol)`
   - Only if NOT in `HOLDING_STOCK` or `SELLING_CALLS` phase
   - Don't already have stock position
   - Used for cash-secured puts

**Skip if**: Wrong wheel phase for the trade type

---

### STAGE 6: Existing Position Check
**Component**: `_has_existing_option_position()`
**Location**: [src/strategy/wheel_engine.py:306-307](../src/strategy/wheel_engine.py#L306-L307)

**Filter**:
- Checks Alpaca account for existing option positions in this symbol
- **Skip if**: Already have options in this underlying
- **Purpose**: Prevent multiple concurrent positions in same stock

---

### STAGE 7: Options Chain Criteria (Put-Specific)
**Component**: `market_data.find_suitable_puts()` → `_meets_put_criteria()`
**Location**: [src/api/market_data.py:204-231](../src/api/market_data.py#L204-L231)

**For each put contract in the options chain:**

#### Filter 7A: Days to Expiration (DTE)
- **Target**: 7 days
- **Max**: Must be ≤ 7 days
- **Config**: [config/settings.yaml:14](../config/settings.yaml#L14)
- **Rejects**: Options expiring > 7 days out

#### Filter 7B: Minimum Premium
- **Threshold**: $0.50 per contract
- **Config**: [config/settings.yaml:26](../config/settings.yaml#L26)
- **Rejects**: Puts with mid_price < $0.50

#### Filter 7C: Delta Range
- **Range**: 0.10 to 0.20 (absolute value)
- **Config**: [config/settings.yaml:18](../config/settings.yaml#L18)
- **Rejects**: Puts outside delta range
- **Purpose**: Target ~10-20% probability of assignment

#### Filter 7D: Liquidity Check
- **Minimum**: Open Interest ≥ 10 contracts OR volume > 0
- **Rejects**: Illiquid contracts
- **Purpose**: Ensure ability to close position if needed

#### Ranking:
After filtering, remaining puts are ranked by:
- **Score**: `annual_return * (1 - |delta|)`
- **Preference**: Higher return, lower delta (less likely assignment)
- **Best put**: First in sorted list selected

**Output**: Best put opportunity or `None` if no suitable options

---

### STAGE 8: Position Sizing Validation
**Component**: `put_seller._calculate_position_size()`
**Location**: [src/strategy/put_seller.py](../src/strategy/put_seller.py)

**Checks**:

1. **Account Buying Power**
   - Requires: `strike_price * 100 * contracts` in cash
   - For multiple contracts: scales accordingly

2. **Max Exposure Per Ticker**
   - **Limit**: $25,000 per underlying
   - **Config**: [config/settings.yaml:39](../config/settings.yaml#L39)

3. **Portfolio Allocation**
   - **Max total**: 80% of portfolio
   - **Min cash reserve**: 20%
   - **Config**: [config/settings.yaml:44-46](../config/settings.yaml#L44-L46)

**Rejects if**: Insufficient buying power or exceeds risk limits

---

### STAGE 9: ~~Conservative Execution Limit~~ REMOVED
**Previously**: Only 1 new position per cycle
**Now**: Multiple positions can be opened per cycle (as many as pass all filters)
**Rationale**:
- Stage 8 position sizing already limits exposure ($25k per ticker, 80% portfolio max)
- Stage 6 prevents duplicate positions in same underlying
- Max 10 total positions enforced by config
- Let portfolio limits and risk controls dictate capacity, not arbitrary per-cycle caps

---

## Summary: Filter Funnel

```
14 Stocks (universe)
    ↓
STAGE 1: Price & Volume
    ↓ (~12-14 stocks typically pass)
STAGE 2: Gap Risk Analysis
    ├── Historical Gap Frequency ≤ 15%
    ├── Historical Volatility ≤ 40%
    └── Current Gap ≤ 5%
    ↓ (~7-10 stocks pass)
STAGE 3: [REMOVED - No arbitrary stock limit]
    ↓ (ALL gap-filtered stocks evaluated)
STAGE 4: Execution Gap Check (per stock)
    └── Real-time gap ≤ 1.5%
    ↓
STAGE 5: Wheel State Check (per stock)
    └── Can sell puts/calls in current phase?
    ↓
STAGE 6: Existing Position Check (per stock)
    └── No existing options in this symbol?
    ↓
STAGE 7: Options Chain Criteria (per contract)
    ├── DTE ≤ 7 days
    ├── Premium ≥ $0.50
    ├── Delta: 0.10-0.20
    └── Liquidity ≥ 10 OI or volume > 0
    ↓
STAGE 8: Position Sizing (per opportunity)
    ├── Sufficient buying power?
    ├── ≤ $25k exposure per ticker?
    ├── ≤ 80% portfolio allocation?
    └── ≤ 10 total positions (config)
    ↓
STAGE 9: [REMOVED - No per-cycle limit]
    ↓
0-N Trades Executed (limited by buying power, position limits, and risk controls)
```

---

## Why Stocks Get Filtered Out

### Common Rejection Reasons (by stage):

**Stage 1 - Price/Volume**:
- Stock too cheap (< $10) or expensive (> $400)
- Low liquidity (< 2M avg volume)

**Stage 2 - Gap Risk**:
- **Most common rejection**
- AMD: High gap frequency (20.6% > 15%)
- Volatile tech stocks often fail here

**Stage 4 - Execution Gap**:
- Intraday movement > 1.5% from previous close
- Market volatility during trading hours

**Stage 5 - Wheel State**:
- Already holding stock (can't sell puts)
- No stock position (can't sell calls)

**Stage 6 - Existing Position**:
- Already have options in this underlying
- Portfolio concentration limit

**Stage 7 - Options Chain**:
- **Very common**
- No 7-day options available
- Strikes outside delta range
- Premiums too low (< $0.50)
- Illiquid options (OI < 10)

**Stage 8 - Position Sizing**:
- Insufficient buying power
- Would exceed $25k single-ticker limit
- Portfolio already at 80% allocation
- Already at max 10 total positions

**~~Stage 3 & 9~~** (REMOVED):
- Previously limited to 5 stocks evaluated and 1 position per cycle
- Now portfolio naturally limited by risk controls in Stages 6 & 8

---

## Configuration Reference

All thresholds are configurable in [config/settings.yaml](../config/settings.yaml)

| Filter | Parameter | Default | Config Line |
|--------|-----------|---------|-------------|
| Price Range | min_stock_price | $10.00 | 30 |
| Price Range | max_stock_price | $400.00 | 31 |
| Volume | min_avg_volume | 2M shares | 32 |
| Gap Frequency | max_gap_frequency | 15% | 67 |
| Historical Vol | max_historical_vol | 40% | 82 |
| Current Gap | max_overnight_gap_percent | 5.0% | 65 |
| Execution Gap | execution_gap_threshold | 1.5% | 74 |
| Quality Gap | quality_gap_threshold | 2.0% | 71 |
| Put DTE | put_target_dte | 7 days | 14 |
| Put Premium | min_put_premium | $0.50 | 26 |
| Put Delta | put_delta_range | [0.10, 0.20] | 18 |
| Max Exposure | max_exposure_per_ticker | $25,000 | 39 |
| Portfolio Limit | max_portfolio_allocation | 80% | 44 |

---

## Monitoring Filters in Production

### Key Logs to Watch:

**After Stage 1**:
```json
{
  "event": "Filtered suitable stocks",
  "total_analyzed": 14,
  "suitable_count": N
}
```

**After Stage 2**:
```json
{
  "event": "Evaluating new opportunities with wheel state logic",
  "suitable_stocks": N,
  "gap_filtered_stocks": M,
  "gap_filtered_symbols": ["MSFT", "GOOGL", ...],
  "filtered_out_symbols": ["AMD", "UNH"]
}
```

**Stage 2 Rejections**:
```json
{
  "event_type": "stock_filtered_by_gap_risk",
  "symbol": "AMD",
  "gap_risk_score": 0.74,
  "gap_frequency": 0.206,
  "historical_volatility": 0.35
}
```

**Stage 4 Blocks**:
```json
{
  "event": "Trade execution blocked by gap check",
  "symbol": "AAPL",
  "reason": "execution_gap_exceeded",
  "gap_percent": 1.8
}
```

**Final Summary**:
```json
{
  "event": "New opportunities search completed",
  "opportunities_found": N,
  "put_opportunities": N,
  "call_opportunities": N
}
```

---

## Recent Improvements (Oct 3, 2025)

1. **Fixed datetime bug** in gap detector affecting 5 stocks
   - [Commit bcbbb23](https://github.com/memon1987/options_wheel/commit/bcbbb23)

2. **Fixed logging configuration** to see all filter decisions
   - [Commit 9fea03d](https://github.com/memon1987/options_wheel/commit/9fea03d)

3. **Added enhanced debug logging** for gap filtering
   - Shows exactly which stocks pass/fail at each stage

---

**Next**: Monitor first hourly execution at 10:00am ET today to see improved visibility into filtering decisions.
