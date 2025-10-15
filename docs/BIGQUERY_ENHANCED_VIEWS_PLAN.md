# Enhanced BigQuery Views - Comprehensive Analytics Plan

**Objective**: Provide detailed visibility across all program operations for weekly calendar evaluation

**Date**: October 15, 2025

---

## Current State Assessment

### Existing Views (4)
1. ✅ `daily_execution_summary` - High-level daily metrics
2. ✅ `scan_details` - Individual scan results
3. ✅ `filtering_pipeline` - Stage-by-stage filtering
4. ✅ `performance_metrics` - Timing data

### Available Event Categories in Logs
Based on Oct 15, 2025 data:
- **filtering** - All 9 filtering stages (28 events)
- **system** - Strategy cycles, scans, executions (21 events)
- **performance** - Metrics and timing (3 events)
- **trade** - Trade execution (not yet in current logs)
- **error** - Error tracking (not yet in current logs)
- **risk** - Gap detection and risk events (not yet in current logs)
- **backtest** - Backtesting results (not yet in current logs)
- **position_update** - Wheel state transitions (not yet in current logs)

---

## Proposed Enhanced View Structure

### Category 1: Daily Operations Overview
**Purpose**: Executive dashboard for daily/weekly performance tracking

#### View 1.1: `daily_operations_summary`
**What it shows**: Complete daily overview with all key metrics
```sql
CREATE OR REPLACE VIEW `options_wheel_logs.daily_operations_summary` AS
SELECT
  DATE(timestamp, 'America/New_York') as date_et,

  -- Scan metrics
  COUNT(CASE WHEN jsonPayload.event = 'market_scan_completed' THEN 1 END) as total_scans,
  AVG(CASE WHEN jsonPayload.event = 'market_scan_completed'
      THEN SAFE_CAST(jsonPayload.duration_seconds AS FLOAT64) END) as avg_scan_duration,

  -- Opportunity metrics
  SUM(SAFE_CAST(jsonPayload.put_opportunities AS INT64)) as total_put_opps,
  SUM(SAFE_CAST(jsonPayload.call_opportunities AS INT64)) as total_call_opps,
  SUM(SAFE_CAST(jsonPayload.total_opportunities AS INT64)) as total_opportunities,

  -- Execution metrics
  COUNT(CASE WHEN jsonPayload.event = 'strategy_execution_completed' THEN 1 END) as total_executions,
  SUM(SAFE_CAST(jsonPayload.trades_executed AS INT64)) as trades_executed,
  SUM(SAFE_CAST(jsonPayload.trades_failed AS INT64)) as trades_failed,

  -- Error metrics
  COUNT(CASE WHEN jsonPayload.event_category = 'error' THEN 1 END) as total_errors,

  -- Performance metrics
  AVG(CASE WHEN jsonPayload.metric_name = 'market_scan_duration'
      THEN SAFE_CAST(jsonPayload.metric_value AS FLOAT64) END) as avg_scan_seconds

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE _TABLE_SUFFIX >= '20251015'
GROUP BY date_et
ORDER BY date_et DESC;
```

**Use Case**:
- Daily/weekly performance tracking
- Identify days with issues (high errors, low opportunities)
- Track scan frequency and timing

---

#### View 1.2: `hourly_scan_execution_timeline`
**What it shows**: Hour-by-hour breakdown of scans and executions
```sql
CREATE OR REPLACE VIEW `options_wheel_logs.hourly_scan_execution_timeline` AS
WITH scan_events AS (
  SELECT
    DATE(timestamp, 'America/New_York') as date_et,
    EXTRACT(HOUR FROM DATETIME(timestamp, 'America/New_York')) as hour_et,
    EXTRACT(MINUTE FROM DATETIME(timestamp, 'America/New_York')) as minute_et,
    'SCAN' as event_phase,
    SAFE_CAST(jsonPayload.put_opportunities AS INT64) as put_opps,
    SAFE_CAST(jsonPayload.call_opportunities AS INT64) as call_opps,
    SAFE_CAST(jsonPayload.duration_seconds AS FLOAT64) as duration_seconds
  FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
  WHERE jsonPayload.event = 'market_scan_completed'
    AND _TABLE_SUFFIX >= '20251015'
),
execution_events AS (
  SELECT
    DATE(timestamp, 'America/New_York') as date_et,
    EXTRACT(HOUR FROM DATETIME(timestamp, 'America/New_York')) as hour_et,
    EXTRACT(MINUTE FROM DATETIME(timestamp, 'America/New_York')) as minute_et,
    'EXECUTION' as event_phase,
    SAFE_CAST(jsonPayload.opportunities_evaluated AS INT64) as opportunities_evaluated,
    SAFE_CAST(jsonPayload.trades_executed AS INT64) as trades_executed,
    SAFE_CAST(jsonPayload.duration_seconds AS FLOAT64) as duration_seconds
  FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
  WHERE jsonPayload.event = 'strategy_execution_completed'
    AND _TABLE_SUFFIX >= '20251015'
)
SELECT * FROM scan_events
UNION ALL
SELECT
  date_et,
  hour_et,
  minute_et,
  event_phase,
  opportunities_evaluated as put_opps,
  trades_executed as call_opps,
  duration_seconds
FROM execution_events
ORDER BY date_et DESC, hour_et, minute_et;
```

