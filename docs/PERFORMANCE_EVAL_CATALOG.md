# Performance Evaluation Catalog

Recurring analysis checks to run against production trading data. Each eval defines a hypothesis, the data required, the query/method to validate, and when it becomes actionable. These are designed to eventually be automated as programmatic evals that can autonomously tune strategy parameters.

---

## Status Key
- **BLOCKED**: Missing required data — noted what's needed
- **READY**: Data available, can run now
- **ACTIVE**: Running on schedule, informing decisions
- **AUTOMATED**: Programmatic eval adjusts parameters autonomously

---

## EVAL-001: Early Close Limit Order Fill Rate

**Hypothesis:** 95% of ask is aggressive enough to fill reliably without sacrificing profits to unfilled orders.

**Data required:** `bid`, `ask`, `limit_price`, `fill_price` on `early_close_executed` events (available after Tier 1 deploy)

**Query:**
```sql
SELECT
  symbol,
  bid, ask, limit_price, fill_price,
  CASE WHEN fill_price IS NOT NULL THEN 'filled' ELSE 'unfilled' END as outcome,
  (ask - fill_price) as savings_vs_ask,
  (fill_price - bid) / NULLIF(ask - bid, 0) as fill_position_in_spread
FROM trades_executed
WHERE event_type = 'early_close_executed' AND limit_price IS NOT NULL
```

**What to look for:**
- Fill rate < 90% → limit too aggressive, increase toward ask
- Fill rate > 99% → limit too conservative, tighten toward mid
- Average `savings_vs_ask` → quantifies actual dollar savings vs market orders
- `fill_position_in_spread` distribution → understand where in the spread we're filling

**Action threshold:** If fill rate < 85% over 2 weeks, change multiplier from 0.95 to 0.97. If > 98%, tighten to 0.92.

**Status:** BLOCKED — needs 2+ weeks of Tier 1 data

**Config parameter:** Close limit multiplier (currently hardcoded 0.95 in cloud_run_server.py)

---

## EVAL-002: Profit Target vs Let-Expire Analysis

**Hypothesis:** Some positions that hit the profit target would have been more profitable if left to expire worthless (full premium capture).

**Data required:** `order_filled`/`order_expired` events from `poll_order_statuses()`, plus historical position outcomes

**Query:**
```sql
-- Compare: premium collected on close vs remaining time value
SELECT
  ec.symbol,
  ec.profit_pct as close_profit_pct,
  ec.fill_price as buyback_cost,
  ps.premium as original_premium,
  ps.dte as original_dte,
  ec.dte as close_dte,
  -- If option expired worthless, remaining_value = buyback_cost = lost profit
  ec.fill_price * ec.contracts * 100 as profit_left_on_table
FROM early_closes ec
JOIN put_sales ps ON ec.underlying = ps.underlying
  AND ps.date_et < ec.date_et
  AND ps.date_et > DATE_SUB(ec.date_et, INTERVAL 14 DAY)
```

**What to look for:**
- Average `profit_left_on_table` per close
- Percentage of closes where the option expired worthless within 2 days (we closed too early)
- Correlation between DTE at close and profit left on table
- Whether the DTE-band profit targets are calibrated correctly

**Action threshold:** If > 40% of closed positions would have expired worthless within 48 hours, widen profit targets by 10% at corresponding DTE bands.

**Status:** BLOCKED — needs fill price data (Tier 1) + order outcome data (Tier 2.2)

**Config parameter:** `risk.profit_taking.dte_bands[].profit_target`

---

## EVAL-003: Assignment Rate by Symbol

**Hypothesis:** Some symbols have systematically higher assignment rates, making them less profitable despite higher premiums.

**Data required:** Assignment detection events from `reconcile_positions()` (Tier 2.3)

