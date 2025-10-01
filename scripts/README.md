# Scripts Directory

This directory contains standalone utility scripts for testing, setup, and operational tasks.

## Directory Structure

### `testing/`
Manual test scripts for verifying system functionality:

- **`test_live_positions.py`** - Check Alpaca account status and balances
- **`test_trading_workflow.py`** - Complete workflow simulation (scan → execute → monitor)
- **`test_trade_execution.py`** - Detailed trade execution test with risk validation
- **`test_live_engine.py`** - Live engine testing
- **`test_issue_audit.py`** - Comprehensive system audit for pre-launch checks

### Usage

Run any test script directly:
```bash
# Check account balance
python scripts/testing/test_live_positions.py

# Run full workflow test
python scripts/testing/test_trading_workflow.py

# Simulate trade execution
python scripts/testing/test_trade_execution.py

# Run system audit
python scripts/testing/test_issue_audit.py
```

### Requirements

Set environment variables before running:
```bash
export ALPACA_API_KEY="your_key"
export ALPACA_SECRET_KEY="your_secret"
```

Or the scripts will attempt to load from Google Cloud Secret Manager.

## Related Directories

- `tests/` - Unit tests (pytest-based, automated)
- `tools/testing/` - Integration test tools and utilities
- `examples/` - Example usage and demonstrations
