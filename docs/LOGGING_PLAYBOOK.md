# Logging Playbook for Options Wheel Strategy

## Overview

This document provides the standard logging implementation patterns for all new features, endpoints, and scheduled jobs in the Options Wheel Strategy. Following this playbook ensures consistent logging across Cloud Logging, BigQuery analytics, and monitoring dashboards.

## Logging Architecture

### Data Flow
```
Cloud Run Service (structlog)
    ↓
Cloud Logging (raw JSON logs)
    ↓
Log Sink (filters by service_name)
    ↓
BigQuery Dataset (options_wheel_logs)
    ↓
BigQuery Views (for analytics)
```

### Key Components

1. **Cloud Logging**: Real-time log streaming and search
2. **BigQuery Tables**: Structured data storage for analytics
3. **BigQuery Views**: Pre-computed queries for monitoring
4. **Structured Logging**: Uses `structlog` with consistent field naming

## Required Imports

```python
import structlog
from src.utils.logging_events import (
    log_system_event,      # System-level events (job start/end)
    log_trade_event,       # Trade executions (buy/sell)
    log_performance_metric,# Performance tracking
    log_error_event,       # Error handling
    log_filtering_event,   # Stage filtering decisions
    log_position_update    # Position state changes
)

logger = structlog.get_logger(__name__)
```

## Logging Event Types

### 1. System Events (`log_system_event`)

Use for: Job triggers, completions, status changes

```python
# Job Start
log_system_event(
    logger,
    event_type="position_monitoring_triggered",
    status="starting"
)

# Job Complete
log_system_event(
    logger,
    event_type="position_monitoring_completed",
    status="completed",
    duration_seconds=duration_seconds,
    positions_evaluated=len(positions),
    positions_closed=len(closed),
    errors=len(errors)
)

# Job Failed
log_system_event(
    logger,
    event_type="position_monitoring_failed",
    status="error",
    error=str(e),
    duration_seconds=duration_seconds
)
```

**Required Fields:**
- `event_type`: Descriptive name (e.g., "market_scan_triggered")
- `status`: "starting", "completed", "error", "warning"
- `duration_seconds`: Execution time (for completed events)

### 2. Trade Events (`log_trade_event`)

Use for: Trade executions, position opens/closes

```python
log_trade_event(
    logger,
    event_type="early_close_executed",
    symbol="AMD251017P00330000",
    strategy="close_put",
    success=True,
    underlying="AMD",
    option_type="PUT",
    contracts=1,
    unrealized_pl=82.50,
    profit_pct=52.3,
    order_id="abc123",
    reason="profit_target_reached",
    market_value=158.00,
    entry_price=1.58,
    exit_price=0.76
)
```

**Required Fields:**
- `event_type`: Trade action (e.g., "put_sale_executed", "early_close_executed")
- `symbol`: Option symbol (full OCC format)
- `strategy`: Trading strategy ("sell_put", "sell_call", "close_put", "close_call")
- `success`: Boolean indicating trade success
- `underlying`: Stock symbol
- `contracts`: Number of contracts
- `order_id`: Alpaca order ID

**Recommended Fields:**
- `premium`, `strike_price`, `dte`, `delta`, `unrealized_pl`, `profit_pct`, `reason`

### 3. Performance Metrics (`log_performance_metric`)

Use for: Tracking execution timing and efficiency

```python
log_performance_metric(
    logger,
    metric_name="position_monitoring_duration",
    metric_value=duration_seconds,
    unit="seconds",
    context={
        'positions_evaluated': len(positions),
        'positions_closed': len(closed),
        'success_rate': f"{(len(closed)/len(positions)*100):.1f}%"
    }
)
```

### 4. Error Events (`log_error_event`)

Use for: Error handling and debugging

```python
log_error_event(
    logger,
    error_type="position_evaluation_failed",
    error_message=str(e),
    component="monitor_positions",
    recoverable=True,
    symbol=symbol,
    traceback=traceback.format_exc()
)
```

### 5. Filtering Events (`log_filtering_event`)

Use for: Stage-by-stage filtering decisions

```python
log_filtering_event(
    logger,
    stage=6,
    stage_name="existing_position_check",
    action="blocked",
    symbol="AAPL",
    reason="profit_target_not_reached",
    profit_pct=35.2,
    target_pct=50.0
)
```

## Standard Logging Pattern for New Endpoints

### Template for HTTP Endpoints

