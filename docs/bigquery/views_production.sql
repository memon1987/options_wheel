-- ================================================================
-- BigQuery Views for Options Wheel Strategy - Production Version
-- Created: October 15, 2025
-- Purpose: Track daily executions and analyze backtesting results
-- Schema: Based on current logging structure from Oct 15 forward
-- ================================================================

-- Note: These views only query tables from Oct 15, 2025 onwards to avoid
-- schema conflicts with older tables. Use _20251015 as the minimum suffix.

-- ================================================================
-- VIEW 1: DAILY_EXECUTION_SUMMARY
-- Purpose: High-level daily execution tracking
-- Use case: Daily monitoring dashboard
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.daily_execution_summary` AS
SELECT
  DATE(timestamp, 'America/New_York') as date_et,

  -- Scan metrics
  COUNT(CASE WHEN jsonPayload.event = 'market_scan_completed' THEN 1 END) as total_scans,
  SUM(SAFE_CAST(jsonPayload.put_opportunities AS INT64)) as total_put_opportunities,
  SUM(SAFE_CAST(jsonPayload.call_opportunities AS INT64)) as total_call_opportunities,

  -- Performance metrics
  AVG(CASE WHEN jsonPayload.metric_name = 'market_scan_duration'
      THEN SAFE_CAST(jsonPayload.metric_value AS FLOAT64) END) as avg_scan_duration_seconds,

  -- Execution tracking
  COUNT(CASE WHEN jsonPayload.event = 'strategy_execution_completed' THEN 1 END) as total_executions,
  SUM(CASE WHEN jsonPayload.event = 'strategy_execution_completed'
      THEN SAFE_CAST(jsonPayload.trades_executed AS INT64) END) as total_trades_executed,
  SUM(CASE WHEN jsonPayload.event = 'strategy_execution_completed'
      THEN SAFE_CAST(jsonPayload.opportunities_evaluated AS INT64) END) as total_opportunities_evaluated,

  -- Time range
  MIN(timestamp) as first_event_utc,
  MAX(timestamp) as last_event_utc

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category IN ('system', 'performance')
  AND _TABLE_SUFFIX >= '20251015'
GROUP BY date_et
ORDER BY date_et DESC;

-- ================================================================
-- VIEW 2: SCAN_DETAILS
-- Purpose: Detailed scan-by-scan results
-- Use case: Analyze individual scan performance and opportunity discovery
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.scan_details` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp, 'America/New_York') as date_et,
  EXTRACT(HOUR FROM DATETIME(timestamp, 'America/New_York')) as hour_et,

  jsonPayload.event,
  jsonPayload.status,
  SAFE_CAST(jsonPayload.put_opportunities AS INT64) as put_opportunities,
  SAFE_CAST(jsonPayload.call_opportunities AS INT64) as call_opportunities,
  SAFE_CAST(jsonPayload.total_opportunities AS INT64) as total_opportunities,
  SAFE_CAST(jsonPayload.duration_seconds AS FLOAT64) as duration_seconds,
  SAFE_CAST(jsonPayload.stored_for_execution AS BOOL) as stored_for_execution,
  jsonPayload.blob_path,

  insertId

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event = 'market_scan_completed'
  AND _TABLE_SUFFIX >= '20251015'
ORDER BY timestamp DESC;

