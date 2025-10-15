-- BigQuery Views for Options Wheel Strategy Analytics
-- These views flatten the log data for easy querying
-- Note: Timestamps are provided in both UTC and Eastern Time (America/New_York)

-- ================================================================
-- 1. TRADES VIEW - All trading activity
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.trades` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  JSON_VALUE(jsonPayload.event_type) as event_type,
  JSON_VALUE(jsonPayload.symbol) as symbol,
  JSON_VALUE(jsonPayload.underlying) as underlying,
  JSON_VALUE(jsonPayload.strategy) as strategy,
  CAST(JSON_VALUE(jsonPayload.strike_price) AS FLOAT64) as strike_price,
  CAST(JSON_VALUE(jsonPayload.premium) AS FLOAT64) as premium,
  CAST(JSON_VALUE(jsonPayload.contracts) AS INT64) as contracts,
  CAST(JSON_VALUE(jsonPayload.limit_price) AS FLOAT64) as limit_price,
  CAST(JSON_VALUE(jsonPayload.success) AS BOOL) as success,
  JSON_VALUE(jsonPayload.order_id) as order_id,
  CAST(JSON_VALUE(jsonPayload.collateral_required) AS FLOAT64) as collateral_required,
  CAST(JSON_VALUE(jsonPayload.dte) AS INT64) as dte,
  CAST(JSON_VALUE(jsonPayload.shares_covered) AS INT64) as shares_covered,
  CAST(JSON_VALUE(jsonPayload.stock_cost_basis) AS FLOAT64) as stock_cost_basis,
  CAST(JSON_VALUE(jsonPayload.total_return_if_called) AS FLOAT64) as total_return_if_called,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr`
WHERE JSON_VALUE(jsonPayload.event_category) = 'trade';

-- ================================================================
-- 2. RISK EVENTS VIEW - Gap detection and risk management
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.risk_events` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  JSON_VALUE(jsonPayload.event_type) as event_type,
  JSON_VALUE(jsonPayload.symbol) as symbol,
  JSON_VALUE(jsonPayload.risk_type) as risk_type,
  JSON_VALUE(jsonPayload.action_taken) as action_taken,
  CAST(JSON_VALUE(jsonPayload.gap_percent) AS FLOAT64) as gap_percent,
  CAST(JSON_VALUE(jsonPayload.threshold) AS FLOAT64) as threshold,
  CAST(JSON_VALUE(jsonPayload.gap_risk_score) AS FLOAT64) as gap_risk_score,
  CAST(JSON_VALUE(jsonPayload.gap_frequency) AS FLOAT64) as gap_frequency,
  CAST(JSON_VALUE(jsonPayload.historical_volatility) AS FLOAT64) as historical_volatility,
  CAST(JSON_VALUE(jsonPayload.previous_close) AS FLOAT64) as previous_close,
  CAST(JSON_VALUE(jsonPayload.current_price) AS FLOAT64) as current_price,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr`
WHERE JSON_VALUE(jsonPayload.event_category) = 'risk';

-- ================================================================
-- 3. PERFORMANCE METRICS VIEW - Timing and efficiency
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.performance_metrics` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  JSON_VALUE(jsonPayload.metric_name) as metric_name,
  CAST(JSON_VALUE(jsonPayload.metric_value) AS FLOAT64) as metric_value,
  JSON_VALUE(jsonPayload.metric_unit) as metric_unit,
  CAST(JSON_VALUE(jsonPayload.duration_seconds) AS FLOAT64) as duration_seconds,
  CAST(JSON_VALUE(jsonPayload.actions_taken) AS INT64) as actions_taken,
  CAST(JSON_VALUE(jsonPayload.symbols_scanned) AS INT64) as symbols_scanned,
  CAST(JSON_VALUE(jsonPayload.suitable_stocks) AS INT64) as suitable_stocks,
  CAST(JSON_VALUE(jsonPayload.gap_filtered_stocks) AS INT64) as gap_filtered_stocks,
  CAST(JSON_VALUE(jsonPayload.opportunities_found) AS INT64) as opportunities_found,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr`
WHERE JSON_VALUE(jsonPayload.event_category) = 'performance';

-- ================================================================
-- 4. ERRORS VIEW - Error tracking and debugging
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.errors` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  JSON_VALUE(jsonPayload.error_type) as error_type,
  JSON_VALUE(jsonPayload.error_message) as error_message,
  JSON_VALUE(jsonPayload.component) as component,
  CAST(JSON_VALUE(jsonPayload.recoverable) AS BOOL) as recoverable,
  JSON_VALUE(jsonPayload.symbol) as symbol,
  JSON_VALUE(jsonPayload.underlying) as underlying,
  CAST(JSON_VALUE(jsonPayload.strike_price) AS FLOAT64) as strike_price,
  CAST(JSON_VALUE(jsonPayload.contracts) AS INT64) as contracts,
  CAST(JSON_VALUE(jsonPayload.required) AS FLOAT64) as required,
  CAST(JSON_VALUE(jsonPayload.available) AS FLOAT64) as available,
  CAST(JSON_VALUE(jsonPayload.shortage) AS FLOAT64) as shortage,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr`
WHERE JSON_VALUE(jsonPayload.event_category) = 'error';