**Use Case**:
- Verify 6 scans/day running at :00 (10am, 11am, 12pm, 1pm, 2pm, 3pm)
- Verify 6 executions/day running at :15
- Identify missing scheduled runs
- Track hourly opportunity discovery patterns

---

### Category 2: Risk Filtering Analysis
**Purpose**: Detailed funnel analysis of filtering stages

#### View 2.1: `filtering_stage_summary`
**What it shows**: Daily stage-by-stage pass/block rates
```sql
CREATE OR REPLACE VIEW `options_wheel_logs.filtering_stage_summary` AS
SELECT
  DATE(timestamp, 'America/New_York') as date_et,
  CASE
    WHEN jsonPayload.event_type LIKE 'stage_1%' THEN 1
    WHEN jsonPayload.event_type LIKE 'stage_2%' THEN 2
    WHEN jsonPayload.event_type LIKE 'stage_3%' THEN 3
    WHEN jsonPayload.event_type LIKE 'stage_4%' THEN 4
    WHEN jsonPayload.event_type LIKE 'stage_5%' THEN 5
    WHEN jsonPayload.event_type LIKE 'stage_6%' THEN 6
    WHEN jsonPayload.event_type LIKE 'stage_7%' THEN 7
    WHEN jsonPayload.event_type LIKE 'stage_8%' THEN 8
    WHEN jsonPayload.event_type LIKE 'stage_9%' THEN 9
  END as stage_number,
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

  -- Summary metrics
  COUNT(*) as total_events,
  COUNT(DISTINCT jsonPayload.symbol) as unique_symbols,

  -- Pass/block counts
  SUM(CASE WHEN jsonPayload.event_type LIKE '%_passed' THEN 1 ELSE 0 END) as passed,
  SUM(CASE WHEN jsonPayload.event_type LIKE '%_blocked' THEN 1 ELSE 0 END) as blocked,
  SUM(CASE WHEN jsonPayload.event_type LIKE '%_found' THEN 1 ELSE 0 END) as found,
  SUM(CASE WHEN jsonPayload.event_type LIKE '%_not_found' THEN 1 ELSE 0 END) as not_found,

  -- Stage 1 specific
  MAX(SAFE_CAST(jsonPayload.passed AS INT64)) as stage1_passed_count,
  MAX(SAFE_CAST(jsonPayload.rejected AS INT64)) as stage1_rejected_count,

  -- Symbols lists
  ARRAY_AGG(DISTINCT jsonPayload.symbol IGNORE NULLS) as symbols_processed

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'filtering'
  AND _TABLE_SUFFIX >= '20251015'
GROUP BY date_et, stage_number, stage_name
ORDER BY date_et DESC, stage_number;
```

**Use Case**:
- Complete filtering funnel analysis
- Identify bottleneck stages (highest rejection rate)
- Track daily filtering efficiency
- See which symbols pass/fail each stage

---