```python
@app.route('/your-endpoint', methods=['POST'])
def your_endpoint():
    """Description of endpoint."""
    with strategy_lock:
        start_time = datetime.now()
        try:
            # 1. Log trigger
            log_system_event(
                logger,
                event_type="your_job_triggered",
                status="starting"
            )

            # 2. Initialize components
            config = Config()
            # ... component setup ...

            # 3. Main logic with detailed logging
            results = []
            errors = []

            for item in items_to_process:
                try:
                    # Process item
                    result = process_item(item)

                    # Log success
                    logger.info("Item processed successfully",
                               event_category="execution",
                               event_type="item_processed",
                               item_id=item['id'],
                               **result)

                    # Log trade events if applicable
                    if result.get('trade_executed'):
                        log_trade_event(
                            logger,
                            event_type="trade_executed",
                            symbol=result['symbol'],
                            strategy=result['strategy'],
                            success=True,
                            **result
                        )

                    results.append(result)

                except Exception as item_error:
                    # Log individual item errors
                    log_error_event(
                        logger,
                        error_type="item_processing_failed",
                        error_message=str(item_error),
                        component="your_endpoint",
                        recoverable=True,
                        item_id=item.get('id')
                    )
                    errors.append(str(item_error))

            # 4. Calculate duration
            duration_seconds = (datetime.now() - start_time).total_seconds()

            # 5. Log completion
            log_system_event(
                logger,
                event_type="your_job_completed",
                status="completed",
                duration_seconds=duration_seconds,
                items_processed=len(results),
                errors=len(errors)
            )

            # 6. Log performance metric
            log_performance_metric(
                logger,
                metric_name="your_job_duration",
                metric_value=duration_seconds,
                unit="seconds",
                context={
                    'items_processed': len(results),
                    'success_rate': f"{(len(results)/(len(results)+len(errors))*100):.1f}%"
                }
            )

            # 7. Return response
            return jsonify({
                'message': 'Job completed',
                'timestamp': datetime.now().isoformat(),
                'results': {
                    'items_processed': len(results),
                    'errors': len(errors),
                    'duration_seconds': duration_seconds
                }
            })

        except Exception as e:
            # 8. Log failure
            error_msg = f"Job failed: {str(e)}"

            log_error_event(
                logger,
                error_type="job_exception",
                error_message=error_msg,
                component="your_endpoint",
                recoverable=False,
                traceback=traceback.format_exc()
            )

            log_system_event(
                logger,
                event_type="your_job_failed",
                status="error",
                error=error_msg,
                duration_seconds=(datetime.now() - start_time).total_seconds()
            )

            return jsonify({'error': error_msg}), 500
```

## Standard Event Categories

Use consistent `event_category` values:

- **`system`**: Job triggers, completions, status changes
- **`execution`**: Trade executions, order placements
- **`filtering`**: Stage filtering decisions
- **`error`**: Error conditions
- **`performance`**: Timing and efficiency metrics
- **`monitoring`**: Position monitoring, risk checks

## BigQuery Integration

### Automatic Table Creation

The log sink automatically creates tables:
- `run_googleapis_com_stderr` - All Cloud Run logs
- `run_googleapis_com_stdout` - (if configured)

### Custom Views for New Features

After adding a new feature with logging, create BigQuery views:

```sql
-- View for monitoring early closes
CREATE OR REPLACE VIEW `gen-lang-client-0607444019.options_wheel_logs.early_closes` AS
SELECT
  timestamp,
  TIMESTAMP(DATETIME(timestamp, 'America/New_York')) as timestamp_et,
  DATE(DATETIME(timestamp, 'America/New_York')) as date_et,
  jsonPayload.symbol as option_symbol,
  jsonPayload.underlying as underlying,
  jsonPayload.option_type as type,
  jsonPayload.contracts as contracts,
  CAST(jsonPayload.unrealized_pl AS FLOAT64) as profit,
  CAST(jsonPayload.profit_pct AS FLOAT64) as profit_pct,
  jsonPayload.order_id as order_id,
  jsonPayload.reason as close_reason
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr`
WHERE jsonPayload.event_type = 'early_close_executed'
ORDER BY timestamp DESC;
```

## Verification Checklist

When implementing a new feature, verify:

### ✅ Cloud Logging
```bash
# Check logs appear in Cloud Logging
gcloud logging read 'resource.labels.service_name="options-wheel-strategy" AND jsonPayload.event_type="your_event_type"' --limit=5 --format=json
```

### ✅ BigQuery Data Flow
```bash
# Verify log sink is active
gcloud logging sinks describe options-wheel-logs

