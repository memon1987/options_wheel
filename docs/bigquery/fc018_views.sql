-- FC-018 Phase B: views powering the wheel-centric dashboard rebuild.
--
-- All views read from FC-012 sources (`trades_with_outcomes`,
-- `wheel_cycles_from_activities`, `equity_history_from_alpaca`) plus the
-- new `stock_history_from_alpaca` table populated by
-- `src/data/stock_history_ingestor.py` (FC-018 PR B).
--
-- Deploy:
--   bq query --use_legacy_sql=false < docs/bigquery/fc018_views.sql
--
-- Naming is namespaced by `fc018_` to keep the FC's surface visible.
-- Views are CREATE OR REPLACE — safe to re-run.


-- =================================================================
-- 1. acb_timeline_per_symbol
-- =================================================================
-- One row per premium / assignment / called_away event, with a
-- running adjusted cost basis (ACB) per share.
--
-- Wheel community standard formula:
--   ACB = (share_cost - net_premiums_collected) / shares
-- Pre-assignment, ACB is undefined (0 shares) but cumulative net
-- premium is shown so the chart still has data.
--
-- This view IS the data source for the per-symbol drilldown's
-- ACB walk chart and for `acb_per_symbol_current`.

CREATE OR REPLACE VIEW `options_wheel.fc018_acb_timeline_per_symbol` AS
WITH events AS (
  -- All option-side events (puts and calls) with the underlying.
  SELECT
    underlying,
    transaction_time AS event_time,
    activity_id,
    activity_type,
    -- OCC contract symbol (e.g. AMD260417C00245000) for diagnosing/linking back to Alpaca
    symbol AS occ_symbol,
    order_id,
    expiration,
    option_type,
    side,
    qty,
    price,
    strike_price,
    premium_total,
    outcome,
    realized_pnl,
    -- Premium contribution (positive when collected, negative on close)
    CASE
      WHEN side IN ('sell_short', 'sell') THEN COALESCE(premium_total, 0)
      WHEN side IN ('buy_to_close', 'buy') THEN -COALESCE(premium_total, 0)
      ELSE 0
    END AS net_premium_delta,
    -- Share-count change (positive on assignment, negative on called-away)
    CASE
      WHEN activity_type = 'OPASN' AND option_type = 'put' THEN ABS(COALESCE(qty, 0)) * 100
      WHEN activity_type = 'OPASN' AND option_type = 'call' THEN -ABS(COALESCE(qty, 0)) * 100
      ELSE 0
    END AS shares_delta,
    -- Share-cost contribution at strike on assignment
    CASE
      WHEN activity_type = 'OPASN' AND option_type = 'put'
        THEN COALESCE(strike_price, 0) * ABS(COALESCE(qty, 0)) * 100
      WHEN activity_type = 'OPASN' AND option_type = 'call'
        THEN -COALESCE(strike_price, 0) * ABS(COALESCE(qty, 0)) * 100
      ELSE 0
    END AS share_cost_delta
  FROM `options_wheel.trades_with_outcomes`
  WHERE underlying IS NOT NULL
),
running AS (
  SELECT
    *,
    SUM(net_premium_delta) OVER (
      PARTITION BY underlying ORDER BY event_time
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_net_premium,
    SUM(shares_delta) OVER (
      PARTITION BY underlying ORDER BY event_time
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS running_shares,
    SUM(share_cost_delta) OVER (
      PARTITION BY underlying ORDER BY event_time
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS running_share_cost
  FROM events
)
SELECT
  underlying,
  event_time,
  DATE(event_time, 'America/New_York') AS event_date,
  activity_id,
  activity_type,
  occ_symbol,
  order_id,
  expiration,
  option_type,
  side,
  qty,
  strike_price,
  premium_total,
  outcome,
  realized_pnl,
  net_premium_delta,
  shares_delta,
  share_cost_delta,
  cumulative_net_premium,
  running_shares,
  running_share_cost,
  -- ACB only meaningful while shares are held
  CASE
    WHEN running_shares > 0
      THEN SAFE_DIVIDE(running_share_cost - cumulative_net_premium, running_shares)
    ELSE NULL
  END AS acb_per_share,
  -- Event label for chart annotations
  CASE
    WHEN activity_type = 'FILL' AND side IN ('sell_short', 'sell') AND option_type = 'put' THEN 'put_sold'
    WHEN activity_type = 'FILL' AND side IN ('sell_short', 'sell') AND option_type = 'call' THEN 'call_sold'
    WHEN activity_type = 'FILL' AND side IN ('buy_to_close', 'buy') THEN 'option_closed'
    WHEN activity_type = 'OPASN' AND option_type = 'put' THEN 'put_assigned'
    WHEN activity_type = 'OPASN' AND option_type = 'call' THEN 'called_away'
    WHEN activity_type = 'OPEXP' THEN 'expired'
    ELSE 'other'
  END AS event_label
FROM running;


-- =================================================================
-- 2. acb_per_symbol_current
-- =================================================================
-- Latest ACB per underlying (one row per symbol that ever traded).
-- Used by the Overview per-symbol scorecard.

CREATE OR REPLACE VIEW `options_wheel.fc018_acb_per_symbol_current` AS
SELECT
  underlying,
  ARRAY_AGG(STRUCT(
    event_time,
    running_shares,
    running_share_cost,
    cumulative_net_premium,
    acb_per_share
  ) ORDER BY event_time DESC LIMIT 1)[OFFSET(0)].* EXCEPT (event_time)
FROM `options_wheel.fc018_acb_timeline_per_symbol`
GROUP BY underlying;


-- =================================================================
-- 3. per_symbol_scorecard
-- =================================================================
-- One row per underlying with the columns the Overview matrix needs.
-- vs-buy-and-hold delta is joined in `vs_buy_and_hold_per_symbol`
-- (separate view because it needs `stock_history_from_alpaca`).

CREATE OR REPLACE VIEW `options_wheel.fc018_per_symbol_scorecard` AS
WITH trade_agg AS (
  SELECT
    underlying,
    COUNT(*) AS trade_count,
    SUM(COALESCE(premium_total, 0)) AS total_premium,
    SUM(CASE WHEN option_type = 'put' THEN COALESCE(premium_total, 0) ELSE 0 END) AS put_premium,
    SUM(CASE WHEN option_type = 'call' THEN COALESCE(premium_total, 0) ELSE 0 END) AS call_premium,
    SUM(COALESCE(realized_pnl, 0)) AS realized_pnl,
    COUNTIF(outcome = 'open') AS open_count,
    COUNTIF(outcome = 'assignment') AS put_assignment_count,
    COUNTIF(outcome = 'called_away') AS called_away_count,
    COUNTIF(outcome = 'early_close') AS early_close_count,
    COUNTIF(outcome = 'expiration') AS expiration_count,
    MIN(transaction_time) AS first_trade_time,
    MAX(transaction_time) AS last_trade_time
  FROM `options_wheel.trades_with_outcomes`
  WHERE underlying IS NOT NULL
  GROUP BY underlying
),
-- Share-side P&L: sum of OPTRD net_amount per underlying. Captures the
-- actual cash flow on assignment (negative — cash leaves to buy shares)
-- and called-away (positive — cash comes in when shares sell). Net of
-- all share movements is the true P&L from the stock leg of the wheel.
-- This is what the wheel_cycles view's (call_strike − put_strike)
-- approximation gets wrong when share lots overlap.
share_side_agg AS (
  SELECT
    symbol AS underlying,
    SUM(COALESCE(net_amount, 0)) AS share_side_pnl,
    COUNT(*) AS share_event_count
  FROM `options_wheel.trades_from_activities`
  WHERE activity_type = 'OPTRD'
    AND symbol IS NOT NULL AND symbol != ''
  GROUP BY symbol
),
cycle_agg AS (
  SELECT
    underlying,
    COUNT(*) AS cycles_completed,
    SUM(COALESCE(total_premium, 0)) AS cycle_total_premium,
    SUM(COALESCE(capital_gain, 0)) AS cycle_capital_gain,
    AVG(duration_days) AS avg_cycle_days
  FROM `options_wheel.wheel_cycles_from_activities`
  WHERE underlying IS NOT NULL
  GROUP BY underlying
)
SELECT
  COALESCE(t.underlying, c.underlying) AS underlying,
  t.trade_count,
  COALESCE(c.cycles_completed, 0) AS cycles_completed,
  t.total_premium,
  t.put_premium,
  t.call_premium,
  t.realized_pnl,
  -- Share-side P&L from actual OPTRD cash flow (FC-019). This is the
  -- truth for capital gains/losses on share movements, replacing the
  -- (call_strike − put_strike) approximation that fails on overlapping
  -- share lots.
  COALESCE(s.share_side_pnl, 0) AS share_side_pnl,
  -- Total realized P&L = realized option P&L + share-side P&L.
  -- This is what should reconcile to the headline Total Return
  -- (modulo unrealized on currently-open positions and fees).
  COALESCE(t.realized_pnl, 0) + COALESCE(s.share_side_pnl, 0)
    AS total_realized_pnl,
  t.open_count,
  t.put_assignment_count,
  t.called_away_count,
  t.early_close_count,
  t.expiration_count,
  c.cycle_capital_gain,
  c.avg_cycle_days,
  t.first_trade_time,
  t.last_trade_time,
  acb.running_shares AS current_shares,
  acb.acb_per_share AS current_acb_per_share,
  acb.cumulative_net_premium AS current_cumulative_net_premium
FROM trade_agg t
FULL OUTER JOIN cycle_agg c USING (underlying)
LEFT JOIN share_side_agg s USING (underlying)
LEFT JOIN `options_wheel.fc018_acb_per_symbol_current` acb
  ON acb.underlying = COALESCE(t.underlying, c.underlying);


-- =================================================================
-- 4. vs_buy_and_hold_per_symbol
-- =================================================================
-- For each underlying, compare actual wheel-strategy P&L against a
-- synthetic buy-and-hold: "what if I had bought the same dollar
-- amount of shares on the first trade and held to today?"
--
-- Requires `stock_history_from_alpaca` (FC-018 PR B ingestor).
-- If the table doesn't exist or has no data for a symbol, the
-- buy-and-hold columns are NULL.

CREATE OR REPLACE VIEW `options_wheel.fc018_vs_buy_and_hold_per_symbol` AS
WITH first_trade AS (
  SELECT
    underlying,
    MIN(DATE(transaction_time, 'America/New_York')) AS first_trade_date,
    -- Total dollar exposure first put: strike * 100 * qty (if a put was first)
    -- Use cumulative premium + collateral as the comparison baseline
    ARRAY_AGG(strike_price ORDER BY transaction_time ASC LIMIT 1)[OFFSET(0)] AS first_strike,
    ARRAY_AGG(qty ORDER BY transaction_time ASC LIMIT 1)[OFFSET(0)] AS first_qty
  FROM `options_wheel.trades_with_outcomes`
  WHERE underlying IS NOT NULL
  GROUP BY underlying
),
ws AS (
  SELECT
    underlying,
    realized_pnl,
    total_premium,
    current_shares,
    current_acb_per_share
  FROM `options_wheel.fc018_per_symbol_scorecard`
),
prices AS (
  -- First-trade-date close and most-recent close per underlying.
  SELECT
    s.symbol AS underlying,
    ANY_VALUE(IF(s.date = ft.first_trade_date, s.close, NULL)) AS price_at_start,
    ARRAY_AGG(s.close ORDER BY s.date DESC LIMIT 1)[OFFSET(0)] AS price_now
  FROM `options_wheel.stock_history_from_alpaca` s
  JOIN first_trade ft ON s.symbol = ft.underlying
  WHERE s.date >= ft.first_trade_date
  GROUP BY s.symbol
)
SELECT
  ws.underlying,
  ft.first_trade_date,
  ft.first_strike,
  ws.realized_pnl,
  ws.total_premium,
  ws.current_shares,
  ws.current_acb_per_share,
  p.price_at_start,
  p.price_now,
  -- Hypothetical buy-and-hold: the dollar amount equal to first_strike * 100 * first_qty
  -- (a CSP's collateral) bought at price_at_start and held to today.
  CASE
    WHEN p.price_at_start IS NOT NULL AND p.price_at_start > 0
         AND ft.first_strike IS NOT NULL AND ft.first_qty IS NOT NULL
      THEN (ft.first_strike * 100 * ABS(ft.first_qty)) / p.price_at_start
  END AS hypothetical_shares,
  CASE
    WHEN p.price_at_start IS NOT NULL AND p.price_now IS NOT NULL
         AND p.price_at_start > 0 AND ft.first_strike IS NOT NULL AND ft.first_qty IS NOT NULL
      THEN ((ft.first_strike * 100 * ABS(ft.first_qty)) / p.price_at_start) * (p.price_now - p.price_at_start)
  END AS bh_dollar_pnl,
  -- Wheel "value-add": realized P&L + premium − bh_dollar_pnl
  -- Positive = wheel beat buy-and-hold for this name; negative = lagged.
  CASE
    WHEN p.price_at_start IS NOT NULL AND p.price_now IS NOT NULL
         AND p.price_at_start > 0 AND ft.first_strike IS NOT NULL AND ft.first_qty IS NOT NULL
      THEN (COALESCE(ws.realized_pnl, 0) + COALESCE(ws.total_premium, 0))
           - (((ft.first_strike * 100 * ABS(ft.first_qty)) / p.price_at_start) * (p.price_now - p.price_at_start))
  END AS wheel_minus_bh
FROM ws
LEFT JOIN first_trade ft USING (underlying)
LEFT JOIN prices p USING (underlying);
