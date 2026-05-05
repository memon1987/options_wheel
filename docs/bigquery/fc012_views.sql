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

-- A wheel cycle = put assigned -> stock held -> covered call(s) sold -> called
-- away (or still in flight). During the held period the same shares are often
-- covered by MULTIPLE rolled calls; the cycle aggregation must sum premium
-- and net P&L across all of them, not just the first.
CREATE OR REPLACE VIEW `options_wheel.wheel_cycles_from_activities` AS
WITH
-- Each put assignment starts a cycle.
assigned_puts AS (
  SELECT
    activity_id            AS put_activity_id,
    transaction_time       AS put_transaction_time,
    underlying,
    strike_price           AS put_strike,
    premium_total          AS put_premium,
    qty                    AS put_qty,
    close_transaction_time AS put_assignment_time,
    close_activity_id      AS opasn_activity_id
  FROM `options_wheel.trades_with_outcomes`
  WHERE option_type = 'put' AND outcome = 'assignment'
),
-- A called_away call ends a cycle. Pair each assigned put to the EARLIEST
-- subsequent called_away on the same underlying. If none exists, the cycle
-- is still in flight (call_outcome_time IS NULL).
ending_calls AS (
  SELECT
    activity_id            AS call_activity_id,
    transaction_time       AS call_transaction_time,
    close_transaction_time AS call_outcome_time,
    underlying,
    strike_price           AS call_strike,
    premium_total          AS call_terminating_premium,
    qty                    AS call_qty
  FROM `options_wheel.trades_with_outcomes`
  WHERE option_type = 'call' AND outcome = 'called_away'
),
paired AS (
  SELECT
    p.*,
    e.call_activity_id,
    e.call_transaction_time,
    e.call_outcome_time,
    e.call_strike,
    e.call_terminating_premium,
    e.call_qty,
    ROW_NUMBER() OVER (
      PARTITION BY p.put_activity_id
      ORDER BY e.call_outcome_time ASC
    ) AS rn
  FROM assigned_puts p
  LEFT JOIN ending_calls e
    ON e.underlying = p.underlying
    AND e.call_outcome_time > p.put_assignment_time
),
cycles AS (
  SELECT * FROM paired WHERE rn = 1 OR rn IS NULL
),
-- Aggregate every option event between the put assignment and the cycle's
-- end (or the present, for in-flight cycles). This is the cycle's full
-- realized contribution: includes the put's premium kept on assignment,
-- every covered call sold during the held period (whether early-closed and
-- rolled or held to assignment/expiration), and the buyback costs of those
-- early-closed calls.
cycle_aggregates AS (
  -- Aggregate every CALL event between assignment and the cycle's end (or now,
  -- for in-flight cycles). The put's own $premium is counted via put_premium
  -- below — including it here would double-count, since the put's
  -- transaction_time is before put_assignment_time anyway.
  SELECT
    c.put_activity_id,
    SUM(COALESCE(t.realized_pnl, 0))   AS cycle_call_net_realized,
    SUM(COALESCE(t.premium_total, 0))  AS cycle_call_gross_premium,
    COUNTIF(t.outcome != 'open')       AS calls_in_cycle
  FROM cycles c
  JOIN `options_wheel.trades_with_outcomes` t
    ON t.underlying = c.underlying
    AND t.option_type = 'call'
    AND t.outcome != 'open'
    AND t.transaction_time > c.put_assignment_time
    AND (c.call_outcome_time IS NULL OR t.transaction_time <= c.call_outcome_time)
  GROUP BY c.put_activity_id
),
-- FC-019: actual share-side cash flow from OPTRD activities within the cycle
-- window. Replaces the (call_strike − put_strike) approximation that
-- breaks on overlapping share lots. Each OPTRD records the real cash that
-- moved when shares were assigned (negative) or called away (positive).
cycle_share_cash AS (
  SELECT
    c.put_activity_id,
    SUM(COALESCE(o.net_amount, 0)) AS cycle_optrd_net,
    COUNT(*) AS optrd_event_count
  FROM cycles c
  JOIN `options_wheel.trades_from_activities` o
    ON o.symbol = c.underlying
    AND o.activity_type = 'OPTRD'
    AND o.transaction_time >= c.put_assignment_time
    AND (c.call_outcome_time IS NULL OR o.transaction_time <= c.call_outcome_time)
  GROUP BY c.put_activity_id
)
SELECT
  c.put_activity_id,
  c.opasn_activity_id,
  c.call_activity_id,
  c.underlying,
  c.put_transaction_time,
  c.put_assignment_time,
  c.call_transaction_time,
  c.call_outcome_time,
  -- Put side
  DATE(c.put_transaction_time,  'America/New_York') AS put_date,
  c.put_strike,
  c.put_premium,
  c.put_qty,
  DATE(c.put_assignment_time,   'America/New_York') AS assignment_date,
  -- Call side (terminating call only — the called_away one).
  DATE(c.call_transaction_time, 'America/New_York') AS call_date,
  c.call_strike,
  c.call_terminating_premium AS call_premium,
  c.call_qty,
  CASE WHEN c.call_outcome_time IS NULL THEN 'open' ELSE 'called_away' END AS call_outcome,
  DATE(c.call_outcome_time,     'America/New_York') AS call_outcome_date,
  LEAST(ABS(COALESCE(c.put_qty, 0)), ABS(COALESCE(c.call_qty, 0))) AS matched_contracts,
  -- Aggregated cycle metrics (the fix).
  ca.calls_in_cycle,
  ca.cycle_call_gross_premium,
  ca.cycle_call_net_realized,
  -- total_premium = the cycle's net realized P&L from option events.
  -- (Stock leg is in capital_gain, computed from OPTRD net_amount below.)
  COALESCE(c.put_premium, 0) + COALESCE(ca.cycle_call_net_realized, 0) AS total_premium,
  -- FC-019: capital_gain now uses real OPTRD cash flow within the cycle
  -- window, not the (call_strike − put_strike) × 100 approximation. This
  -- handles overlapping share lots correctly. Falls back to the old
  -- formula if no OPTRD data is ingested yet (FC-019 backfill prerequisite).
  COALESCE(
    sc.cycle_optrd_net,
    CASE
      WHEN c.call_strike IS NOT NULL AND c.put_strike IS NOT NULL THEN
        (c.call_strike - c.put_strike) * 100
          * LEAST(ABS(COALESCE(c.put_qty, 0)), ABS(COALESCE(c.call_qty, 0)))
    END
  ) AS capital_gain,
  sc.optrd_event_count,
  CASE
    WHEN c.put_strike IS NOT NULL AND c.put_strike > 0 AND c.put_qty IS NOT NULL THEN
      SAFE_DIVIDE(
        COALESCE(c.put_premium, 0)
          + COALESCE(ca.cycle_call_net_realized, 0)
          + COALESCE(
              sc.cycle_optrd_net,
              CASE
                WHEN c.call_strike IS NOT NULL THEN
                  (c.call_strike - c.put_strike) * 100
                    * LEAST(ABS(c.put_qty), ABS(COALESCE(c.call_qty, 0)))
                ELSE 0
              END),
        c.put_strike * 100 * ABS(c.put_qty)
      )
  END AS total_return,
  DATE_DIFF(
    DATE(COALESCE(c.call_outcome_time, CURRENT_TIMESTAMP()), 'America/New_York'),
    DATE(c.put_assignment_time, 'America/New_York'),
    DAY
  ) AS duration_days,
  CAST(ABS(COALESCE(c.put_qty, 0)) * 100 AS INT64) AS shares
FROM cycles c
LEFT JOIN cycle_aggregates ca USING (put_activity_id)
LEFT JOIN cycle_share_cash sc USING (put_activity_id);
