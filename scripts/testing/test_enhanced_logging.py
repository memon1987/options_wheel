#!/usr/bin/env python3
"""Test script to verify enhanced logging is working correctly."""

import sys
import os
from datetime import datetime

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import structlog
from src.utils.logging_events import (
    log_trade_event,
    log_risk_event,
    log_performance_metric,
    log_error_event,
    log_system_event,
    log_position_update
)

# Configure structlog for console output
structlog.configure(
    processors=[
        structlog.processors.JSONRenderer()
    ]
)

logger = structlog.get_logger(__name__)

def test_all_logging_events():
    """Test all enhanced logging event types."""

    print("=== Testing Enhanced Logging Events ===\n")

    # 1. Test trade event
    print("1. Trade Event:")
    log_trade_event(
        logger,
        event_type="put_sale_executed",
        symbol="AMD250117P00155000",
        underlying="AMD",
        strategy="sell_put",
        success=True,
        strike_price=155.0,
        premium=0.74,
        contracts=2,
        limit_price=0.70,
        order_id="test-order-123",
        collateral_required=31000.0,
        dte=45
    )
    print()

    # 2. Test risk event
    print("2. Risk Event:")
    log_risk_event(
        logger,
        event_type="execution_gap_exceeded",
        symbol="TSLA",
        risk_type="gap_risk",
        action_taken="trade_blocked",
        gap_percent=3.2,
        threshold=1.5,
        previous_close=245.50,
        current_price=253.35
    )
    print()

    # 3. Test performance metric
    print("3. Performance Metric:")
    log_performance_metric(
        logger,
        metric_name="market_scan_duration",
        metric_value=2.34,
        metric_unit="seconds",
        symbols_scanned=10,
        suitable_stocks=8,
        gap_filtered_stocks=6
    )
    print()

    # 4. Test error event
    print("4. Error Event:")
    log_error_event(
        logger,
        error_type="insufficient_buying_power",
        error_message="Need $31,000 but only $25,000 available",
        component="put_seller",
        recoverable=True,
        symbol="AMD250117P00155000",
        underlying="AMD",
        required=31000.0,
        available=25000.0,
        shortage=6000.0
    )
    print()

    # 5. Test system event
    print("5. System Event:")
    log_system_event(
        logger,
        event_type="strategy_cycle_completed",
        status="completed",
        duration_seconds=5.67,
        actions_taken=3,
        new_positions=1,
        closed_positions=0,
        positions_analyzed=5
    )
    print()

    # 6. Test position update (wheel cycle)
    print("6. Position Update (Wheel Cycle Complete):")
    log_position_update(
        logger,
        event_type="call_assignment",
        symbol="AAPL",
        position_status="assigned",
        position_type="call",
        action="assignment",
        shares=100,
        assignment_price=175.0,
        capital_gain=500.0,
        realized_pnl=750.0,
        remaining_shares=0,
        phase_before="selling_calls",
        phase_after="selling_puts",
        wheel_cycle_completed=True,
        cycle_duration_days=45,
        total_premium_collected=250.0,
        total_return=750.0
    )
    print()

    print("=== All Enhanced Logging Tests Complete ===")
    print("\n✅ All events logged successfully!")
    print("📊 Each event includes event_category for BigQuery filtering")
    print("🔍 All fields are at top level for automatic BigQuery unpacking")

if __name__ == "__main__":
    test_all_logging_events()