# Check BigQuery table has data
bq query --use_legacy_sql=false '
SELECT COUNT(*) as log_count
FROM `gen-lang-client-0607444019.options_wheel_logs.run_googleapis_com_stderr`
WHERE jsonPayload.event_type = "your_event_type"'
```

### ✅ Event Structure
```bash
# Verify log structure
gcloud logging read 'resource.labels.service_name="options-wheel-strategy" AND jsonPayload.event_type="your_event_type"' --limit=1 --format=json | python3 -m json.tool
```

## Example: Position Monitoring Implementation

See the `/monitor` endpoint implementation for a complete example following this playbook:
- [cloud_run_server.py:460-610](../deploy/cloud_run_server.py#L460-L610)

Key features:
- ✅ System events (start, complete, error)
- ✅ Trade events for each position close
- ✅ Error handling with detailed logging
- ✅ Performance metrics
- ✅ Structured data for BigQuery analytics

## Common Patterns

### Pattern 1: Batch Processing with Individual Logging

```python
for item in items:
    try:
        result = process_item(item)
        logger.info("Item processed", item_id=item['id'], **result)
    except Exception as e:
        log_error_event(logger, error_type="item_failed", ...)
```

### Pattern 2: Conditional Trade Logging

```python
if should_execute_trade(position):
    result = execute_trade(position)
    log_trade_event(logger, event_type="trade_executed", ...)
else:
    log_filtering_event(logger, stage=X, action="blocked", ...)
```

### Pattern 3: Performance Tracking

```python
start_time = datetime.now()
# ... do work ...
duration = (datetime.now() - start_time).total_seconds()

log_performance_metric(
    logger,
    metric_name="operation_duration",
    metric_value=duration,
    unit="seconds",
    context={'items_processed': count}
)
```

## Instructions for Claude

When creating new endpoints, jobs, or features:

1. **Always add comprehensive logging** following this playbook
2. **Import required logging functions** from `src.utils.logging_events`
3. **Log at minimum**:
   - Job start (`log_system_event` with status="starting")
   - Job completion (`log_system_event` with status="completed" + duration)
   - Job errors (`log_system_event` with status="error" + `log_error_event`)
   - Trade executions (`log_trade_event` with all required fields)
4. **Use consistent event_type naming**: `{feature}_{action}_{outcome}`
   - Examples: `position_monitoring_triggered`, `early_close_executed`, `scan_completed`
5. **Include context**: Add relevant fields like symbol, strategy, duration, counts
6. **Test verification**: Provide gcloud commands to verify logs appear correctly
7. **Create BigQuery views**: If adding analytics-worthy events, provide SQL for views
8. **Document in code**: Add comments explaining what events are logged and why

## Related Documentation

- [BIGQUERY_LOGGING_SETUP.md](./BIGQUERY_LOGGING_SETUP.md) - Initial setup guide
- [BIGQUERY_VIEWS_USAGE_GUIDE.md](./BIGQUERY_VIEWS_USAGE_GUIDE.md) - View creation and usage
- [BIGQUERY_USAGE_GUIDE.md](./BIGQUERY_USAGE_GUIDE.md) - Query examples

## Logging Anti-Patterns to Avoid

❌ **Don't**: Log without event_type
```python
logger.info("Processing position")  # Too vague
```

✅ **Do**: Use specific event_type
```python
logger.info("Processing position",
           event_category="execution",
           event_type="position_evaluation_started",
           symbol=symbol)
```

❌ **Don't**: Skip error logging
```python
except Exception:
    pass  # Silent failure
```

✅ **Do**: Log all errors
```python
except Exception as e:
    log_error_event(logger, error_type="...", error_message=str(e), ...)
```

❌ **Don't**: Log trades without structured data
```python
logger.info(f"Closed {symbol} for profit")  # Not queryable
```

✅ **Do**: Use log_trade_event with fields
```python
log_trade_event(logger, event_type="early_close_executed",
               symbol=symbol, profit_pct=52.3, ...)  # Queryable in BigQuery
```

## Maintenance

This playbook should be updated when:
- New logging event types are added
- BigQuery schema changes
- New analytics requirements emerge
- Best practices evolve

Last updated: 2025-10-15
