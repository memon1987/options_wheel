-- BigQuery Views for Options Wheel Strategy Analytics
-- These views flatten the log data for easy querying

-- ================================================================
-- 1. TRADES VIEW - All trading activity
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.trades` AS
SELECT
  timestamp,
  DATE(timestamp) as trade_date,
  jsonPayload.event_type,
  jsonPayload.symbol,
  jsonPayload.underlying,
  jsonPayload.strategy,
  CAST(jsonPayload.strike_price AS FLOAT64) as strike_price,
  CAST(jsonPayload.premium AS FLOAT64) as premium,
  CAST(jsonPayload.contracts AS INT64) as contracts,
  CAST(jsonPayload.limit_price AS FLOAT64) as limit_price,
  CAST(jsonPayload.success AS BOOL) as success,
  jsonPayload.order_id,
  CAST(jsonPayload.collateral_required AS FLOAT64) as collateral_required,
  CAST(jsonPayload.dte AS INT64) as dte,
  CAST(jsonPayload.shares_covered AS INT64) as shares_covered,
  CAST(jsonPayload.stock_cost_basis AS FLOAT64) as stock_cost_basis,
  CAST(jsonPayload.total_return_if_called AS FLOAT64) as total_return_if_called,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*`
WHERE jsonPayload.event_category = 'trade';

-- ================================================================
-- 2. RISK EVENTS VIEW - Gap detection and risk management
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.risk_events` AS
SELECT
  timestamp,
  DATE(timestamp) as event_date,
  jsonPayload.event_type,
  jsonPayload.symbol,
  jsonPayload.risk_type,
  jsonPayload.action_taken,
  CAST(jsonPayload.gap_percent AS FLOAT64) as gap_percent,
  CAST(jsonPayload.threshold AS FLOAT64) as threshold,
  CAST(jsonPayload.gap_risk_score AS FLOAT64) as gap_risk_score,
  CAST(jsonPayload.gap_frequency AS FLOAT64) as gap_frequency,
  CAST(jsonPayload.historical_volatility AS FLOAT64) as historical_volatility,
  CAST(jsonPayload.previous_close AS FLOAT64) as previous_close,
  CAST(jsonPayload.current_price AS FLOAT64) as current_price,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*`
WHERE jsonPayload.event_category = 'risk';

-- ================================================================
-- 3. PERFORMANCE METRICS VIEW - Timing and efficiency
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.performance_metrics` AS
SELECT
  timestamp,
  DATE(timestamp) as metric_date,
  jsonPayload.metric_name,
  CAST(jsonPayload.metric_value AS FLOAT64) as metric_value,
  jsonPayload.metric_unit,
  CAST(jsonPayload.duration_seconds AS FLOAT64) as duration_seconds,
  CAST(jsonPayload.actions_taken AS INT64) as actions_taken,
  CAST(jsonPayload.symbols_scanned AS INT64) as symbols_scanned,
  CAST(jsonPayload.suitable_stocks AS INT64) as suitable_stocks,
  CAST(jsonPayload.gap_filtered_stocks AS INT64) as gap_filtered_stocks,
  CAST(jsonPayload.opportunities_found AS INT64) as opportunities_found,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*`
WHERE jsonPayload.event_category = 'performance';

-- ================================================================
-- 4. ERRORS VIEW - Error tracking and debugging
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.errors` AS
SELECT
  timestamp,
  DATE(timestamp) as error_date,
  jsonPayload.error_type,
  jsonPayload.error_message,
  jsonPayload.component,
  CAST(jsonPayload.recoverable AS BOOL) as recoverable,
  jsonPayload.symbol,
  jsonPayload.underlying,
  CAST(jsonPayload.strike_price AS FLOAT64) as strike_price,
  CAST(jsonPayload.contracts AS INT64) as contracts,
  CAST(jsonPayload.required AS FLOAT64) as required,
  CAST(jsonPayload.available AS FLOAT64) as available,
  CAST(jsonPayload.shortage AS FLOAT64) as shortage,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*`
WHERE jsonPayload.event_category = 'error';

-- ================================================================
-- 5. SYSTEM EVENTS VIEW - Strategy cycles and jobs
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.system_events` AS
SELECT
  timestamp,
  DATE(timestamp) as event_date,
  jsonPayload.event_type,
  jsonPayload.status,
  CAST(jsonPayload.duration_seconds AS FLOAT64) as duration_seconds,
  CAST(jsonPayload.actions_taken AS INT64) as actions_taken,
  CAST(jsonPayload.new_positions AS INT64) as new_positions,
  CAST(jsonPayload.closed_positions AS INT64) as closed_positions,
  CAST(jsonPayload.positions_analyzed AS INT64) as positions_analyzed,
  CAST(jsonPayload.put_opportunities AS INT64) as put_opportunities,
  CAST(jsonPayload.call_opportunities AS INT64) as call_opportunities,
  CAST(jsonPayload.total_opportunities AS INT64) as total_opportunities,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*`
WHERE jsonPayload.event_category = 'system';

-- ================================================================
-- 6. POSITION UPDATES VIEW - Wheel state transitions
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.position_updates` AS
SELECT
  timestamp,
  DATE(timestamp) as update_date,
  jsonPayload.event_type,
  jsonPayload.symbol,
  jsonPayload.position_type,
  jsonPayload.action,
  CAST(jsonPayload.shares AS INT64) as shares,
  CAST(jsonPayload.assignment_price AS FLOAT64) as assignment_price,
  CAST(jsonPayload.total_shares AS INT64) as total_shares,
  CAST(jsonPayload.avg_cost_basis AS FLOAT64) as avg_cost_basis,
  CAST(jsonPayload.capital_gain AS FLOAT64) as capital_gain,
  CAST(jsonPayload.realized_pnl AS FLOAT64) as realized_pnl,
  CAST(jsonPayload.remaining_shares AS INT64) as remaining_shares,
  jsonPayload.phase_before,
  jsonPayload.phase_after,
  CAST(jsonPayload.wheel_cycle_completed AS BOOL) as wheel_cycle_completed,
  CAST(jsonPayload.wheel_cycle_started AS BOOL) as wheel_cycle_started,
  CAST(jsonPayload.cycle_duration_days AS INT64) as cycle_duration_days,
  CAST(jsonPayload.total_premium_collected AS FLOAT64) as total_premium_collected,
  CAST(jsonPayload.total_return AS FLOAT64) as total_return,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*`
WHERE jsonPayload.event_category = 'position_update';
