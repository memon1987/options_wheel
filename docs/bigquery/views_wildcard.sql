-- BigQuery Views for Options Wheel Strategy Analytics
-- Uses wildcard tables (_*) to query across all dated log tables
-- Only includes fields that exist in the merged schema (last 30 days of tables)
-- For missing fields, query the raw jsonPayload or use TO_JSON_STRING()

-- ================================================================
-- 1. SYSTEM EVENTS VIEW - Strategy cycles and jobs
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.system_events` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  jsonPayload.event_type,
  jsonPayload.event,
  jsonPayload.event_category,
  jsonPayload.status,
  SAFE_CAST(jsonPayload.duration_seconds AS FLOAT64) as duration_seconds,
  SAFE_CAST(jsonPayload.put_opportunities AS FLOAT64) as put_opportunities,
  SAFE_CAST(jsonPayload.call_opportunities AS FLOAT64) as call_opportunities,
  SAFE_CAST(jsonPayload.total_opportunities AS FLOAT64) as total_opportunities,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'system'
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY));

-- ================================================================
-- 2. PERFORMANCE METRICS VIEW - Timing and efficiency
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.performance_metrics` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  jsonPayload.event,
  jsonPayload.event_category,
  jsonPayload.event_type,
  jsonPayload.metric_name,
  SAFE_CAST(jsonPayload.metric_value AS FLOAT64) as metric_value,
  jsonPayload.metric_unit,
  SAFE_CAST(jsonPayload.opportunities_found AS FLOAT64) as opportunities_found,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'performance'
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY));

-- ================================================================
-- 3. FILTERING EVENTS VIEW - Stage-by-stage filtering pipeline
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.filtering_events` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  jsonPayload.event,
  jsonPayload.event_category,
  jsonPayload.event_type,
  jsonPayload.symbol,
  jsonPayload.reason,
  SAFE_CAST(jsonPayload.price AS FLOAT64) as price,
  SAFE_CAST(jsonPayload.avg_volume AS FLOAT64) as avg_volume,
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = 'filtering'
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY));

-- ================================================================
-- 4. ALL EVENTS VIEW - All structured log events
-- Includes event, event_category, event_type for all logs
-- Use this as a base for custom queries
-- ================================================================
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.all_events` AS
SELECT
  timestamp as timestamp_utc,
  DATETIME(timestamp, 'America/New_York') as timestamp_et,
  DATE(timestamp) as date_utc,
  DATE(timestamp, 'America/New_York') as date_et,
  jsonPayload.event,
  jsonPayload.event_category,
  jsonPayload.event_type,
  jsonPayload.logger,
  jsonPayload.level,
  jsonPayload.symbol,
  jsonPayload.status,
  jsonPayload.reason,
  TO_JSON_STRING(jsonPayload) as payload_json,  -- Full JSON for custom extraction
  insertId,
  severity
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event IS NOT NULL
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY));

-- ================================================================
-- USAGE EXAMPLES
-- ================================================================

-- Example 1: Get recent market scans with opportunity counts
-- SELECT * FROM `options_wheel_logs.system_events`
-- WHERE event = 'market_scan_completed'
-- AND date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
-- ORDER BY timestamp_et DESC;

-- Example 2: Get performance metrics for scan duration
-- SELECT
--   timestamp_et,
--   metric_name,
--   metric_value,
--   metric_unit
-- FROM `options_wheel_logs.performance_metrics`
-- WHERE metric_name = 'market_scan_duration'
-- ORDER BY timestamp_et DESC LIMIT 10;

-- Example 3: Get filtering events for a specific symbol
-- SELECT * FROM `options_wheel_logs.filtering_events`
-- WHERE symbol = 'NVDA'
-- ORDER BY timestamp_et DESC LIMIT 20;

-- Example 4: Extract custom fields from payload_json
-- SELECT
--   timestamp_et,
--   event,
--   JSON_VALUE(payload_json, '$.premium') as premium,
--   JSON_VALUE(payload_json, '$.strike_price') as strike_price
-- FROM `options_wheel_logs.all_events`
-- WHERE event_category = 'trade';