**Query:**
```sql
SELECT
  underlying,
  COUNT(CASE WHEN event_type = 'put_sale_executed' THEN 1 END) as puts_sold,
  COUNT(CASE WHEN event_type = 'put_assignment_detected' THEN 1 END) as assignments,
  SAFE_DIVIDE(
    COUNT(CASE WHEN event_type = 'put_assignment_detected' THEN 1 END),
    COUNT(CASE WHEN event_type = 'put_sale_executed' THEN 1 END)
  ) as assignment_rate,
  AVG(CASE WHEN event_type = 'put_sale_executed' THEN premium END) as avg_premium
FROM trades
GROUP BY underlying
ORDER BY assignment_rate DESC
```

**What to look for:**
- Symbols with > 30% assignment rate — premium may not compensate for stock holding risk
- Correlation between premium size and assignment rate (higher premium = more ITM risk)
- Net P&L by symbol: premium collected - (assignment losses + buyback costs)

**Action threshold:** If a symbol's net P&L (including assignment losses) is negative over 3 months, remove from the universe.

**Status:** BLOCKED — needs assignment detection (Tier 2.3)

**Config parameter:** `stocks.symbols` list

---

## EVAL-004: DTE Optimization

**Hypothesis:** The current 7 DTE target is suboptimal. Shorter DTE (2-3) has higher per-trade ROI but potentially higher assignment risk.

**Data required:** Full trade lifecycle: open premium, close/expire price, assignment outcomes, by DTE

**Query:**
```sql
SELECT
  CAST(dte AS INT64) as entry_dte,
  COUNT(*) as trades,
  AVG(premium) as avg_premium,
  AVG(premium * 100 / NULLIF(collateral_required, 0)) * 100 as avg_roi_pct,
  -- Net ROI including buyback costs and assignment losses
  AVG(CASE
    WHEN outcome = 'expired' THEN premium  -- full profit
    WHEN outcome = 'closed' THEN premium - buyback_price  -- partial profit
    WHEN outcome = 'assigned' THEN premium - assignment_loss  -- may be negative
  END) as avg_net_premium
FROM trade_lifecycle  -- requires joined view
GROUP BY entry_dte
ORDER BY avg_net_premium DESC
```

**What to look for:**
- Which DTE has the best **net** ROI (not just gross premium)
- Whether 2-3 DTE's higher gross ROI survives after assignment losses
- Capital turnover rate: shorter DTE = more trades per month, compounding effect

**Action threshold:** If 3 DTE net ROI exceeds 7 DTE net ROI by > 15% over 2 months of data, shift target DTE.

**Status:** BLOCKED — needs full trade lifecycle data

**Config parameter:** `strategy.put_target_dte`

---

## EVAL-005: Day-of-Week Premium Patterns

**Hypothesis:** Thursday and Monday have sustainably higher premiums than other days.

**Data required:** Existing put_sale_executed data (READY)

**Query:**
```sql
SELECT
  FORMAT_DATE('%A', date_et) as day_of_week,
  EXTRACT(MONTH FROM date_et) as month,
  AVG(premium) as avg_premium,
  STDDEV(premium) as premium_stddev,
  COUNT(*) as trades
FROM trades_executed
WHERE event_type = 'put_sale_executed'
GROUP BY day_of_week, month
ORDER BY month, day_of_week
```

**What to look for:**
- Is the Thu/Mon pattern consistent month-over-month or driven by a few outlier weeks?
- Statistical significance: is the difference > 1 standard deviation?
- Seasonal effects: does the pattern hold in both high-vol (Nov) and low-vol (Dec) months?

**Action threshold:** If Thu premium > Wed premium by > 1 stddev for 3+ consecutive months, weight Thursday execution higher.

**Status:** READY — existing data sufficient for initial analysis

**Config parameter:** Execution schedule weighting (not yet parameterized)

---

## EVAL-006: Minimum Premium Threshold Impact

**Hypothesis:** Raising min_put_premium from $0.50 to $1.00 eliminates low-yield trades without reducing total premium.

**Data required:** Existing data (READY) + forward data after change

