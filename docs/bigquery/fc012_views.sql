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


-- ================================================================
-- wheel_cycles_from_activities (Phase 2.6)
-- ================================================================
--
-- Reconstructs wheel cycles from the raw activities stream. A cycle is
-- defined as: short put sold -> stock assigned via OPASN -> short call
-- sold on the assigned stock -> call assigned (called_away) OR call
-- expired worthless OR call bought to close.
--
-- We only emit rows for cycles where the PUT side has been assigned
-- (i.e., stock was acquired). Cycles that expire without assignment do
-- not appear here — those are visible in ``trades_with_outcomes`` as
-- ``outcome='expiration'`` with no stock leg.

CREATE OR REPLACE VIEW `options_wheel.wheel_cycles_from_activities` AS
WITH
-- All put FILLs that were assigned (via matching OPASN on same symbol).
-- Upstream view exposes close_* columns; the close-side for an assignment
-- is the OPASN activity itself.
assigned_puts AS (
  SELECT
    activity_id             AS put_activity_id,
    transaction_time        AS put_transaction_time,
    activity_date           AS put_activity_date,
    underlying,
    strike_price            AS put_strike,
    premium_total           AS put_premium,
    qty                     AS put_qty,
    close_transaction_time  AS put_assignment_time,
    close_activity_id       AS opasn_activity_id
  FROM `options_wheel.trades_with_outcomes`
  WHERE option_type = 'put'
    AND outcome = 'assignment'
),
-- All call FILLs on assigned underlyings, with their outcome.
covered_calls AS (
  SELECT
    activity_id             AS call_activity_id,
    transaction_time        AS call_transaction_time,
    activity_date           AS call_activity_date,
    underlying,
    strike_price            AS call_strike,
    premium_total           AS call_premium,
    qty                     AS call_qty,
    outcome                 AS call_outcome,
    close_transaction_time  AS call_outcome_time,
    outcome_price           AS call_outcome_price
  FROM `options_wheel.trades_with_outcomes`
  WHERE option_type = 'call'
),
-- Pair each assigned put to the NEXT covered call on same underlying.
paired AS (
  SELECT
    p.*,
    c.call_activity_id,
    c.call_transaction_time,
    c.call_activity_date,
    c.call_strike,
    c.call_premium,
    c.call_qty,
    c.call_outcome,
    c.call_outcome_time,
    c.call_outcome_price,
    ROW_NUMBER() OVER (
      PARTITION BY p.put_activity_id
      ORDER BY c.call_transaction_time ASC
    ) AS rn
  FROM assigned_puts p
  LEFT JOIN covered_calls c
    ON c.underlying = p.underlying
    AND c.call_transaction_time > p.put_assignment_time
)
SELECT
  -- Identity
  put_activity_id,
  opasn_activity_id,
  call_activity_id,
  underlying,
  put_transaction_time,
  put_assignment_time,
  call_transaction_time,
  call_outcome_time,
  -- Put side
  DATE(put_transaction_time, 'America/New_York')  AS put_date,
  put_strike,
  put_premium,
  put_qty,
  DATE(put_assignment_time, 'America/New_York')   AS assignment_date,
  -- Call side
  DATE(call_transaction_time, 'America/New_York') AS call_date,
  call_strike,
  call_premium,
  call_qty,
  call_outcome,
  DATE(call_outcome_time, 'America/New_York')     AS call_outcome_date,
  -- Matched quantity: the number of contracts the put/call pair covers.
  -- If a call was sold for fewer contracts than the put provides collateral
  -- for, capital_gain / total_return apply only to the matched subset.
  LEAST(ABS(COALESCE(put_qty, 0)), ABS(COALESCE(call_qty, 0))) AS matched_contracts,
  -- Computed metrics
  COALESCE(put_premium, 0) + COALESCE(call_premium, 0) AS total_premium,
  CASE
    WHEN call_strike IS NOT NULL AND put_strike IS NOT NULL THEN
      (call_strike - put_strike) * 100
        * LEAST(ABS(COALESCE(put_qty, 0)), ABS(COALESCE(call_qty, 0)))
  END AS capital_gain,
  CASE
    WHEN put_strike IS NOT NULL AND put_strike > 0 AND put_qty IS NOT NULL THEN
      SAFE_DIVIDE(
        COALESCE(put_premium, 0) + COALESCE(call_premium, 0)
          + CASE
              WHEN call_strike IS NOT NULL THEN
                (call_strike - put_strike) * 100
                  * LEAST(ABS(put_qty), ABS(COALESCE(call_qty, 0)))
              ELSE 0
            END,
        put_strike * 100 * ABS(put_qty)
      )
  END AS total_return,
  DATE_DIFF(
    DATE(COALESCE(call_outcome_time, call_transaction_time, put_assignment_time),
         'America/New_York'),
    DATE(put_assignment_time, 'America/New_York'),
    DAY
  ) AS duration_days,
  CAST(ABS(COALESCE(put_qty, 0)) * 100 AS INT64) AS shares
FROM paired
WHERE rn = 1 OR rn IS NULL;
