# Production Configuration Summary

## Options Wheel Strategy - Cloud Deployment Configuration

### Key Strategy Parameters

**Options Selection:**
- Target DTE: 7 days (rapid theta decay)
- Put Delta Range: 0.10-0.20 (10-20% assignment probability)
- Call Delta Range: 0.10-0.20 (conservative covered calls)
- Minimum Premiums: $0.50 puts, $0.30 calls

**Stock Universe (Cloud-Optimized):**
- Price Range: $30-$400 (increased from $20 minimum for better liquidity)
- Volume Requirement: 2M shares daily (increased from 1M for cloud execution)
- Quality Stocks: AAPL, MSFT, GOOGL, AMZN, TSLA, NVDA, AMD, QQQ, SPY, IWM

**Position Sizing (Conservative for Cloud):**
- Max Exposure per Ticker: $25,000 (reduced from $50K for safety)
- Max Positions per Stock: 1 contract
- Max Total Positions: 10
- Portfolio Allocation: 80% max, 20% cash reserve

### Risk Management

**Gap Risk Controls:**
- Quality Filter: Max 2% historical gaps
- Execution Filter: 2.0% hard stop threshold
- Pre-market Filter: 2% gap triggers 15min delay
- Historical Volatility: 40% maximum

**Stop Loss Strategy:**
- Puts: No stop losses (take assignment on quality stocks)
- Calls: 50% stop loss with 1.5x multiplier for time decay
- Profit Target: 50% for early closure

### Cloud-Specific Features

**Execution Schedule:**
- Morning Scan: 9:00 AM ET (market open)
- Midday Execution: 12:00 PM ET
- Afternoon Check: 3:00 PM ET (before close)

**Monitoring:**
- 15-minute position checks during market hours
- Cloud logging enabled for audit trails
- 5-minute execution timeout for Cloud Run
- Performance metrics tracking

**Security:**
- Paper trading enabled by default
- Alpaca API credentials in Google Secret Manager
- OIDC authentication for scheduled jobs
- Proper IAM roles and permissions

### Safety Features

1. **Paper Trading Default**: All trades execute in paper mode
2. **Conservative Sizing**: Reduced position sizes for cloud deployment
3. **Enhanced Gap Protection**: Multiple layers of gap risk management
4. **Quality Stock Universe**: Only liquid, established companies
5. **Comprehensive Logging**: Full audit trail in Google Cloud Logging

### Next Steps for Live Trading

1. **Thoroughly test in paper mode** for several weeks
2. **Monitor gap detection accuracy** during volatile periods
3. **Verify all scheduled jobs execute correctly**
4. **Review performance metrics and adjust as needed**
5. **When ready for live trading**: Change `paper_trading: false` in settings.yaml

---

*Last Updated: Production deployment complete*
*Status: Ready for paper trading validation*