**Query:**
```sql
-- Counterfactual: what would we have collected without sub-$1 trades?
SELECT
  'with_sub_1' as scenario,
  COUNT(*) as trades,
  SUM(premium * contracts * 100) as total_premium,
  AVG(premium * 100 / NULLIF(collateral_required, 0)) * 100 as avg_roi
FROM trades_executed WHERE event_type = 'put_sale_executed'

UNION ALL

SELECT
  'without_sub_1' as scenario,
  COUNT(*) as trades,
  SUM(premium * contracts * 100) as total_premium,
  AVG(premium * 100 / NULLIF(collateral_required, 0)) * 100 as avg_roi
FROM trades_executed WHERE event_type = 'put_sale_executed' AND premium >= 1.00
```

**What to look for:**
- Premium lost by eliminating sub-$1 trades
- Collateral freed up (could be deployed to higher-ROI opportunities)
- After implementing: did trade quality improve? Did total premium stay flat or increase?

**Action threshold:** If eliminating sub-$1 trades loses < 10% of total premium while freeing > 20% of collateral, make the change permanent.

**Status:** READY — can run counterfactual now, forward test after config change

**Config parameter:** `strategy.min_put_premium`

---

## EVAL-007: Unused Symbol Investigation

**Hypothesis:** F, PFE, KMI, VZ are configured but never trade due to filtering.

**Data required:** Filtering stage logs (READY)

**Query:**
```sql
SELECT
  jsonPayload.symbol,
  jsonPayload.event_type,
  COUNT(*) as count
FROM raw_logs
WHERE jsonPayload.event_type LIKE 'stock_%' OR jsonPayload.event_type LIKE 'stage_%'
  AND jsonPayload.symbol IN ('F', 'PFE', 'KMI', 'VZ')
GROUP BY jsonPayload.symbol, jsonPayload.event_type
ORDER BY jsonPayload.symbol, count DESC
```

**What to look for:**
- Which filtering stage rejects these symbols (gap risk? price? volume? premium too low?)
- Whether relaxing the specific filter would allow them through safely
- If premium_too_low is the reason, these symbols need different DTE targets (longer DTE for lower-priced stocks to accumulate premium)

**Status:** READY — filtering logs exist

**Config parameter:** Per-symbol DTE targets (not yet supported), filter thresholds

---

## EVAL-008: Slippage Analysis (Open vs Close)

**Hypothesis:** We're losing more to slippage on opens (sell limit orders) than closes.

**Data required:** `limit_price` and `fill_price` on both sell and buy orders

**Query:**
```sql
SELECT
  side,
  COUNT(*) as orders,
  AVG(ABS(fill_price - limit_price)) as avg_slippage,
  AVG(ABS(fill_price - limit_price) / NULLIF(limit_price, 0)) * 100 as avg_slippage_pct,
  SUM(ABS(fill_price - limit_price) * contracts * 100) as total_slippage_dollars
FROM trade_lifecycle
WHERE fill_price IS NOT NULL AND limit_price IS NOT NULL
GROUP BY side
```

**What to look for:**
- Sell orders (opening): limit_price should be close to fill_price (selling at our price)
- Buy orders (closing): fill_price should be at or below limit_price
- Total slippage in dollars — is it material compared to premium collected?

**Status:** BLOCKED — needs fill_price data (available after Tier 1 deploy + poll_order_statuses)

**Config parameter:** Sell limit offset (currently 95% of mid in put_seller), close limit multiplier

---

## EVAL-009: Circuit Breaker Impact

**Hypothesis:** The circuit breaker prevents cascade failures without causing missed trades.

**Data required:** Circuit breaker events from logs

**Query:**
```sql
SELECT
  DATE(timestamp, 'America/New_York') as date,
  COUNTIF(event_type = 'circuit_breaker_opened') as opens,
  COUNTIF(event_type = 'circuit_breaker_half_open') as half_opens,
  COUNTIF(event_type = 'circuit_breaker_closed') as closes,
  COUNTIF(event_type = 'circuit_breaker_call_blocked') as blocked_calls
FROM raw_logs
WHERE event_type LIKE 'circuit_breaker_%'
GROUP BY date
ORDER BY date DESC
```

**What to look for:**
- Frequency of breaker trips
- Duration of open state (should be ~60s)
- Number of blocked calls during open state — these are missed opportunities
- Correlation with Alpaca API incidents