#### View 2.2: `symbol_filtering_journey`
**What it shows**: Per-symbol path through all 9 stages
```sql
CREATE OR REPLACE VIEW `options_wheel_logs.symbol_filtering_journey` AS
SELECT
  DATE(timestamp, 'America/New_York') as date_et,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  jsonPayload.symbol,

  -- Stage identification
  CASE
    WHEN jsonPayload.event_type LIKE 'stage_1%' THEN 1
    WHEN jsonPayload.event_type LIKE 'stage_2%' THEN 2
    WHEN jsonPayload.event_type LIKE 'stage_3%' THEN 3
    WHEN jsonPayload.event_type LIKE 'stage_4%' THEN 4
    WHEN jsonPayload.event_type LIKE 'stage_5%' THEN 5
    WHEN jsonPayload.event_type LIKE 'stage_6%' THEN 6
    WHEN jsonPayload.event_type LIKE 'stage_7%' THEN 7
    WHEN jsonPayload.event_type LIKE 'stage_8%' THEN 8
    WHEN jsonPayload.event_type LIKE 'stage_9%' THEN 9
  END as stage_number,

  jsonPayload.event_type,
  jsonPayload.event,

  -- Result
  CASE
    WHEN jsonPayload.event_type LIKE '%_passed' THEN 'PASSED'
    WHEN jsonPayload.event_type LIKE '%_blocked' THEN 'BLOCKED'
    WHEN jsonPayload.event_type LIKE '%_found' THEN 'FOUND'
    WHEN jsonPayload.event_type LIKE '%_not_found' THEN 'NOT_FOUND'
    WHEN jsonPayload.event_type LIKE '%_complete' THEN 'COMPLETE'
  END as stage_result,

  -- Key metrics by stage
  jsonPayload.reason,
  SAFE_CAST(jsonPayload.gap_percent AS FLOAT64) as gap_percent,
  SAFE_CAST(jsonPayload.gap_frequency AS FLOAT64) as gap_frequency,
  SAFE_CAST(jsonPayload.historical_volatility AS FLOAT64) as volatility,
  SAFE_CAST(jsonPayload.buying_power AS FLOAT64) as buying_power,
  SAFE_CAST(jsonPayload.max_contracts_allowed AS INT64) as max_contracts,
  SAFE_CAST(jsonPayload.suitable_puts AS INT64) as suitable_puts

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'filtering'
  AND _TABLE_SUFFIX >= '20251015'
  AND jsonPayload.symbol IS NOT NULL
ORDER BY date_et DESC, timestamp_et, stage_number;
```

**Use Case**:
- Trace individual symbol filtering path
- Answer "Why wasn't AAPL traded today?"
- Debug filtering logic
- Identify patterns in rejections

---

#### View 2.3: `stage1_price_volume_analysis`
**What it shows**: Daily Stage 1 results with passed/rejected symbols
```sql
CREATE OR REPLACE VIEW `options_wheel_logs.stage1_price_volume_analysis` AS
SELECT
  DATE(timestamp, 'America/New_York') as date_et,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,

  SAFE_CAST(jsonPayload.total_analyzed AS INT64) as total_stocks,
  SAFE_CAST(jsonPayload.passed AS INT64) as passed_count,
  SAFE_CAST(jsonPayload.rejected AS INT64) as rejected_count,

  ROUND(SAFE_CAST(jsonPayload.passed AS INT64) /
        SAFE_CAST(jsonPayload.total_analyzed AS INT64) * 100, 1) as pass_rate_pct,

  jsonPayload.passed_symbols,
  jsonPayload.rejected_symbols

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'filtering'
  AND jsonPayload.event_type = 'stage_1_complete'
  AND _TABLE_SUFFIX >= '20251015'
ORDER BY date_et DESC, timestamp_et DESC;
```

**Use Case**:
- Track which stocks fail basic price/volume criteria
- Monitor if universe shrinks over time
- Identify consistently rejected symbols

---

#### View 2.4: `stage7_options_chain_analysis`
**What it shows**: Options chain scanning results by symbol
```sql
CREATE OR REPLACE VIEW `options_wheel_logs.stage7_options_chain_analysis` AS
SELECT
  DATE(timestamp, 'America/New_York') as date_et,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  jsonPayload.symbol,

  jsonPayload.event_type,

  CASE
    WHEN jsonPayload.event_type = 'stage_7_complete_found' THEN 'FOUND'
    WHEN jsonPayload.event_type = 'stage_7_complete_not_found' THEN 'NOT_FOUND'
    WHEN jsonPayload.event_type = 'stage_7_start' THEN 'SCANNING'
  END as result,

  SAFE_CAST(jsonPayload.suitable_puts AS INT64) as suitable_puts_count,
  SAFE_CAST(jsonPayload.total_puts_in_chain AS INT64) as total_puts_scanned,

  jsonPayload.reason as rejection_reason,

  -- Rejection reason breakdown
  SAFE_CAST(jsonPayload.rejected_premium_too_low AS INT64) as rejected_premium_low,
  SAFE_CAST(jsonPayload.rejected_delta_out_of_range AS INT64) as rejected_delta_wrong,
  SAFE_CAST(jsonPayload.rejected_dte_too_high AS INT64) as rejected_dte_high,
  SAFE_CAST(jsonPayload.rejected_no_liquidity AS INT64) as rejected_illiquid,

  -- Best put found
  SAFE_CAST(jsonPayload.best_put_strike AS FLOAT64) as best_strike,
  SAFE_CAST(jsonPayload.best_put_premium AS FLOAT64) as best_premium,
  SAFE_CAST(jsonPayload.best_put_delta AS FLOAT64) as best_delta,
  SAFE_CAST(jsonPayload.best_put_dte AS INT64) as best_dte

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'filtering'
  AND jsonPayload.event_type LIKE 'stage_7%'
  AND _TABLE_SUFFIX >= '20251015'
ORDER BY date_et DESC, timestamp_et, symbol;
```

