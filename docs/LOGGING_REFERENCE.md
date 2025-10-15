# Options Wheel Strategy - Comprehensive Logging Reference

**Last Updated:** October 15, 2025

This document provides complete reference for all logging performed throughout the options wheel trading system, including event categories, log fields, and query examples for analysis.

---

## Table of Contents

1. [Logging Framework](#logging-framework)
2. [Event Categories](#event-categories)
3. [Standardized Logging Functions](#standardized-logging-functions)
4. [Component Logging Reference](#component-logging-reference)
5. [Filtering Pipeline (Stage 1-9)](#filtering-pipeline-stage-1-9)
6. [BigQuery Integration](#bigquery-integration)
7. [Query Examples](#query-examples)
8. [Monitoring & Alerts](#monitoring--alerts)

---

## Logging Framework

### Technology Stack
- **Framework:** [structlog](https://www.structlog.org/) - Structured logging for Python
- **Format:** JSON (for machine parsing and BigQuery compatibility)
- **Destination:** Cloud Logging → BigQuery export
- **Time Format:** ISO 8601 with millisecond precision

### Configuration
Location: `src/utils/logger.py`

```python
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)
```

### Critical Requirement
⚠️ **ALL logs exported to BigQuery MUST include `event_category` field!**

Cloud Logging Sink Filter:
```
resource.labels.service_name="options-wheel-strategy"
jsonPayload.event_category=*
```

Logs without `event_category` will NOT be exported to BigQuery.

---

## Event Categories

All events are categorized for easy querying and analysis:

| Category | Purpose | Example Events |
|----------|---------|----------------|
| `trade` | Trading activity, orders | `put_sale_executed`, `call_sale_executed` |
| `risk` | Gap detection, filtering, blocking | `stock_filtered_by_gap_risk`, `execution_gap_exceeded` |
| `system` | Strategy cycles, service events | `market_scan_completed`, `strategy_execution_completed` |
| `performance` | Timing, metrics | `market_scan_duration`, `execution_latency` |
| `error` | Errors, failures | `scan_failure`, `trade_execution_failed` |
| `position` | Wheel state transitions | `position_opened`, `position_assigned` |
| `backtest` | Backtesting events | `backtest_started`, `backtest_completed` |
| `filtering` | Filter stage logging (STAGE 1-9) | `stage_1_complete`, `stage_7_complete_found` |

---

## Standardized Logging Functions

Location: `src/utils/logging_events.py`

### 1. Trade Events

```python
log_trade_event(
    logger,
    event_type="put_sale_executed",
    symbol="AMD251010P00192500",
    strategy="sell_put",
    success=True,
    underlying="AMD",
    strike_price=192.50,
    premium=2.17,
    contracts=1,
    order_id="abc123"
)
```

**Fields:**
- `event_category`: "trade"
- `event_type`: Specific trade event
- `symbol`: Option symbol
- `strategy`: "sell_put" or "sell_call"
- `success`: Boolean
- `underlying`: Stock symbol
- `strike_price`: Strike price
- `premium`: Premium per contract
- `contracts`: Number of contracts
- `order_id`: Alpaca order ID
- `timestamp_ms`: Unix milliseconds
- `timestamp_iso`: ISO 8601 timestamp

### 2. Risk Events

```python
log_risk_event(
    logger,
    event_type="gap_detected",
    symbol="AMD",
    risk_type="gap_risk",
    action_taken="trade_blocked",
    gap_percent=2.5,
    threshold=1.5,
    reason="Overnight gap exceeded execution threshold"
)
```

**Fields:**
- `event_category`: "risk"
- `event_type`: Risk event type
- `symbol`: Stock symbol
- `risk_type`: "gap_risk", "position_risk", "buying_power"
- `action_taken`: "trade_blocked", "position_closed", "alert_sent"
- Additional context fields (gap_percent, threshold, etc.)

### 3. Performance Metrics

```python
log_performance_metric(
    logger,
    metric_name="market_scan_duration",
    metric_value=4.23,
    metric_unit="seconds",
    symbols_scanned=10,
    opportunities_found=8
)
```

**Fields:**
- `event_category`: "performance"
- `event_type`: "metric"
- `metric_name`: Name of metric
- `metric_value`: Numeric value
- `metric_unit`: "seconds", "milliseconds", "count"

### 4. Error Events

```python
log_error_event(
    logger,
    error_type="insufficient_funds",
    error_message="Not enough buying power for trade",
    component="put_seller",
    recoverable=True,
    required=15500.00,
    available=10000.00,
    symbol="AMD"
)
```

**Fields:**
- `event_category`: "error"
- `error_type`: Type of error
- `error_message`: Human-readable message
- `component`: Component where error occurred
- `recoverable`: Boolean

### 5. System Events

```python
log_system_event(
    logger,
    event_type="strategy_cycle_completed",
    status="completed",
    duration_seconds=12.5,
    actions_taken=3,
    new_positions=2,
    closed_positions=1
)
```

**Fields:**
- `event_category`: "system"
- `event_type`: System event type
- `status`: "starting", "running", "completed", "failed"

### 6. Filtering Events

```python
log_filtering_event(
    logger,
    stage_number=1,
    event_type="complete",
    status="complete",
    total_analyzed=14,
    passed=12,
    rejected=2,
    passed_symbols=["AAPL", "MSFT"],
    rejected_symbols=["XYZ"]
)
```

**Fields:**
- `event_category`: "filtering"
- `event_type`: f"stage_{stage_number}_{event_type}"
- `stage_number`: 1-9
- `status`: "complete", "passed", "blocked"

---

## Component Logging Reference

### Cloud Run Server (`deploy/cloud_run_server.py`)

#### Market Scan Endpoint (`/scan`)

**Scan Trigger:**
```python
log_system_event(
    logger,
    event_type="market_scan_triggered",
    status="starting"
)
```

**Scan Completion:**
```python
log_system_event(
    logger,
    event_type="market_scan_completed",
    status="completed",
    duration_seconds=16.2,
    put_opportunities=10,
    call_opportunities=0,
    total_opportunities=10,
    stored_for_execution=True
)
```

**Performance Metric:**
```python
log_performance_metric(
    logger,
    metric_name="market_scan_duration",
    metric_value=16.2,
    metric_unit="seconds",
    opportunities_found=10
)
```

**Scan Failure:**
```python
log_error_event(
    logger,
    error_type="market_scan_exception",
    error_message=str(e),
    component="cloud_run_server",
    recoverable=True
)
```

#### Strategy Execution Endpoint (`/run`)

**Execution Trigger:**
```python
log_system_event(
    logger,
    event_type="strategy_execution_triggered",
    status="starting"
)
```

**No Opportunities:**
```python
log_system_event(
    logger,
    event_type="strategy_execution_completed",
    status="no_opportunities",
    duration_seconds=0.5,
    opportunities_found=0
)
```

**Buying Power Logging:**
```python
logger.info("Starting execution with buying power",
    initial_buying_power=50000.00,
    buying_power=50000.00,
    options_buying_power=50000.00,
    cash=45000.00,
    portfolio_value=52000.00,
    equity=52000.00
)
```

**Batch Selection:**
```python
logger.info("Selected opportunity for batch execution",
    symbol="AMD",
    collateral=19250.00,
    premium=217.00,
    roi="0.0113",
    remaining_bp=30750.00
)
```

**Duplicate Underlying Skip:**
```python
logger.info("Skipping duplicate underlying in batch selection",
    symbol="AMD",
    collateral=19250.00,
    premium=217.00,
    roi="0.0113",
    reason="already_selected_for_execution"
)
```

**Trade Executed:**
```python
log_system_event(
    logger,
    event_type="trade_executed",
    status="success",
    symbol="AMD",
    option_symbol="AMD251010P00192500",
    contracts=1,
    premium=2.17,
    strike_price=192.50,
    order_id="abc-123-def"
)
```

**Trade Failed:**
```python
log_error_event(
    logger,
    error_type="trade_execution_failed",
    error_message="Order rejected by broker",
    component="execution_engine",
    recoverable=True,
    symbol="AMD",
    option_symbol="AMD251010P00192500"
)
```

**Execution Completion:**
```python
log_system_event(
    logger,
    event_type="strategy_execution_completed",
    status="completed",
    duration_seconds=8.3,
    opportunities_evaluated=10,
    trades_executed=3,
    trades_failed=7
)
```

---

### Market Data Manager (`src/api/market_data.py`)

#### Stage 1: Price/Volume Filtering

**Stock Passed:**
```python
logger.info("Stock passed price/volume filter",
    symbol="AAPL",
    price=237.50,
    avg_volume=45000000,
    volatility=0.285
)
```

**Stock Rejected:**
```python
logger.info("Stock rejected by price/volume filter",
    symbol="SPY",
    reasons=["price $575.23 outside $10.00-$300.00"],
    price=575.23,
    avg_volume=60000000
)
```

**Stage Complete:**
```python
logger.info("STAGE 1 COMPLETE: Price/Volume filtering",
    event_category="filtering",
    event_type="stage_1_complete",
    total_analyzed=14,
    passed=11,
    rejected=3,
    passed_symbols=["AAPL", "AMD", "NVDA", ...],
    rejected_symbols=["SPY", "QQQ", "MSFT"]
)
```

#### Stage 7: Put Options Chain Criteria

**Scan Start:**
```python
logger.info("STAGE 7: Options chain criteria - starting put scan",
    event_category="filtering",
    event_type="stage_7_start",
    symbol="AMD",
    total_puts_in_chain=82,
    target_dte=7,
    min_premium=0.50,
    delta_range=[0.10, 0.25]
)
```

**Puts Found:**
```python
logger.info("STAGE 7 COMPLETE: Options chain criteria - puts found",
    event_category="filtering",
    event_type="stage_7_complete_found",
    symbol="AMD",
    total_puts=82,
    rejected=75,
    suitable_count=7,
    best_put_strike=192.50,
    best_put_premium=2.17,
    best_put_dte=3,
    best_put_delta=0.15,
    # Rejection breakdown
    rejected_dte_too_high=20,
    rejected_premium_too_low=35,
    rejected_delta_out_of_range=15,
    rejected_no_liquidity=5
)
```

**No Suitable Puts:**
```python
logger.info("STAGE 7 COMPLETE: Options chain criteria - NO suitable puts",
    event_category="filtering",
    event_type="stage_7_complete_not_found",
    symbol="F",
    total_puts=45,
    rejected=45,
    reason="no_puts_met_criteria",
    # Rejection breakdown
    rejected_dte_too_high=10,
    rejected_premium_too_low=30,
    rejected_delta_out_of_range=3,
    rejected_no_liquidity=2,
    # Stats on rejected puts
    rejected_avg_premium=0.32,
    rejected_avg_delta=0.0850,
    rejected_max_premium=0.45,
    rejected_dte_range="1-14"
)
```

#### Stage 8: Call Options Chain Criteria

**Scan Start:**
```python
logger.info("STAGE 8: Call options criteria - starting call scan",
    event_category="filtering",
    event_type="stage_8_start",
    symbol="AMD",
    total_calls_in_chain=68,
    target_dte=7,
    min_premium=0.50,
    delta_range=[0.20, 0.40],
    min_strike_price=185.50  # Cost basis protection
)
```

**Calls Found:**
```python
logger.info("STAGE 8 COMPLETE: Call options criteria - calls found",
    event_category="filtering",
    event_type="stage_8_complete_found",
    symbol="AMD",
    total_calls=68,
    rejected=62,
    suitable_count=6,
    best_call_strike=195.00,
    best_call_premium=1.85,
    best_call_dte=3,
    best_call_delta=0.28,
    # Rejection breakdown
    rejected_below_cost_basis=15,
    rejected_dte_too_high=18,
    rejected_premium_too_low=22,
    rejected_delta_out_of_range=5,
    rejected_no_liquidity=2
)
```

---

### Options Scanner (`src/data/options_scanner.py`)

**Put Scan Start:**
```python
logger.info("Scanning for put opportunities",
    symbols=14
)
```

**Put Scan Complete:**
```python
logger.info("Put scan completed",
    total_opportunities=15,
    returning=10
)
```

**Performance Metric:**
```python
log_performance_metric(
    logger,
    metric_name="put_opportunities_discovered",
    metric_value=15,
    metric_unit="count",
    symbols_scanned=14,
    suitable_stocks=11,
    returning=10,
    top_score=0.0856,
    avg_score=0.0623,
    avg_annual_return=45.2
)
```

**Scan Failure:**
```python
log_error_event(
    logger,
    error_type="scan_failure",
    error_message=str(e),
    component="options_scanner",
    recoverable=True,
    scan_type="put"
)
```

---

### Put Seller (`src/strategy/put_seller.py`)

**Opportunity Evaluation:**
```python
logger.info("Evaluating put opportunity",
    symbol="AMD"
)
```

**No Suitable Puts:**
```python
logger.info("No suitable puts found",
    symbol="F"
)
```

**Position Size Validation Failed:**
```python
logger.info("Position size validation failed",
    symbol="NVDA"
)
```

**Opportunity Identified:**
```python
logger.info("Put opportunity identified",
    symbol="AMD",
    strike=192.50,
    premium=2.17,
    dte=3,
    contracts=1
)
```

**Trade Execution - Success:**
```python
log_trade_event(
    logger,
    event_type="put_sale_executed",
    symbol="AMD251010P00192500",
    strategy="sell_put",
    success=True,
    underlying="AMD",
    strike_price=192.50,
    premium=2.17,
    contracts=1,
    expiration_date="2025-10-10",
    dte=3,
    delta=0.15,
    order_id="abc-123",
    limit_price=2.17,
    capital_required=19250.00,
    max_profit=217.00,
    breakeven=190.33
)
```

**Trade Execution - Failure:**
```python
log_error_event(
    logger,
    error_type="put_sale_failed",
    error_message="Insufficient buying power",
    component="put_seller",
    recoverable=True,
    symbol="AMD",
    required_capital=19250.00,
    available_capital=15000.00
)
```

---

### Gap Detector (`src/risk/gap_detector.py`)

#### Stage 2: Gap Risk Analysis

**Stock Passed:**
```python
logger.info("Stock passed gap risk filter",
    symbol="AAPL",
    gap_risk_score=0.245,
    gap_frequency=0.082,
    volatility=0.285
)
```

**Stock Rejected:**
```python
log_risk_event(
    logger,
    event_type="stock_filtered_by_gap_risk",
    symbol="AMD",
    risk_type="gap_risk",
    action_taken="stock_excluded",
    gap_risk_score=1.000,
    gap_frequency=0.2353,
    historical_volatility=0.8549
)
```

**Stage Complete:**
```python
logger.info("STAGE 2 COMPLETE: Gap risk analysis",
    event_category="filtering",
    event_type="stage_2_complete",
    input_symbols=11,
    passed=9,
    rejected=2,
    passed_symbols=["AAPL", "GOOGL", ...],
    rejected_symbols=["AMD", "NVDA"]
)
```

#### Stage 4: Execution Gap Check

**Gap Exceeded:**
```python
log_risk_event(
    logger,
    event_type="execution_gap_exceeded",
    symbol="AMD",
    risk_type="gap_risk",
    action_taken="trade_blocked",
    gap_percent=2.75,
    threshold=1.50,
    previous_close=189.50,
    current_price=194.71
)
```

**Detection Failure (Conservative Block):**
```python
log_risk_event(
    logger,
    event_type="stock_blocked_gap_detection_failure",
    symbol="AMD",
    risk_type="gap_detection_error",
    action_taken="stock_excluded_conservative_fallback",
    gap_percent=999.0,
    threshold=15.0,
    detection_error="Invalid comparison between dtype=datetime64[ns, UTC] and datetime"
)
```

**Gap Check Error:**
```python
log_error_event(
    logger,
    error_type="gap_check_error",
    error_message=str(e),
    component="gap_detector",
    recoverable=True,
    symbol="AMD"
)
```

---

### Opportunity Store (`src/data/opportunity_store.py`)

**Opportunities Stored:**
```python
log_system_event(
    logger,
    event_type="opportunities_stored",
    status="success",
    opportunity_count=10,
    blob_path="opportunities/2025-10-06/16-00.json",
    expires_at="2025-10-06T16:20:00"
)
```

**Storage Failed:**
```python
log_error_event(
    logger,
    error_type="opportunity_storage_failed",
    error_message=str(e),
    component="opportunity_store",
    recoverable=True,
    opportunity_count=10
)
```

**Opportunities Retrieved:**
```python
logger.info("Retrieved most recent valid scan",
    count=10,
    scan_time="2025-10-06T16:00:15",
    age_minutes=14.5,
    max_age_minutes=20,
    path="opportunities/2025-10-06/16-00.json"
)
```

**Scan Too Old:**
```python
logger.info("Scan too old, skipping",
    scan_time="2025-10-06T15:00:00",
    age_minutes=75.3,
    max_age_minutes=20,
    path="opportunities/2025-10-06/15-00.json"
)
```

**Marked Executed:**
```python
log_system_event(
    logger,
    event_type="opportunities_marked_executed",
    status="success",
    executed_count=3,
    blob_path="opportunities/2025-10-06/16-00.json"
)
```

---

### Alpaca Client (`src/api/alpaca_client.py`)

**Client Initialized:**
```python
logger.info("Alpaca client initialized",
    paper_trading=True
)
```

**Account Info Failed:**
```python
logger.error("Failed to get account info",
    error=str(e)
)
```

**Positions Failed:**
```python
logger.error("Failed to get positions",
    error=str(e)
)
```

**Quote Retrieved:**
```python
logger.debug("Stock quote retrieved",
    symbol="AMD",
    bid=192.45,
    ask=192.53,
    feed="iex"
)
```

**Options Chain Retrieved:**
```python
logger.info("Options chain retrieved",
    symbol="AMD",
    total_contracts=150,
    puts=82,
    calls=68
)
```

---

## Filtering Pipeline (Stage 1-9)

Complete logging for each stage of the risk filtering pipeline:

### Stage 1: Price & Volume Filter
- **Component:** `MarketDataManager.filter_suitable_stocks()`
- **Event Type:** `stage_1_complete`
- **Fields:** total_analyzed, passed, rejected, passed_symbols, rejected_symbols

### Stage 2: Gap Risk Analysis
- **Component:** `GapDetector.filter_stocks_by_gap_risk()`
- **Event Type:** `stage_2_complete`
- **Fields:** input_symbols, passed, rejected, passed_symbols, rejected_symbols

### Stage 3: [Reserved for future use]

### Stage 4: Execution Gap Check
- **Component:** `GapDetector.can_execute_trade()`
- **Event Type:** `execution_gap_exceeded` or `gap_within_limits`
- **Fields:** gap_percent, threshold, previous_close, current_price

### Stage 5: [Reserved for future use]

### Stage 6: [Reserved for future use]

### Stage 7: Put Options Chain Criteria
- **Component:** `MarketDataManager.find_suitable_puts()`
- **Event Types:**
  - `stage_7_start`
  - `stage_7_complete_found`
  - `stage_7_complete_not_found`
- **Fields:** total_puts, rejected, suitable_count, rejection breakdown

### Stage 8: Call Options Chain Criteria
- **Component:** `MarketDataManager.find_suitable_calls()`
- **Event Types:**
  - `stage_8_start`
  - `stage_8_complete_found`
  - `stage_8_complete_not_found`
- **Fields:** total_calls, rejected, suitable_count, rejection breakdown

### Stage 9: Position Sizing & Buying Power
- **Component:** `PutSeller._calculate_position_size()`
- **Event Type:** `stage_9_calculation`
- **Fields:** contracts, capital_required, max_profit, buying_power_used

---

## BigQuery Integration

### Log Export Configuration

**Sink Name:** `options-wheel-logs`

**Filter:**
```
resource.labels.service_name="options-wheel-strategy"
jsonPayload.event_category=*
```

**Destination:** `bigquery.googleapis.com/projects/gen-lang-client-0607444019/datasets/options_wheel_logs`

### Available Views

Created from `/docs/bigquery_views.sql`:

1. **`trades`** - All executed trades
2. **`scan_performance`** - Market scan metrics
3. **`execution_performance`** - Execution metrics
4. **`error_summary`** - Error counts and types
5. **`filtering_stats`** - Stage-by-stage filtering statistics
6. **`risk_events`** - Gap risk and blocking events
7. **`daily_summary`** - Daily performance rollup

### Log Tables

**Raw Logs:**
- `run_googleapis_com_stderr_YYYYMMDD` - Partitioned by day
- Fields: `timestamp`, `severity`, `jsonPayload`, `resource`, `httpRequest`

**Important Fields in jsonPayload:**
- `event_category` - REQUIRED for export
- `event_type` - Specific event name
- `timestamp_ms` - Unix milliseconds
- `timestamp_iso` - ISO 8601 format
- Event-specific fields (symbol, premium, strike, etc.)

---

## Query Examples

### 1. All Trades for a Day

```sql
SELECT
  timestamp_et,
  symbol,
  underlying,
  premium,
  contracts,
  strike_price,
  order_id,
  success
FROM `gen-lang-client-0607444019.options_wheel_logs.trades`
WHERE date_et = "2025-10-06"
ORDER BY timestamp_et DESC
```

### 2. Market Scan Success Rate

```sql
SELECT
  DATE(timestamp) as date,
  COUNT(*) as total_scans,
  COUNTIF(JSON_VALUE(jsonPayload, '$.put_opportunities') > '0') as scans_with_opportunities,
  AVG(CAST(JSON_VALUE(jsonPayload, '$.duration_seconds') AS FLOAT64)) as avg_duration_sec
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_type = "market_scan_completed"
  AND _TABLE_SUFFIX = FORMAT_DATE('%Y%m%d', CURRENT_DATE())
GROUP BY date
```

### 3. Filtering Stage Breakdown

```sql
SELECT
  JSON_VALUE(jsonPayload, '$.stage_number') as stage,
  JSON_VALUE(jsonPayload, '$.event_type') as event_type,
  COUNT(*) as occurrences,
  AVG(CAST(JSON_VALUE(jsonPayload, '$.passed') AS INT64)) as avg_passed,
  AVG(CAST(JSON_VALUE(jsonPayload, '$.rejected') AS INT64)) as avg_rejected
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = "filtering"
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY))
GROUP BY stage, event_type
ORDER BY stage
```

### 4. Gap Risk Rejections

```sql
SELECT
  JSON_VALUE(jsonPayload, '$.symbol') as symbol,
  COUNT(*) as rejection_count,
  AVG(CAST(JSON_VALUE(jsonPayload, '$.gap_frequency') AS FLOAT64)) as avg_gap_freq,
  AVG(CAST(JSON_VALUE(jsonPayload, '$.historical_volatility') AS FLOAT64)) as avg_volatility
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_type = "stock_filtered_by_gap_risk"
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY))
GROUP BY symbol
ORDER BY rejection_count DESC
```

### 5. Trade Execution Success Rate

```sql
SELECT
  DATE(timestamp) as date,
  COUNT(*) as total_executions,
  COUNTIF(JSON_VALUE(jsonPayload, '$.trades_executed') > '0') as successful_executions,
  SUM(CAST(JSON_VALUE(jsonPayload, '$.trades_executed') AS INT64)) as total_trades,
  SUM(CAST(JSON_VALUE(jsonPayload, '$.trades_failed') AS INT64)) as total_failures,
  ROUND(SUM(CAST(JSON_VALUE(jsonPayload, '$.trades_executed') AS INT64)) /
        NULLIF(SUM(CAST(JSON_VALUE(jsonPayload, '$.opportunities_evaluated') AS INT64)), 0) * 100, 2)
    as execution_rate_pct
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_type = "strategy_execution_completed"
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY))
GROUP BY date
ORDER BY date DESC
```

### 6. Error Summary

```sql
SELECT
  JSON_VALUE(jsonPayload, '$.error_type') as error_type,
  JSON_VALUE(jsonPayload, '$.component') as component,
  COUNT(*) as error_count,
  COUNTIF(JSON_VALUE(jsonPayload, '$.recoverable') = 'true') as recoverable_count,
  ARRAY_AGG(JSON_VALUE(jsonPayload, '$.error_message') LIMIT 3) as sample_messages
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_category = "error"
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY))
GROUP BY error_type, component
ORDER BY error_count DESC
```

### 7. Premium Collected by Stock

```sql
SELECT
  JSON_VALUE(jsonPayload, '$.underlying') as stock,
  COUNT(*) as trades,
  SUM(CAST(JSON_VALUE(jsonPayload, '$.premium') AS FLOAT64) *
      CAST(JSON_VALUE(jsonPayload, '$.contracts') AS INT64) * 100) as total_premium,
  AVG(CAST(JSON_VALUE(jsonPayload, '$.premium') AS FLOAT64)) as avg_premium_per_contract,
  AVG(CAST(JSON_VALUE(jsonPayload, '$.strike_price') AS FLOAT64)) as avg_strike
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_type = "put_sale_executed"
  AND JSON_VALUE(jsonPayload, '$.success') = 'true'
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY))
GROUP BY stock
ORDER BY total_premium DESC
```

### 8. Hourly Execution Pattern

```sql
SELECT
  EXTRACT(HOUR FROM timestamp) as hour_et,
  COUNT(*) as execution_count,
  AVG(CAST(JSON_VALUE(jsonPayload, '$.trades_executed') AS INT64)) as avg_trades_per_execution,
  SUM(CAST(JSON_VALUE(jsonPayload, '$.trades_executed') AS INT64)) as total_trades
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_type = "strategy_execution_completed"
  AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY))
GROUP BY hour_et
ORDER BY hour_et
```

---

## Monitoring & Alerts

### Key Performance Indicators (KPIs)

**Scan Health:**
- Market scan completion rate: >95%
- Average scan duration: <20 seconds
- Opportunities found per scan: >3

**Execution Health:**
- Execution success rate: >15%
- Trade execution latency: <10 seconds
- Buying power utilization: 40-80%

**Error Thresholds:**
- API errors: <5 per day
- Gap detection failures: <2 per day
- Storage failures: 0 per day

### Alert Queries

**Scan Failures:**
```sql
SELECT COUNT(*) as failures
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.error_type = "market_scan_exception"
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
-- Alert if failures > 2
```

**No Opportunities Alert:**
```sql
SELECT COUNT(*) as zero_opp_scans
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_type = "market_scan_completed"
  AND CAST(JSON_VALUE(jsonPayload, '$.total_opportunities') AS INT64) = 0
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR)
-- Alert if zero_opp_scans > 4 (entire morning)
```

**Execution Drought:**
```sql
SELECT COUNT(*) as executions_with_trades
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_type = "strategy_execution_completed"
  AND CAST(JSON_VALUE(jsonPayload, '$.trades_executed') AS INT64) > 0
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
-- Alert if executions_with_trades = 0
```

**Gap Detection Errors:**
```sql
SELECT COUNT(*) as gap_errors
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr_*`
WHERE jsonPayload.event_type = "stock_blocked_gap_detection_failure"
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
-- Alert if gap_errors > 3
```

---

## Best Practices

### 1. Always Include Event Category
```python
# ❌ WRONG - Won't export to BigQuery
logger.info("Some event", metric=123)

# ✅ CORRECT
logger.info("Some event", event_category="filtering", metric=123)
```

### 2. Use Standardized Functions
```python
# ✅ PREFERRED - Uses standardized function
from src.utils.logging_events import log_trade_event

log_trade_event(logger, event_type="put_sale_executed", ...)

# ⚠️ ACCEPTABLE - Manual logging with event_category
logger.info("Put sale executed",
    event_category="trade",
    event_type="put_sale_executed",
    ...)
```

### 3. Include Context
```python
# ❌ INSUFFICIENT
logger.error("Trade failed")

# ✅ GOOD
log_error_event(
    logger,
    error_type="trade_execution_failed",
    error_message="Insufficient buying power",
    component="put_seller",
    recoverable=True,
    symbol="AMD",
    required=19250.00,
    available=15000.00
)
```

### 4. Log at Appropriate Levels
- `logger.debug()` - Detailed diagnostic info (not exported to BigQuery)
- `logger.info()` - Normal operations, events
- `logger.warning()` - Risk events, degraded operations
- `logger.error()` - Errors, failures

### 5. Timing/Performance
```python
import time

start = time.time()
# ... operation ...
duration = time.time() - start

log_performance_metric(
    logger,
    metric_name="operation_duration",
    metric_value=duration,
    metric_unit="seconds"
)
```

---

## Common Logging Patterns

### Pattern 1: Operation Start/Complete

```python
logger.info("Starting market scan", symbols=14)

# ... perform scan ...

log_system_event(
    logger,
    event_type="market_scan_completed",
    status="completed",
    duration_seconds=duration,
    opportunities_found=len(opportunities)
)
```

### Pattern 2: Try/Except with Error Logging

```python
try:
    result = perform_operation()
except Exception as e:
    log_error_event(
        logger,
        error_type="operation_failed",
        error_message=str(e),
        component="component_name",
        recoverable=True
    )
    return None
```

### Pattern 3: Filtering with Rejection Tracking

```python
passed = []
rejected = []

for item in items:
    if meets_criteria(item):
        passed.append(item)
    else:
        rejected.append(item)
        logger.info("Item rejected",
            event_category="filtering",
            item_id=item.id,
            reason=get_rejection_reason(item))

logger.info("STAGE X COMPLETE",
    event_category="filtering",
    event_type="stage_x_complete",
    total=len(items),
    passed=len(passed),
    rejected=len(rejected))
```

### Pattern 4: Trade Execution with Outcome

```python
try:
    order = execute_trade(opportunity)

    log_trade_event(
        logger,
        event_type="put_sale_executed",
        symbol=opportunity['option_symbol'],
        strategy="sell_put",
        success=True,
        underlying=opportunity['symbol'],
        strike_price=opportunity['strike_price'],
        premium=opportunity['premium'],
        contracts=opportunity['contracts'],
        order_id=order.id
    )

except InsufficientFundsError as e:
    log_error_event(
        logger,
        error_type="insufficient_buying_power",
        error_message=str(e),
        component="put_seller",
        recoverable=True,
        symbol=opportunity['symbol'],
        required=calculate_required_capital(opportunity),
        available=get_buying_power()
    )
```

---

## Appendix: Complete Event Type Catalog

### Trade Events
- `put_sale_executed` - Put option sold
- `call_sale_executed` - Call option sold
- `put_sale_failed` - Put sale attempt failed
- `call_sale_failed` - Call sale attempt failed
- `position_opened` - New position opened
- `position_closed` - Position closed
- `position_assigned` - Option assigned

### System Events
- `market_scan_triggered` - Scan initiated
- `market_scan_completed` - Scan finished
- `strategy_execution_triggered` - Execution initiated
- `strategy_execution_completed` - Execution finished
- `opportunities_stored` - Opportunities saved to storage
- `opportunities_marked_executed` - Execution recorded
- `trade_executed` - Individual trade completed

### Risk Events
- `stock_filtered_by_gap_risk` - Stock excluded by gap analysis
- `execution_gap_exceeded` - Trade blocked by gap threshold
- `stock_blocked_gap_detection_failure` - Conservative block due to error
- `gap_detected` - Gap identified but within limits

### Performance Events
- `market_scan_duration` - Time to complete scan
- `strategy_execution_duration` - Time to execute trades
- `put_opportunities_discovered` - Number of puts found

### Error Events
- `market_scan_exception` - Scan crashed
- `scan_failure` - Scanner component failure
- `trade_execution_failed` - Trade attempt failed
- `opportunity_storage_failed` - Storage write error
- `opportunity_retrieval_failed` - Storage read error
- `gap_check_error` - Gap detection error
- `current_gap_detection_failed` - Current gap check failed
- `insufficient_funds` - Not enough buying power
- `api_error` - External API failure

### Filtering Events (Stage 1-9)
- `stage_1_complete` - Price/volume filter complete
- `stage_2_complete` - Gap risk analysis complete
- `stage_4_execution_gap_check` - Execution gap verification
- `stage_7_start` - Put options scan starting
- `stage_7_complete_found` - Suitable puts identified
- `stage_7_complete_not_found` - No suitable puts
- `stage_8_start` - Call options scan starting
- `stage_8_complete_found` - Suitable calls identified
- `stage_8_complete_not_found` - No suitable calls
- `stage_9_calculation` - Position sizing calculated

---

## Support & Troubleshooting

### Common Issues

**Issue: Logs not appearing in BigQuery**
- Check: Does log include `event_category` field?
- Check: Cloud Logging Sink filter
- Check: BigQuery dataset permissions

**Issue: Missing fields in BigQuery**
- All fields must be at top level of `jsonPayload`
- Use `JSON_VALUE(jsonPayload, '$.field_name')` for dynamic fields
- Check table schema in BigQuery console

**Issue: Duplicate logs**
- Check for multiple logger instances
- Verify structlog configuration
- Check Cloud Run revision count

### Debug Commands

**View recent logs:**
```bash
gcloud logging read 'resource.labels.service_name="options-wheel-strategy"' \
  --limit=50 --format=json
```

**Test BigQuery export:**
```bash
bq query --use_legacy_sql=false \
  'SELECT * FROM `options_wheel_logs.run_googleapis_com_stderr_*` LIMIT 10'
```

**Check sink status:**
```bash
gcloud logging sinks describe options-wheel-logs
```

---

**End of Logging Reference**

For questions or updates, see:
- [CLAUDE.md](CLAUDE.md) - Development guidelines
- [LOGGING_GUIDELINES.md](LOGGING_GUIDELINES.md) - Logging best practices
- [bigquery_views.sql](bigquery_views.sql) - View definitions
