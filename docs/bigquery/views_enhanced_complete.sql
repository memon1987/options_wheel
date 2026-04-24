-- ============================================================================
-- ENHANCED BIGQUERY VIEWS - COMPLETE SET
-- ============================================================================
-- Created: October 15, 2025
-- Purpose: Comprehensive analytics for Options Wheel Strategy monitoring
-- Total Views: 13 (organized into 6 categories)
-- ============================================================================

-- ============================================================================
-- CATEGORY 1: DAILY OPERATIONS OVERVIEW
-- ============================================================================

-- ----------------------------------------------------------------------------
-- VIEW 1.1: daily_operations_summary
-- Purpose: Executive dashboard for daily/weekly performance tracking
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.daily_operations_summary` AS
SELECT
  DATE(timestamp, 'America/New_York') as date_et,

  -- Scan metrics
  COUNT(CASE WHEN jsonPayload.event = 'market_scan_completed' THEN 1 END) as total_scans,
  AVG(CASE WHEN jsonPayload.event = 'market_scan_completed'
      THEN SAFE_CAST(jsonPayload.duration_seconds AS FLOAT64) END) as avg_scan_duration_sec,

  -- Opportunity metrics
  SUM(SAFE_CAST(jsonPayload.put_opportunities AS INT64)) as total_put_opportunities,
  SUM(SAFE_CAST(jsonPayload.call_opportunities AS INT64)) as total_call_opportunities,
  SUM(SAFE_CAST(jsonPayload.total_opportunities AS INT64)) as total_opportunities,

  -- Execution metrics
  COUNT(CASE WHEN jsonPayload.event = 'strategy_execution_completed' THEN 1 END) as total_executions,
  SUM(SAFE_CAST(jsonPayload.trades_executed AS INT64)) as trades_executed,
  SUM(SAFE_CAST(jsonPayload.trades_failed AS INT64)) as trades_failed,
  SUM(SAFE_CAST(jsonPayload.opportunities_evaluated AS INT64)) as opportunities_evaluated,

  -- Error metrics
  COUNT(CASE WHEN jsonPayload.event_category = 'error' THEN 1 END) as total_errors,
  COUNT(CASE WHEN severity = 'ERROR' THEN 1 END) as error_count,
  COUNT(CASE WHEN severity = 'WARNING' THEN 1 END) as warning_count,

  -- Performance metrics
  AVG(CASE WHEN jsonPayload.metric_name = 'market_scan_duration'
      THEN SAFE_CAST(jsonPayload.metric_value AS FLOAT64) END) as avg_scan_metric_value

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE _TABLE_SUFFIX >= '20251015'
GROUP BY date_et
ORDER BY date_et DESC;


-- ----------------------------------------------------------------------------
-- VIEW 1.2: hourly_scan_execution_timeline
-- Purpose: Hour-by-hour breakdown of scans and executions
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.hourly_scan_execution_timeline` AS
WITH scan_events AS (
  SELECT
    DATE(timestamp, 'America/New_York') as date_et,
    EXTRACT(HOUR FROM DATETIME(timestamp, 'America/New_York')) as hour_et,
    EXTRACT(MINUTE FROM DATETIME(timestamp, 'America/New_York')) as minute_et,
    DATETIME(timestamp, 'America/New_York') as timestamp_et,
    'SCAN' as event_phase,
    SAFE_CAST(jsonPayload.put_opportunities AS INT64) as metric1,
    SAFE_CAST(jsonPayload.call_opportunities AS INT64) as metric2,
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
    DATETIME(timestamp, 'America/New_York') as timestamp_et,
    'EXECUTION' as event_phase,
    SAFE_CAST(jsonPayload.opportunities_evaluated AS INT64) as metric1,
    SAFE_CAST(jsonPayload.trades_executed AS INT64) as metric2,
    SAFE_CAST(jsonPayload.duration_seconds AS FLOAT64) as duration_seconds
  FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
  WHERE jsonPayload.event = 'strategy_execution_completed'
    AND _TABLE_SUFFIX >= '20251015'
)
SELECT
  date_et,
  hour_et,
  minute_et,
  timestamp_et,
  event_phase,
  metric1,
  metric2,
  duration_seconds
FROM scan_events
UNION ALL
SELECT * FROM execution_events
ORDER BY date_et DESC, hour_et, minute_et;


-- ============================================================================
-- CATEGORY 2: RISK FILTERING ANALYSIS
-- ============================================================================