**Use Case**:
- Understand options chain rejection reasons
- Track options availability by symbol
- Identify if premiums are too low or deltas wrong
- Best opportunities found per symbol

---

### Category 3: Trade Execution Tracking
**Purpose**: Monitor all trading activity and results

#### View 3.1: `trades_executed`
**What it shows**: All trades with complete details
```sql
CREATE OR REPLACE VIEW `options_wheel_logs.trades_executed` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp, 'America/New_York') as date_et,

  jsonPayload.event_type,
  jsonPayload.symbol,
  jsonPayload.underlying,
  jsonPayload.strategy,

  -- Trade details
  SAFE_CAST(jsonPayload.strike_price AS FLOAT64) as strike_price,
  SAFE_CAST(jsonPayload.premium AS FLOAT64) as premium,
  SAFE_CAST(jsonPayload.contracts AS INT64) as contracts,
  SAFE_CAST(jsonPayload.limit_price AS FLOAT64) as limit_price,
  SAFE_CAST(jsonPayload.dte AS INT64) as dte,

  -- Financial impact
  SAFE_CAST(jsonPayload.collateral_required AS FLOAT64) as collateral_required,
  SAFE_CAST(jsonPayload.premium AS FLOAT64) *
    SAFE_CAST(jsonPayload.contracts AS INT64) * 100 as total_premium,

  -- Success tracking
  SAFE_CAST(jsonPayload.success AS BOOL) as success,
  jsonPayload.order_id,
  jsonPayload.error_message,

  -- Context
  SAFE_CAST(jsonPayload.buying_power_before AS FLOAT64) as buying_power_before,
  SAFE_CAST(jsonPayload.buying_power_after AS FLOAT64) as buying_power_after

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'trade'
  AND _TABLE_SUFFIX >= '20251015'
ORDER BY timestamp DESC;
```

**Use Case**:
- Complete trade log with all executed trades
- Track success/failure rates
- Calculate total premiums collected
- Monitor capital deployment

---

#### View 3.2: `execution_cycle_results`
**What it shows**: Results of each execution cycle (every :15)
```sql
CREATE OR REPLACE VIEW `options_wheel_logs.execution_cycle_results` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp, 'America/New_York') as date_et,
  EXTRACT(HOUR FROM DATETIME(timestamp, 'America/New_York')) as hour_et,

  jsonPayload.status,

  -- Opportunity metrics
  SAFE_CAST(jsonPayload.opportunities_evaluated AS INT64) as opportunities_evaluated,
  SAFE_CAST(jsonPayload.opportunities_executed AS INT64) as opportunities_executed,

  -- Trade results
  SAFE_CAST(jsonPayload.trades_executed AS INT64) as trades_executed,
  SAFE_CAST(jsonPayload.trades_failed AS INT64) as trades_failed,

  -- Buying power tracking
  SAFE_CAST(jsonPayload.buying_power_start AS FLOAT64) as buying_power_start,
  SAFE_CAST(jsonPayload.buying_power_end AS FLOAT64) as buying_power_end,
  SAFE_CAST(jsonPayload.buying_power_used AS FLOAT64) as buying_power_used,

  -- Performance
  SAFE_CAST(jsonPayload.duration_seconds AS FLOAT64) as duration_seconds

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event = 'strategy_execution_completed'
  AND _TABLE_SUFFIX >= '20251015'
ORDER BY timestamp DESC;
```

**Use Case**:
- Track execution cycle success rates
- Monitor buying power utilization
- Identify cycles with failures
- Performance timing analysis

---

### Category 4: Error Tracking
**Purpose**: Comprehensive error monitoring and debugging

