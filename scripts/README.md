# Scripts Directory

This directory contains standalone utility scripts for testing, setup, and operational tasks.

## Directory Structure

### `testing/`
Manual test scripts for verifying system functionality:

- **`test_live_positions.py`** - Check Alpaca account status and balances
- **`test_trading_workflow.py`** - Complete workflow simulation (scan → execute → monitor)
- **`test_trade_execution.py`** - Detailed trade execution test with risk validation
- **`test_live_engine.py`** - Live engine testing

`test_issue_audit.py` was **deleted by FC-069 S1**. It audited the account
against `max_exposure_per_ticker`, `min_cash_reserve`, `max_portfolio_allocation`
and `max_total_positions` — a policy layer that never gated a trade and that
FC-069 removed, so its premise is gone. Its useful residue (account-vs-config
arithmetic) is superseded by the hourly `/regression` checks.

### Usage

Run any test script directly:
```bash
# Check account balance
python scripts/testing/test_live_positions.py

# Run full workflow test
python scripts/testing/test_trading_workflow.py

# Simulate trade execution
python scripts/testing/test_trade_execution.py
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