-- ----------------------------------------------------------------------------
-- VIEW 2.1: filtering_stage_summary
-- Purpose: Daily stage-by-stage pass/block rates for all 9 filtering stages
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.filtering_stage_summary` AS
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
  CASE
    WHEN jsonPayload.event_type LIKE 'stage_1%' THEN 'Price/Volume'
    WHEN jsonPayload.event_type LIKE 'stage_2%' THEN 'Gap Risk'
    WHEN jsonPayload.event_type LIKE 'stage_3%' THEN 'Stock Eval Limit'
    WHEN jsonPayload.event_type LIKE 'stage_4%' THEN 'Execution Gap'
    WHEN jsonPayload.event_type LIKE 'stage_5%' THEN 'Wheel State'
    WHEN jsonPayload.event_type LIKE 'stage_6%' THEN 'Existing Positions'
    WHEN jsonPayload.event_type LIKE 'stage_7%' THEN 'Options Chain'
    WHEN jsonPayload.event_type LIKE 'stage_8%' THEN 'Position Sizing'
    WHEN jsonPayload.event_type LIKE 'stage_9%' THEN 'Position Limit'
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
  MAX(SAFE_CAST(jsonPayload.total_analyzed AS INT64)) as stage1_total_analyzed

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'filtering'
  AND _TABLE_SUFFIX >= '20251015'
GROUP BY date_et, stage_number, stage_name
ORDER BY date_et DESC, stage_number;


-- ----------------------------------------------------------------------------
-- VIEW 2.2: symbol_filtering_journey
-- Purpose: Per-symbol path through all 9 filtering stages
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.symbol_filtering_journey` AS
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
  SAFE_CAST(jsonPayload.suitable_puts AS INT64) as suitable_puts,
  SAFE_CAST(jsonPayload.capital_required AS FLOAT64) as capital_required,
  SAFE_CAST(jsonPayload.portfolio_allocation AS FLOAT64) as portfolio_allocation

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'filtering'
  AND _TABLE_SUFFIX >= '20251015'
  AND jsonPayload.symbol IS NOT NULL
ORDER BY date_et DESC, timestamp_et, stage_number;


-- ----------------------------------------------------------------------------
-- VIEW 2.3: stage1_price_volume_analysis
-- Purpose: Daily Stage 1 results with passed/rejected symbols
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.stage1_price_volume_analysis` AS
SELECT
  DATE(timestamp, 'America/New_York') as date_et,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,

  SAFE_CAST(jsonPayload.total_analyzed AS INT64) as total_stocks,
  SAFE_CAST(jsonPayload.passed AS INT64) as passed_count,
  SAFE_CAST(jsonPayload.rejected AS INT64) as rejected_count,

  ROUND(SAFE_CAST(jsonPayload.passed AS INT64) /
        NULLIF(SAFE_CAST(jsonPayload.total_analyzed AS INT64), 0) * 100, 1) as pass_rate_pct,

  jsonPayload.passed_symbols,
  jsonPayload.rejected_symbols

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'filtering'
  AND jsonPayload.event_type = 'stage_1_complete'
  AND _TABLE_SUFFIX >= '20251015'
ORDER BY date_et DESC, timestamp_et DESC;


-- ----------------------------------------------------------------------------
-- VIEW 2.4: stage7_options_chain_analysis
-- Purpose: Options chain scanning results by symbol with rejection reasons
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.stage7_options_chain_analysis` AS
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


-- ============================================================================
-- CATEGORY 3: TRADE EXECUTION TRACKING
-- ============================================================================

-- ----------------------------------------------------------------------------
-- VIEW 3.1: trades_executed
-- Purpose: All trades with complete details and financial impact
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.trades_executed` AS
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
    SAFE_CAST(jsonPayload.contracts AS INT64) * 100 as total_premium_collected,

  -- Success tracking
  SAFE_CAST(jsonPayload.success AS BOOL) as success,
  jsonPayload.order_id,
  jsonPayload.error_message,

  -- Context
  SAFE_CAST(jsonPayload.buying_power_before AS FLOAT64) as buying_power_before,
  SAFE_CAST(jsonPayload.buying_power_after AS FLOAT64) as buying_power_after,
  SAFE_CAST(jsonPayload.buying_power AS FLOAT64) as buying_power

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'trade'
  AND _TABLE_SUFFIX >= '20251015'
ORDER BY timestamp DESC;


-- ----------------------------------------------------------------------------
-- VIEW 3.2: execution_cycle_results
-- Purpose: Results of each execution cycle (every :15)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.execution_cycle_results` AS
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


-- ============================================================================
-- CATEGORY 4: ERROR TRACKING
-- ============================================================================

-- ----------------------------------------------------------------------------
-- VIEW 4.1: errors_all
-- Purpose: All errors with context and recovery status
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.errors_all` AS
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
  SAFE_CAST(jsonPayload.shortage AS FLOAT64) as shortage,

  -- Full payload for debugging
  jsonPayload.logger as logger_name

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'error'
  AND _TABLE_SUFFIX >= '20251015'
ORDER BY timestamp DESC;


-- ----------------------------------------------------------------------------
-- VIEW 4.2: errors_daily_summary
-- Purpose: Daily error counts by type and severity
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.errors_daily_summary` AS
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

  -- Top error messages (limit to avoid huge arrays)
  ARRAY_AGG(DISTINCT jsonPayload.error_message IGNORE NULLS LIMIT 10) as top_error_messages

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'error'
  AND _TABLE_SUFFIX >= '20251015'
GROUP BY date_et
ORDER BY date_et DESC;


-- ============================================================================
-- CATEGORY 5: PERFORMANCE & TIMING
-- ============================================================================

-- ----------------------------------------------------------------------------
-- VIEW 5.1: performance_detailed
-- Purpose: All performance metrics with trends
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.performance_detailed` AS
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


-- ============================================================================
-- CATEGORY 6: BACKTESTING RESULTS
-- ============================================================================

-- ----------------------------------------------------------------------------
-- VIEW 6.1: backtest_results_complete
-- Purpose: Full backtest results with all metrics
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.backtest_results_complete` AS
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


-- ============================================================================
-- END OF VIEW DEFINITIONS
-- ============================================================================
