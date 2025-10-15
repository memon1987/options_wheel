-- BigQuery Views for Options Wheel Strategy Analytics
-- These views flatten the log data for easy querying
-- Note: Timestamps are provided in both UTC and Eastern Time (America/New_York)
-- Uses wildcard tables (_*) with _TABLE_SUFFIX filtering to handle schema evolution

-- ================================================================
-- 1. TRADES VIEW - All trading activity
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.trades` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  jsonPayload.event_type,
  jsonPayload.symbol,
  jsonPayload.underlying,
  jsonPayload.strategy,
  SAFE_CAST(jsonPayload.strike_price AS FLOAT64) as strike_price,
  SAFE_CAST(jsonPayload.premium AS FLOAT64) as premium,
  SAFE_CAST(jsonPayload.contracts AS INT64) as contracts,
  SAFE_CAST(jsonPayload.limit_price AS FLOAT64) as limit_price,
  SAFE_CAST(jsonPayload.success AS BOOL) as success,
  jsonPayload.order_id,
  SAFE_CAST(jsonPayload.collateral_required AS FLOAT64) as collateral_required,
  SAFE_CAST(jsonPayload.dte AS INT64) as dte,
  SAFE_CAST(jsonPayload.shares_covered AS INT64) as shares_covered,
  SAFE_CAST(jsonPayload.stock_cost_basis AS FLOAT64) as stock_cost_basis,
  SAFE_CAST(jsonPayload.total_return_if_called AS FLOAT64) as total_return_if_called,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'trade'
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY));

-- ================================================================
-- 2. RISK EVENTS VIEW - Gap detection and risk management
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.risk_events` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  jsonPayload.event_type,
  jsonPayload.symbol,
  jsonPayload.risk_type,
  jsonPayload.action_taken,
  SAFE_CAST(jsonPayload.gap_percent AS FLOAT64) as gap_percent,
  SAFE_CAST(jsonPayload.threshold AS FLOAT64) as threshold,
  SAFE_CAST(jsonPayload.gap_risk_score AS FLOAT64) as gap_risk_score,
  SAFE_CAST(jsonPayload.gap_frequency AS FLOAT64) as gap_frequency,
  SAFE_CAST(jsonPayload.historical_volatility AS FLOAT64) as historical_volatility,
  SAFE_CAST(jsonPayload.previous_close AS FLOAT64) as previous_close,
  SAFE_CAST(jsonPayload.current_price AS FLOAT64) as current_price,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'risk'
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY));

-- ================================================================
-- 3. PERFORMANCE METRICS VIEW - Timing and efficiency
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.performance_metrics` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  jsonPayload.metric_name,
  SAFE_CAST(jsonPayload.metric_value AS FLOAT64) as metric_value,
  jsonPayload.metric_unit,
  SAFE_CAST(jsonPayload.duration_seconds AS FLOAT64) as duration_seconds,
  SAFE_CAST(jsonPayload.actions_taken AS INT64) as actions_taken,
  SAFE_CAST(jsonPayload.symbols_scanned AS INT64) as symbols_scanned,
  SAFE_CAST(jsonPayload.suitable_stocks AS INT64) as suitable_stocks,
  SAFE_CAST(jsonPayload.gap_filtered_stocks AS INT64) as gap_filtered_stocks,
  SAFE_CAST(jsonPayload.opportunities_found AS INT64) as opportunities_found,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'performance'
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY));

-- ================================================================
-- 4. ERRORS VIEW - Error tracking and debugging
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.errors` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  jsonPayload.error_type,
  jsonPayload.error_message,
  jsonPayload.component,
  SAFE_CAST(jsonPayload.recoverable AS BOOL) as recoverable,
  jsonPayload.symbol,
  jsonPayload.underlying,
  SAFE_CAST(jsonPayload.strike_price AS FLOAT64) as strike_price,
  SAFE_CAST(jsonPayload.contracts AS INT64) as contracts,
  SAFE_CAST(jsonPayload.required AS FLOAT64) as required,
  SAFE_CAST(jsonPayload.available AS FLOAT64) as available,
  SAFE_CAST(jsonPayload.shortage AS FLOAT64) as shortage,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'error'
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY));

-- ================================================================
-- 5. SYSTEM EVENTS VIEW - Strategy cycles and jobs
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.system_events` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  jsonPayload.event_type,
  jsonPayload.event,
  jsonPayload.status,
  SAFE_CAST(jsonPayload.duration_seconds AS FLOAT64) as duration_seconds,
  SAFE_CAST(jsonPayload.actions_taken AS INT64) as actions_taken,
  SAFE_CAST(jsonPayload.new_positions AS INT64) as new_positions,
  SAFE_CAST(jsonPayload.closed_positions AS INT64) as closed_positions,
  SAFE_CAST(jsonPayload.positions_analyzed AS INT64) as positions_analyzed,
  SAFE_CAST(jsonPayload.put_opportunities AS INT64) as put_opportunities,
  SAFE_CAST(jsonPayload.call_opportunities AS INT64) as call_opportunities,
  SAFE_CAST(jsonPayload.total_opportunities AS INT64) as total_opportunities,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'system'
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY));

-- ================================================================
-- 6. POSITION UPDATES VIEW - Wheel state transitions
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.position_updates` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  jsonPayload.event_type,
  jsonPayload.symbol,
  jsonPayload.position_type,
  jsonPayload.action,
  SAFE_CAST(jsonPayload.shares AS INT64) as shares,
  SAFE_CAST(jsonPayload.assignment_price AS FLOAT64) as assignment_price,
  SAFE_CAST(jsonPayload.total_shares AS INT64) as total_shares,
  SAFE_CAST(jsonPayload.avg_cost_basis AS FLOAT64) as avg_cost_basis,
  SAFE_CAST(jsonPayload.capital_gain AS FLOAT64) as capital_gain,
  SAFE_CAST(jsonPayload.realized_pnl AS FLOAT64) as realized_pnl,
  SAFE_CAST(jsonPayload.remaining_shares AS INT64) as remaining_shares,
  jsonPayload.phase_before,
  jsonPayload.phase_after,
  SAFE_CAST(jsonPayload.wheel_cycle_completed AS BOOL) as wheel_cycle_completed,
  SAFE_CAST(jsonPayload.wheel_cycle_started AS BOOL) as wheel_cycle_started,
  SAFE_CAST(jsonPayload.cycle_duration_days AS INT64) as cycle_duration_days,
  SAFE_CAST(jsonPayload.total_premium_collected AS FLOAT64) as total_premium_collected,
  SAFE_CAST(jsonPayload.total_return AS FLOAT64) as total_return,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'position_update'
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY));

-- ================================================================
-- 7. BACKTEST RESULTS VIEW - Historical backtesting analysis
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.backtest_results` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  jsonPayload.event_type,
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

  -- Configuration
  jsonPayload.symbols,
  SAFE_CAST(jsonPayload.symbol_count AS INT64) as symbol_count,
  SAFE_CAST(jsonPayload.trading_days AS INT64) as trading_days,
  SAFE_CAST(jsonPayload.gap_detection_enabled AS BOOL) as gap_detection_enabled,

  -- Success indicator
  SAFE_CAST(jsonPayload.success AS BOOL) as success,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'backtest'
  AND jsonPayload.event_type = 'backtest_completed'
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY));