#### View 4.1: `errors_all`
**What it shows**: All errors with context
```sql
CREATE OR REPLACE VIEW `options_wheel_logs.errors_all` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp, 'America/New_York') as date_et,
  severity,

  jsonPayload.error_type,
  jsonPayload.error_message,
  jsonPayload.component,
  jsonPayload.event,

  -- Context
  jsonPayload.symbol,
  jsonPayload.underlying,
  SAFE_CAST(jsonPayload.strike_price AS FLOAT64) as strike_price,

  -- Error details
  SAFE_CAST(jsonPayload.recoverable AS BOOL) as recoverable,
  SAFE_CAST(jsonPayload.required AS FLOAT64) as required,
  SAFE_CAST(jsonPayload.available AS FLOAT64) as available,
  SAFE_CAST(jsonPayload.shortage AS FLOAT64) as shortage

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'error'
  AND _TABLE_SUFFIX >= '20251015'
ORDER BY timestamp DESC;
```

**Use Case**:
- Monitor all errors across system
- Track error frequency and types
- Identify recurring issues
- Debug trade failures

---

#### View 4.2: `errors_daily_summary`
**What it shows**: Daily error counts by type
```sql
CREATE OR REPLACE VIEW `options_wheel_logs.errors_daily_summary` AS
SELECT
  DATE(timestamp, 'America/New_York') as date_et,

  COUNT(*) as total_errors,
  COUNT(DISTINCT jsonPayload.error_type) as unique_error_types,

  -- By severity
  SUM(CASE WHEN severity = 'ERROR' THEN 1 ELSE 0 END) as errors,
  SUM(CASE WHEN severity = 'WARNING' THEN 1 ELSE 0 END) as warnings,
  SUM(CASE WHEN severity = 'CRITICAL' THEN 1 ELSE 0 END) as critical,

  -- By component
  COUNT(CASE WHEN jsonPayload.component = 'market_data' THEN 1 END) as market_data_errors,
  COUNT(CASE WHEN jsonPayload.component = 'trade_execution' THEN 1 END) as trade_errors,
  COUNT(CASE WHEN jsonPayload.component = 'risk_management' THEN 1 END) as risk_errors,

  -- Recoverable
  SUM(CASE WHEN SAFE_CAST(jsonPayload.recoverable AS BOOL) = TRUE THEN 1 ELSE 0 END) as recoverable_errors,

  -- Top error messages
  ARRAY_AGG(DISTINCT jsonPayload.error_message LIMIT 10) as top_error_messages

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'error'
  AND _TABLE_SUFFIX >= '20251015'
GROUP BY date_et
ORDER BY date_et DESC;
```

**Use Case**:
- Daily error dashboard
- Identify error spikes
- Track error recovery rates
- Monitor system health

---

### Category 5: Performance & Timing
**Purpose**: System performance monitoring

#### View 5.1: `performance_detailed`
**What it shows**: All performance metrics with trends
```sql
CREATE OR REPLACE VIEW `options_wheel_logs.performance_detailed` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp, 'America/New_York') as date_et,

  jsonPayload.metric_name,
  SAFE_CAST(jsonPayload.metric_value AS FLOAT64) as metric_value,
  jsonPayload.metric_unit,

  -- Context
  SAFE_CAST(jsonPayload.symbols_scanned AS INT64) as symbols_scanned,
  SAFE_CAST(jsonPayload.opportunities_found AS INT64) as opportunities_found,
  SAFE_CAST(jsonPayload.duration_seconds AS FLOAT64) as duration_seconds

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'performance'
  AND _TABLE_SUFFIX >= '20251015'
ORDER BY timestamp DESC;
```

**Use Case**:
- Track scan performance over time
- Identify performance degradation
- Optimize slow operations

---

### Category 6: Backtesting Results
**Purpose**: Historical backtest analysis

