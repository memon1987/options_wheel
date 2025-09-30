# Ongoing Development

This folder contains experimental and development scripts that are not part of the main production codebase.

## Monday-Only Backtesting

### Scripts
- `monday_only_backtesting/monday_only_backtest.py` - Core Monday-only strategy backtesting engine
- `monday_only_backtesting/trade_by_trade_analysis.py` - Detailed trade analysis and walkthrough

### Purpose
Experimental backtesting approach that only enters positions on Mondays targeting Friday expirations (5 DTE).

### Key Findings
- **Execution Rate**: 30.8% (4 trades out of 13 possible Mondays)
- **Win Rate**: 75% but overall negative return (-355.9%)
- **Assignment Risk**: One large assignment loss dominated performance
- **Strategy Risk**: 5-day expiration provides limited recovery time

### Usage
```bash
# Run the Monday-only backtest
python ongoing_dev/monday_only_backtesting/monday_only_backtest.py

# Generate detailed trade analysis
python ongoing_dev/monday_only_backtesting/trade_by_trade_analysis.py
```

### Recommendations
1. Consider wider OTM strikes (10-15% buffer)
2. Implement profit-taking rules (close at 50% profit)
3. Evaluate 7-10 DTE options for more recovery time
4. Compare with daily entry approach for opportunity frequency