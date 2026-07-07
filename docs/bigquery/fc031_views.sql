-- =====================================================================
-- FC-031 views — dashboard metrics overhaul
-- Plan: docs/plans/fc-031.md
--
-- Apply with:
--   bq query --use_legacy_sql=false < docs/bigquery/fc031_views.sql
-- Views are CREATE OR REPLACE — safe to re-run, no downtime.
-- =====================================================================

-- =================================================================
-- 1. monthly_option_cashflow
-- =================================================================
-- NET option cash flow by calendar month (ET), split put/call.
-- Replaces gross-premium-by-sale-date as the Overview bars source:
-- gross premium is revenue, not profit — a month with heavy rolling
-- (e.g. AMZN cycle 1's 9 rolls) overstates income unless buybacks are
-- netted in the month the cash actually left.
--
-- Source: fc018_acb_timeline_per_symbol.net_premium_delta, which is
-- already signed per event (+premium on opening sells, −cost on
-- buy-to-close; zero for OPASN/OPEXP markers).

CREATE OR REPLACE VIEW `options_wheel.fc031_monthly_option_cashflow` AS
SELECT
  FORMAT_DATE('%Y-%m', DATE(event_time, 'America/New_York')) AS month,
  SUM(net_premium_delta) AS net_option_cashflow,
  SUM(IF(option_type = 'put',  net_premium_delta, 0)) AS put_net_cashflow,
  SUM(IF(option_type = 'call', net_premium_delta, 0)) AS call_net_cashflow,
  -- Gross premium received in the month (opens only) — tooltip context,
  -- never the headline bar.
  SUM(IF(net_premium_delta > 0, net_premium_delta, 0)) AS gross_premium,
  SUM(IF(net_premium_delta < 0, -net_premium_delta, 0)) AS buyback_cost,
  COUNT(*) AS event_count
FROM `options_wheel.fc018_acb_timeline_per_symbol`
WHERE net_premium_delta IS NOT NULL AND net_premium_delta != 0
GROUP BY month;
