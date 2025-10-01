"""Standardized logging events for BigQuery analytics.

This module provides consistent logging functions for key trading events,
making it easy to query and analyze logs in BigQuery.

All events are logged with standardized fields for easy aggregation:
- event_category: High-level category (trade, risk, system, error)
- event_type: Specific event name
- timestamp_ms: Unix milliseconds for precise timing
- Symbol, strategy, and other contextual data

BigQuery Integration:
- All fields are logged at the top level of jsonPayload
- This ensures they're automatically unpacked into separate columns
- No nested JSON = easier SQL queries
"""

import time
from typing import Any, Dict, Optional
from datetime import datetime


def log_trade_event(
    logger: Any,
    event_type: str,
    symbol: str,
    strategy: str,
    success: bool,
    **kwargs
) -> None:
    """Log a trading event for BigQuery analytics.

    Args:
        logger: structlog logger instance
        event_type: Type of trade event (e.g., 'put_sale_executed', 'call_sale_executed')
        symbol: Stock or option symbol
        strategy: Trading strategy (e.g., 'sell_put', 'sell_call')
        success: Whether the operation succeeded
        **kwargs: Additional context (premium, strike_price, contracts, etc.)

    Example:
        log_trade_event(
            logger,
            event_type="put_sale_executed",
            symbol="AMD251003P00155000",
            strategy="sell_put",
            success=True,
            underlying="AMD",
            strike_price=155.00,
            premium=0.74,
            contracts=1,
            order_id="abc123"
        )

    BigQuery Result:
        All fields become columns: event_category, event_type, symbol, strategy,
        success, underlying, strike_price, premium, contracts, order_id
    """
    logger.info(
        event_type,
        event_category="trade",
        event_type=event_type,
        symbol=symbol,
        strategy=strategy,
        success=success,
        timestamp_ms=int(time.time() * 1000),
        timestamp_iso=datetime.now().isoformat(),
        **kwargs
    )


def log_risk_event(
    logger: Any,
    event_type: str,
    symbol: str,
    risk_type: str,
    action_taken: str,
    **kwargs
) -> None:
    """Log a risk management event.

    Args:
        logger: structlog logger instance
        event_type: Type of risk event (e.g., 'gap_detected', 'stop_loss_triggered')
        symbol: Stock symbol
        risk_type: Type of risk (e.g., 'gap_risk', 'position_risk', 'buying_power')
        action_taken: Action taken (e.g., 'trade_blocked', 'position_closed', 'alert_sent')
        **kwargs: Additional context (gap_percent, threshold, etc.)

    Example:
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

    BigQuery Result:
        SELECT symbol, gap_percent, action_taken
        FROM logs
        WHERE event_category = 'risk'
    """
    logger.warning(
        event_type,
        event_category="risk",
        event_type=event_type,
        symbol=symbol,
        risk_type=risk_type,
        action_taken=action_taken,
        timestamp_ms=int(time.time() * 1000),
        timestamp_iso=datetime.now().isoformat(),
        **kwargs
    )


def log_performance_metric(
    logger: Any,
    metric_name: str,
    metric_value: float,
    metric_unit: str,
    **kwargs
) -> None:
    """Log a performance metric.

    Args:
        logger: structlog logger instance
        metric_name: Name of metric (e.g., 'scan_duration', 'execution_latency')
        metric_value: Numeric value
        metric_unit: Unit of measurement (e.g., 'seconds', 'milliseconds', 'count')
        **kwargs: Additional context

    Example:
        log_performance_metric(
            logger,
            metric_name="market_scan_duration",
            metric_value=4.23,
            metric_unit="seconds",
            symbols_scanned=10,
            opportunities_found=8
        )

    BigQuery Result:
        SELECT metric_name, AVG(metric_value)
        FROM logs
        WHERE event_category = 'performance'
        GROUP BY metric_name
    """
    logger.info(
        f"metric.{metric_name}",
        event_category="performance",
        event_type="metric",
        metric_name=metric_name,
        metric_value=metric_value,
        metric_unit=metric_unit,
        timestamp_ms=int(time.time() * 1000),
        timestamp_iso=datetime.now().isoformat(),
        **kwargs
    )