-- ================================================================
-- VIEW 3: EXECUTION_DETAILS
-- Purpose: Detailed execution results
-- Use case: Track strategy execution outcomes
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.execution_details` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp, 'America/New_York') as date_et,
  EXTRACT(HOUR FROM DATETIME(timestamp, 'America/New_York')) as hour_et,

  jsonPayload.event,
  jsonPayload.event_type,
  jsonPayload.status,
  SAFE_CAST(jsonPayload.opportunities_evaluated AS INT64) as opportunities_evaluated,
  SAFE_CAST(jsonPayload.trades_executed AS INT64) as trades_executed,
  SAFE_CAST(jsonPayload.trades_failed AS INT64) as trades_failed,
  SAFE_CAST(jsonPayload.duration_seconds AS FLOAT64) as duration_seconds,

  insertId

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event = 'strategy_execution_completed'
  AND _TABLE_SUFFIX >= '20251015'
ORDER BY timestamp DESC;

-- ================================================================
-- VIEW 4: FILTERING_PIPELINE
-- Purpose: Detailed filtering stage analysis
-- Use case: Understand which stocks pass/fail at each filtering stage
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.filtering_pipeline` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp, 'America/New_York') as date_et,

  jsonPayload.event,
  jsonPayload.event_type,
  jsonPayload.symbol,
  jsonPayload.reason,

  -- Stage identification (extract stage number from event_type)
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

  -- Pass/fail status
  CASE
    WHEN jsonPayload.event_type LIKE '%_passed' OR jsonPayload.event_type LIKE '%_complete_found' THEN 'PASSED'
    WHEN jsonPayload.event_type LIKE '%_blocked' OR jsonPayload.event_type LIKE '%_complete_not_found' THEN 'BLOCKED'
    ELSE 'UNKNOWN'
  END as stage_result,

  -- Price and volume data
  SAFE_CAST(jsonPayload.price AS FLOAT64) as price,
  SAFE_CAST(jsonPayload.avg_volume AS FLOAT64) as avg_volume,
  SAFE_CAST(jsonPayload.volatility AS FLOAT64) as volatility,

  -- Options chain data
  SAFE_CAST(jsonPayload.total_puts_in_chain AS INT64) as total_puts_in_chain,
  SAFE_CAST(jsonPayload.min_premium AS FLOAT64) as min_premium,
  SAFE_CAST(jsonPayload.target_dte AS INT64) as target_dte,

  insertId

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'filtering'
  AND _TABLE_SUFFIX >= '20251015'
ORDER BY timestamp DESC;

-- ================================================================
-- VIEW 5: PERFORMANCE_METRICS
-- Purpose: All performance and timing metrics
-- Use case: Performance analysis and optimization
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.performance_metrics` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp, 'America/New_York') as date_et,

  jsonPayload.metric_name,
  SAFE_CAST(jsonPayload.metric_value AS FLOAT64) as metric_value,
  jsonPayload.metric_unit,

  -- Context fields
  SAFE_CAST(jsonPayload.opportunities_found AS INT64) as opportunities_found,
  SAFE_CAST(jsonPayload.symbols_scanned AS INT64) as symbols_scanned,
  SAFE_CAST(jsonPayload.suitable_stocks AS INT64) as suitable_stocks,
  SAFE_CAST(jsonPayload.stock_positions AS INT64) as stock_positions,
  SAFE_CAST(jsonPayload.positions_with_100_shares AS INT64) as positions_with_100_shares,
  SAFE_CAST(jsonPayload.avg_score AS FLOAT64) as avg_score,
  SAFE_CAST(jsonPayload.avg_annual_return AS FLOAT64) as avg_annual_return,

  insertId

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'performance'
  AND _TABLE_SUFFIX >= '20251015'
ORDER BY timestamp DESC;

-- ================================================================
-- VIEW 6: BACKTEST_RESULTS
-- Purpose: Backtesting analysis results
-- Use case: Evaluate historical performance
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.backtest_results` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp, 'America/New_York') as date_et,

  jsonPayload.backtest_id,
  jsonPayload.start_date,
  jsonPayload.end_date,
  jsonPayload.symbols,
  SAFE_CAST(jsonPayload.symbol_count AS INT64) as symbol_count,
  SAFE_CAST(jsonPayload.trading_days AS INT64) as trading_days,
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
  SAFE_CAST(jsonPayload.avg_at_risk_capital AS FLOAT64) as avg_at_risk_capital,
  SAFE_CAST(jsonPayload.peak_at_risk_percentage AS FLOAT64) as peak_at_risk_percentage,

  -- Trading metrics
  SAFE_CAST(jsonPayload.total_trades AS INT64) as total_trades,
  SAFE_CAST(jsonPayload.put_trades AS INT64) as put_trades,
  SAFE_CAST(jsonPayload.call_trades AS INT64) as call_trades,
  SAFE_CAST(jsonPayload.assignments AS INT64) as assignments,
  SAFE_CAST(jsonPayload.assignment_rate AS FLOAT64) as assignment_rate,
  SAFE_CAST(jsonPayload.win_rate AS FLOAT64) as win_rate,
  SAFE_CAST(jsonPayload.premium_collected AS FLOAT64) as premium_collected,

  SAFE_CAST(jsonPayload.gap_detection_enabled AS BOOL) as gap_detection_enabled,
  SAFE_CAST(jsonPayload.success AS BOOL) as success,

  insertId

FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'backtest'
  AND jsonPayload.event_type = 'backtest_completed'
  AND _TABLE_SUFFIX >= '20251015'
ORDER BY timestamp DESC;
