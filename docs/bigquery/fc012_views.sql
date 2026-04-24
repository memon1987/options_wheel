-- FC-012 Phase 2.1: Projection view over trades_from_activities
--
-- Raw table: options_wheel.trades_from_activities (append-only, one row
-- per Alpaca activity).
-- View:      options_wheel.trades_with_outcomes (one row per opening option
--            FILL, with its eventual outcome derived from later activities).
--
-- See docs/plans/fc-012.md §2.1 for context.
--
-- Deploy:
--   bq query --use_legacy_sql=false < docs/bigquery/fc012_views.sql
--
-- Outcome semantics:
--   'open'         -> no matching close-side activity yet
--   'assignment'   -> short put assigned (stock acquired)
--   'called_away'  -> short call assigned (stock sold at strike)
--   'expiration'   -> option expired worthless
--   'early_close'  -> short position bought back before expiration

CREATE OR REPLACE VIEW `options_wheel.trades_with_outcomes` AS
WITH opens AS (
  SELECT *
  FROM `options_wheel.trades_from_activities`
  WHERE activity_type = 'FILL'
    AND option_type IN ('put', 'call')
    -- Opening short options. Alpaca's `side` uses 'sell_short' for options
    -- sold-to-open; 'sell' is also accepted as a safety net.
    AND side IN ('sell_short', 'sell')
),
closes AS (
  SELECT
    activity_id  AS close_activity_id,
    activity_type AS close_activity_type,
    symbol,
    transaction_time AS close_transaction_time,
    price AS close_price,
    qty AS close_qty
  FROM `options_wheel.trades_from_activities`
  WHERE
    -- buy_to_close / buy FILL events that close a short option
    (activity_type = 'FILL' AND option_type IN ('put', 'call')
        AND side IN ('buy_to_close', 'buy'))
    OR activity_type IN ('OPASN', 'OPEXP')
),
-- Pair each open to the earliest later close event on the same OCC symbol.
paired AS (
  SELECT
    o.* EXCEPT (ingested_at),
    c.close_activity_id,
    c.close_activity_type,
    c.close_transaction_time,
    c.close_price,
    c.close_qty,
    ROW_NUMBER() OVER (
      PARTITION BY o.activity_id
      ORDER BY c.close_transaction_time ASC
    ) AS rn
  FROM opens o
  LEFT JOIN closes c
    ON c.symbol = o.symbol
    AND c.close_transaction_time > o.transaction_time
)
SELECT
  activity_id,
  activity_type,
  transaction_time,
  activity_date,
  order_id,
  symbol,
  underlying,
  side,
  qty,
  price,
  option_type,
  strike_price,
  expiration,
  dte_at_event,
  premium_total,
  close_activity_id,
  close_activity_type,
  close_transaction_time,
  close_price,
  close_qty,
  CASE
    WHEN close_activity_id IS NULL THEN 'open'
    WHEN close_activity_type = 'OPASN' AND option_type = 'put' THEN 'assignment'
    WHEN close_activity_type = 'OPASN' AND option_type = 'call' THEN 'called_away'
    WHEN close_activity_type = 'OPEXP' THEN 'expiration'
    WHEN close_activity_type = 'FILL' THEN 'early_close'
    ELSE 'unknown'
  END AS outcome,
  -- Realized P&L per outcome type. Conventions:
  --   assignment/called_away/expiration -> keep full premium
  --   early_close                       -> premium collected minus cost to close
  CASE
    WHEN close_activity_id IS NULL THEN NULL
    WHEN close_activity_type IN ('OPASN', 'OPEXP') THEN premium_total
    WHEN close_activity_type = 'FILL' THEN
      premium_total - (close_price * ABS(close_qty) * 100)
    ELSE NULL
  END AS realized_pnl,
  -- Outcome price: close fill price for early_close, strike for assignments.
  CASE
    WHEN close_activity_type = 'FILL' THEN close_price
    WHEN close_activity_type IN ('OPASN', 'OPEXP') THEN strike_price
    ELSE NULL
  END AS outcome_price
FROM paired
WHERE rn = 1 OR rn IS NULL;