-- ================================================================
-- 5. SYSTEM EVENTS VIEW - Strategy cycles and jobs
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.system_events` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  JSON_VALUE(jsonPayload.event_type) as event_type,
  JSON_VALUE(jsonPayload.status) as status,
  CAST(JSON_VALUE(jsonPayload.duration_seconds) AS FLOAT64) as duration_seconds,
  CAST(JSON_VALUE(jsonPayload.actions_taken) AS INT64) as actions_taken,
  CAST(JSON_VALUE(jsonPayload.new_positions) AS INT64) as new_positions,
  CAST(JSON_VALUE(jsonPayload.closed_positions) AS INT64) as closed_positions,
  CAST(JSON_VALUE(jsonPayload.positions_analyzed) AS INT64) as positions_analyzed,
  CAST(JSON_VALUE(jsonPayload.put_opportunities) AS INT64) as put_opportunities,
  CAST(JSON_VALUE(jsonPayload.call_opportunities) AS INT64) as call_opportunities,
  CAST(JSON_VALUE(jsonPayload.total_opportunities) AS INT64) as total_opportunities,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr`
WHERE JSON_VALUE(jsonPayload.event_category) = 'system';

-- ================================================================
-- 6. POSITION UPDATES VIEW - Wheel state transitions
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.position_updates` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  JSON_VALUE(jsonPayload.event_type) as event_type,
  JSON_VALUE(jsonPayload.symbol) as symbol,
  JSON_VALUE(jsonPayload.position_type) as position_type,
  JSON_VALUE(jsonPayload.action) as action,
  CAST(JSON_VALUE(jsonPayload.shares) AS INT64) as shares,
  CAST(JSON_VALUE(jsonPayload.assignment_price) AS FLOAT64) as assignment_price,
  CAST(JSON_VALUE(jsonPayload.total_shares) AS INT64) as total_shares,
  CAST(JSON_VALUE(jsonPayload.avg_cost_basis) AS FLOAT64) as avg_cost_basis,
  CAST(JSON_VALUE(jsonPayload.capital_gain) AS FLOAT64) as capital_gain,
  CAST(JSON_VALUE(jsonPayload.realized_pnl) AS FLOAT64) as realized_pnl,
  CAST(JSON_VALUE(jsonPayload.remaining_shares) AS INT64) as remaining_shares,
  JSON_VALUE(jsonPayload.phase_before) as phase_before,
  JSON_VALUE(jsonPayload.phase_after) as phase_after,
  CAST(JSON_VALUE(jsonPayload.wheel_cycle_completed) AS BOOL) as wheel_cycle_completed,
  CAST(JSON_VALUE(jsonPayload.wheel_cycle_started) AS BOOL) as wheel_cycle_started,
  CAST(JSON_VALUE(jsonPayload.cycle_duration_days) AS INT64) as cycle_duration_days,
  CAST(JSON_VALUE(jsonPayload.total_premium_collected) AS FLOAT64) as total_premium_collected,
  CAST(JSON_VALUE(jsonPayload.total_return) AS FLOAT64) as total_return,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr`
WHERE JSON_VALUE(jsonPayload.event_category) = 'position_update';

-- ================================================================
-- 7. BACKTEST RESULTS VIEW - Historical backtesting analysis
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.backtest_results` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  JSON_VALUE(jsonPayload.event_type) as event_type,
  JSON_VALUE(jsonPayload.backtest_id) as backtest_id,
  JSON_VALUE(jsonPayload.start_date) as start_date,
  JSON_VALUE(jsonPayload.end_date) as end_date,
  CAST(JSON_VALUE(jsonPayload.duration_seconds) AS FLOAT64) as duration_seconds,

  -- Capital metrics
  CAST(JSON_VALUE(jsonPayload.initial_capital) AS FLOAT64) as initial_capital,
  CAST(JSON_VALUE(jsonPayload.final_capital) AS FLOAT64) as final_capital,
  CAST(JSON_VALUE(jsonPayload.total_return) AS FLOAT64) as total_return,
  CAST(JSON_VALUE(jsonPayload.annualized_return) AS FLOAT64) as annualized_return,

  -- Risk metrics
  CAST(JSON_VALUE(jsonPayload.max_drawdown) AS FLOAT64) as max_drawdown,
  CAST(JSON_VALUE(jsonPayload.sharpe_ratio) AS FLOAT64) as sharpe_ratio,
  CAST(JSON_VALUE(jsonPayload.max_at_risk_capital) AS FLOAT64) as max_at_risk_capital,
  CAST(JSON_VALUE(jsonPayload.avg_at_risk_capital) AS FLOAT64) as avg_at_risk_capital,
  CAST(JSON_VALUE(jsonPayload.peak_at_risk_percentage) AS FLOAT64) as peak_at_risk_percentage,

  -- Trading metrics
  CAST(JSON_VALUE(jsonPayload.total_trades) AS INT64) as total_trades,
  CAST(JSON_VALUE(jsonPayload.put_trades) AS INT64) as put_trades,
  CAST(JSON_VALUE(jsonPayload.call_trades) AS INT64) as call_trades,
  CAST(JSON_VALUE(jsonPayload.assignments) AS INT64) as assignments,
  CAST(JSON_VALUE(jsonPayload.assignment_rate) AS FLOAT64) as assignment_rate,
  CAST(JSON_VALUE(jsonPayload.win_rate) AS FLOAT64) as win_rate,
  CAST(JSON_VALUE(jsonPayload.premium_collected) AS FLOAT64) as premium_collected,

  -- Configuration
  JSON_VALUE(jsonPayload.symbols) as symbols,
  CAST(JSON_VALUE(jsonPayload.symbol_count) AS INT64) as symbol_count,
  CAST(JSON_VALUE(jsonPayload.trading_days) AS INT64) as trading_days,
  CAST(JSON_VALUE(jsonPayload.gap_detection_enabled) AS BOOL) as gap_detection_enabled,

  -- Success indicator
  CAST(JSON_VALUE(jsonPayload.success) AS BOOL) as success,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr`
WHERE JSON_VALUE(jsonPayload.event_category) = 'backtest' AND JSON_VALUE(jsonPayload.event_type) = 'backtest_completed';