#### View 6.1: `backtest_results_complete`
**What it shows**: Full backtest results with all metrics
```sql
CREATE OR REPLACE VIEW `options_wheel_logs.backtest_results_complete` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp, 'America/New_York') as date_et,

  jsonPayload.backtest_id,
  jsonPayload.start_date,
  jsonPayload.end_date,
  SAFE_CAST(jsonPayload.duration_seconds AS FLOAT64) as duration_seconds,

  -- Capital metrics
  SAFE_CAST(jsonPayload.initial_capital AS FLOAT64) as initial_capital,
  SAFE_CAST(jsonPayload.final_capital AS FLOAT64) as final_capital,
  SAFE_CAST(jsonPayload.total_return AS FLOAT64) as total_return,
  SAFE_CAST(jsonPayload.annualized_return AS FLOAT64) as annualized_return,

  -- Risk metrics
  SAFE_CAST(jsonPayload.max_drawdown AS FLOAT64) as max_drawdown,
  SAFE_CAST(jsonPayload.sharpe_ratio AS FLOAT64) as sharpe_ratio,
  SAFE_CAST(jsonPayload.max_at_risk_capital AS FLOAT64) as max_at_risk_capital,

  -- Trading metrics
  SAFE_CAST(jsonPayload.total_trades AS INT64) as total_trades,
  SAFE_CAST(jsonPayload.put_trades AS INT64) as put_trades,
  SAFE_CAST(jsonPayload.call_trades AS INT64) as call_trades,
  SAFE_CAST(jsonPayload.win_rate AS FLOAT64) as win_rate,
  SAFE_CAST(jsonPayload.premium_collected AS FLOAT64) as premium_collected,

  -- Configuration
  jsonPayload.symbols,
  SAFE_CAST(jsonPayload.gap_detection_enabled AS BOOL) as gap_detection_enabled,

  SAFE_CAST(jsonPayload.success AS BOOL) as success

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'backtest'
  AND jsonPayload.event_type = 'backtest_completed'
  AND _TABLE_SUFFIX >= '20251015'
ORDER BY timestamp DESC;
```

**Use Case**:
- Compare backtest results
- Track strategy performance over time
- Evaluate configuration changes

---

## Summary of Proposed Views

### Total: 13 New Views + 4 Existing = 17 Total Views

**Daily Operations** (2 views):
1. ✨ `daily_operations_summary` - Executive dashboard
2. ✨ `hourly_scan_execution_timeline` - Hour-by-hour timeline

**Risk Filtering** (4 views):
3. ✨ `filtering_stage_summary` - Stage-by-stage funnel
4. ✨ `symbol_filtering_journey` - Per-symbol paths
5. ✨ `stage1_price_volume_analysis` - Stage 1 details
6. ✨ `stage7_options_chain_analysis` - Stage 7 options scanning

**Trade Execution** (2 views):
7. ✨ `trades_executed` - All trades log
8. ✨ `execution_cycle_results` - Cycle results

**Error Tracking** (2 views):
9. ✨ `errors_all` - Complete error log
10. ✨ `errors_daily_summary` - Daily error dashboard

**Performance** (1 view):
11. ✨ `performance_detailed` - Performance metrics

**Backtesting** (1 view):
12. ✨ `backtest_results_complete` - Full backtest analysis

**Existing** (4 views):
13. ✅ `daily_execution_summary`
14. ✅ `scan_details`
15. ✅ `filtering_pipeline`
16. ✅ `performance_metrics`

---

## Implementation Priority

### Phase 1: Critical Views (Implement First)
1. `daily_operations_summary` - Need this for daily tracking
2. `filtering_stage_summary` - Core filtering visibility
3. `symbol_filtering_journey` - Debug why symbols rejected
4. `errors_all` - Error monitoring

### Phase 2: Trade & Execution Views
5. `trades_executed` - Once trades start executing
6. `execution_cycle_results` - Track cycle success
7. `hourly_scan_execution_timeline` - Verify schedule

### Phase 3: Deep Dive Analysis
8. `stage1_price_volume_analysis` - Stage details
9. `stage7_options_chain_analysis` - Options analysis
10. `errors_daily_summary` - Error trends

### Phase 4: Performance & Backtesting
11. `performance_detailed` - Performance monitoring
12. `backtest_results_complete` - When backtests run

---

## Key Benefits

### For Daily Operations
- Single dashboard view for daily/weekly performance
- Hour-by-hour execution timeline
- Immediate error visibility

### For Risk Analysis
- Complete filtering funnel from 14 stocks → trades
- Understand why each stock passes/fails
- Identify filtering bottlenecks

### For Trade Evaluation
- Complete trade history with outcomes
- Cycle-by-cycle execution tracking
- Capital deployment monitoring

### For Debugging
- Comprehensive error tracking
- Symbol-level filtering journey
- Performance metrics and timing

### For Strategy Evaluation
- Backtest result comparisons
- Historical performance tracking
- Configuration impact analysis

---

## Next Steps

1. **Review this plan** - Confirm these views meet your needs
2. **Prioritize views** - Which ones do you want first?
3. **Create SQL file** - Write complete CREATE VIEW statements
4. **Test with real data** - Verify with execution logs (need trades)
5. **Create example queries** - Build query library for common questions
6. **Document usage** - Update BigQuery usage guide

Would you like me to proceed with implementing Phase 1 views first?