def log_error_event(
    logger: Any,
    error_type: str,
    error_message: str,
    component: str,
    recoverable: bool = False,
    **kwargs
) -> None:
    """Log an error event for tracking failures.

    Args:
        logger: structlog logger instance
        error_type: Type of error (e.g., 'api_error', 'validation_error', 'timeout')
        error_message: Human-readable error message
        component: Component where error occurred (e.g., 'put_seller', 'alpaca_client')
        recoverable: Whether system can recover from this error
        **kwargs: Additional context

    Example:
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

    BigQuery Result:
        SELECT error_type, COUNT(*) as error_count
        FROM logs
        WHERE event_category = 'error' AND recoverable = false
        GROUP BY error_type
    """
    logger.error(
        error_type,
        event_category="error",
        event_type=error_type,
        error_message=error_message,
        component=component,
        recoverable=recoverable,
        timestamp_ms=int(time.time() * 1000),
        timestamp_iso=datetime.now().isoformat(),
        **kwargs
    )


def log_system_event(
    logger: Any,
    event_type: str,
    status: str,
    **kwargs
) -> None:
    """Log a system-level event.

    Args:
        logger: structlog logger instance
        event_type: Type of system event (e.g., 'service_started', 'scheduled_job_triggered')
        status: Status (e.g., 'starting', 'running', 'completed', 'failed')
        **kwargs: Additional context

    Example:
        log_system_event(
            logger,
            event_type="strategy_cycle_completed",
            status="completed",
            duration_seconds=12.5,
            actions_taken=3,
            new_positions=2,
            closed_positions=1
        )

    BigQuery Result:
        SELECT event_type, AVG(duration_seconds) as avg_duration
        FROM logs
        WHERE event_category = 'system'
        GROUP BY event_type
    """
    logger.info(
        event_type,
        event_category="system",
        event_type=event_type,
        status=status,
        timestamp_ms=int(time.time() * 1000),
        timestamp_iso=datetime.now().isoformat(),
        **kwargs
    )


def log_backtest_event(
    logger: Any,
    event_type: str,
    backtest_id: str,
    **kwargs
) -> None:
    """Log a backtesting event.

    Args:
        logger: structlog logger instance
        event_type: Type of backtest event (e.g., 'backtest_started', 'backtest_completed')
        backtest_id: Unique identifier for the backtest run
        **kwargs: Additional context (symbols, date_range, results, etc.)

    Example:
        log_backtest_event(
            logger,
            event_type="backtest_completed",
            backtest_id="bt_1633024800",
            total_return=0.045,
            win_rate=0.75,
            max_drawdown=-0.018,
            sharpe_ratio=1.85,
            total_trades=45,
            duration_seconds=45.2
        )

    BigQuery Result:
        SELECT backtest_id, total_return, win_rate, sharpe_ratio
        FROM logs
        WHERE event_category = 'backtest' AND event_type = 'backtest_completed'
    """
    logger.info(
        event_type,
        event_category="backtest",
        event_type=event_type,
        backtest_id=backtest_id,
        timestamp_ms=int(time.time() * 1000),
        timestamp_iso=datetime.now().isoformat(),
        **kwargs
    )


def log_position_update(
    logger: Any,
    event_type: str,
    symbol: str,
    position_status: str,
    **kwargs
) -> None:
    """Log a position management event.

    Args:
        logger: structlog logger instance
        event_type: Type of position event (e.g., 'position_opened', 'position_closed', 'position_adjusted')
        symbol: Stock or option symbol
        position_status: Current status (e.g., 'open', 'closed', 'assigned', 'rolled')
        **kwargs: Additional context (quantity, cost_basis, pnl, etc.)

    Example:
        log_position_update(
            logger,
            event_type="position_assigned",
            symbol="AMD",
            position_status="assigned",
            shares=100,
            assignment_price=155.00,
            original_premium=0.74,
            effective_cost_basis=154.26
        )

    BigQuery Result:
        SELECT symbol, position_status, effective_cost_basis
        FROM logs
        WHERE event_category = 'position'
    """
    logger.info(
        event_type,
        event_category="position",
        event_type=event_type,
        symbol=symbol,
        position_status=position_status,
        timestamp_ms=int(time.time() * 1000),
        timestamp_iso=datetime.now().isoformat(),
        **kwargs
    )
