# Codebase Reorganization Plan

## Current Issues
1. **Test files scattered in root** - 5 test_*.py files cluttering root directory
2. **Duplicate script locations** - Scripts in both `tools/` and root
3. **Unclear folder purposes** - `ongoing_dev/` not clearly named
4. **Documentation spread out** - Multiple README files in different locations

## Proposed New Structure

```
options_wheel/
├── config/                      # Configuration files
│   └── settings.yaml
│
├── src/                         # Core application code (GOOD - keep as is)
│   ├── api/                     # Alpaca API integration
│   ├── backtesting/             # Backtesting engine
│   ├── data/                    # Data management
│   ├── risk/                    # Risk management
│   ├── strategy/                # Trading strategies
│   └── utils/                   # Utilities
│
├── tests/                       # Unit tests (GOOD)
│   └── test_*.py
│
├── tools/                       # Operational tools (REORGANIZE)
│   ├── backtesting/             # Backtest runners
│   ├── deployment/              # Deployment scripts
│   ├── development/             # Dev utilities
│   ├── monitoring/              # Monitoring scripts
│   └── testing/                 # Integration/manual tests
│       → MOVE: test_*.py from root here
│
├── scripts/                     # NEW: Standalone utility scripts
│   ├── testing/                 # Manual test scripts
│   │   ├── test_live_positions.py       (from root)
│   │   ├── test_trading_workflow.py     (from root)
│   │   ├── test_trade_execution.py      (from root)
│   │   ├── test_live_engine.py          (from root)
│   │   └── test_issue_audit.py          (from root)
│   └── setup/                   # Setup/installation scripts
│       └── (empty for now)
│
├── deploy/                      # Deployment configs (GOOD)
│   ├── kubernetes/
│   ├── monitoring/
│   ├── cloud_run_server.py
│   └── docker-compose.yml
│
├── docs/                        # Documentation (GOOD)
│   └── *.md
│
├── examples/                    # Example usage (GOOD)
│   └── *.py
│
├── research/                    # NEW: Rename from 'ongoing_dev'
│   └── experiments/             # Experimental features
│       └── monday_only_backtesting/
│
├── .github/                     # CI/CD workflows
│   └── workflows/
│
├── main.py                      # Main entry point (KEEP)
├── setup.py                     # Package setup (KEEP)
├── README.md                    # Main README (KEEP)
├── cloudbuild.yaml             # Cloud Build config (KEEP)
└── requirements.txt            # Python dependencies (KEEP)
```

## Files to Move

### From Root → scripts/testing/
- `test_live_positions.py`
- `test_trading_workflow.py`
- `test_trade_execution.py`
- `test_live_engine.py`
- `test_issue_audit.py`

### Rename Folder
- `ongoing_dev/` → `research/experiments/`

### Clean Up
- Remove duplicate README.md files (keep main one)
- Consolidate deployment documentation

## Benefits

1. **Clean Root Directory**
   - Only essential files (main.py, setup.py, README.md, config files)
   - Professional appearance

2. **Logical Organization**
   - All test scripts in one place
   - Clear separation of concerns
   - Easy to find files

3. **Better Developer Experience**
   - New developers can understand structure quickly
   - Clear where to add new files
   - Follows Python best practices

4. **Maintainability**
   - Related files grouped together
   - Easier to refactor
   - Clearer dependencies

## Migration Steps

1. Create new directories
2. Move test files to scripts/testing/
3. Rename ongoing_dev/ to research/experiments/
4. Update any import statements if needed
5. Update documentation references
6. Test that everything still works
7. Commit and deploy

## Impact Analysis

**Low Risk Changes**:
- Moving test_*.py files (not imported anywhere)
- Renaming ongoing_dev folder (not used in production)
- Creating new empty directories

**No Risk**:
- src/ structure unchanged (all production code stays)
- deploy/ unchanged (deployment not affected)
- tests/ unchanged (unit tests stay)
- main.py unchanged (entry point stays)

**Zero Downtime**: All changes are organizational only, no code changes needed.