**Action threshold:** If breaker trips > 3x/week during market hours, increase failure_threshold from 5 to 8. If blocked_calls cause missed profitable trades, reduce reset_timeout from 60s to 30s.

**Status:** BLOCKED — needs production data post-refactor

**Config parameter:** `CircuitBreaker.failure_threshold`, `CircuitBreaker.reset_timeout`

---

## EVAL-010: Symbol Universe Optimization

**Hypothesis:** The current 14-symbol universe is inefficient — 8 symbols never trade, wasting ~6,000 API calls per month and slowing scans.

**Data (collected Apr 2026):**

| Symbol | Status | Reason |
|---|---|---|
| AMD | ACTIVE (51 trades) | Top earner, but gap-filtered 47% of the time |
| NVDA | ACTIVE (75 trades) | Most active |
| AMZN | ACTIVE (30 trades) | Best ROI (1.50%) — stopped trading Feb 5, investigate |
| UNH | ACTIVE (45 trades) | Steady performer |
| GOOGL | ACTIVE (27 trades) | Solid |
| IWM | ACTIVE (32 trades) | Worst ROI (0.58%) — consider removing |
| AAPL | NEVER TRADED | Passes filters but `no_puts_met_criteria` 738 times — premiums too thin at our delta range |
| MSFT | NEVER TRADED | Price $400-490, above $400 max_stock_price |
| QQQ | NEVER TRADED | Price $480-520, above $400 max |
| SPY | NEVER TRADED | Price $550-600, above $400 max |
| F | NEVER TRADED | At $6, puts pay $0.05-0.15, below $0.50 min premium |
| PFE | NEVER TRADED | At $25, premiums $0.10-0.30, below min |
| KMI | NEVER TRADED | At $28, insufficient premium |
| VZ | NEVER TRADED | At $43, premiums $0.20-0.40, borderline |

**Recommended changes (pending validation):**
- Remove: AAPL, MSFT, QQQ, SPY, F, PFE, KMI, VZ (all dead weight)
- Keep: AMD, NVDA, AMZN, UNH, GOOGL
- Evaluate IWM: lowest ROI but provides ETF diversification
- Investigate: Why AMZN stopped trading after Feb 5 (gap risk? position limit?)
- Consider adding: META, TSLA, COIN, PLTR (all in $100-350 range with high IV)
- If adding MSFT: requires raising max_stock_price from $400 to $500+ ($48k collateral)

**Investigate AMD gap filtering:** AMD is gap-filtered 47% of the time (262 of 553 scans). The gap risk thresholds may be too conservative for a stock that's your top premium generator. Compare AMD's actual overnight gaps vs the filter threshold.

**Action threshold:** Remove symbols with 0 trades over 3+ months. Add symbols only after backtesting confirms they'd pass all filters and generate premium above minimum.

**Status:** READY — data collected, changes cataloged for future session

**Config parameters:** `stocks.symbols`, `strategy.max_stock_price`, `strategy.min_put_premium`, `risk.gap_risk_controls.*`

---

## Future Automation Architecture

Once 3+ evals have sufficient data and stable thresholds, build:

1. **Scheduled eval runner** — Cloud Scheduler job that runs all ACTIVE evals weekly
2. **Results storage** — BigQuery table `options_wheel.eval_results` with eval_id, timestamp, metrics, recommendation
3. **Threshold checker** — Compare eval results against action thresholds
4. **Config proposer** — Generate proposed config changes with evidence
5. **Human-in-the-loop gate** — Proposed changes require approval before applying (initially)
6. **Autonomous mode** — After 3 months of validated proposals, approved evals can auto-apply within safe bounds (e.g., premium threshold can move 10% per week max)

### Safety constraints for autonomous tuning:
- No parameter can change by more than 10% per adjustment
- No more than 1 parameter change per week
- Automatic rollback if regression monitor detects degradation within 48 hours
- Hard limits on all parameters (e.g., min_premium can never go below $0.25 or above $5.00)
- Human notification on every change, even if auto-applied
