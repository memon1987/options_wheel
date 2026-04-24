# Looker Studio Dashboard - User Guide

Quick reference guide for using the Options Wheel Trading Strategy monitoring dashboards.

---

## Dashboard Access

### URLs
- **Trading Performance**: [Fill in after creation]
- **Risk & Performance**: [Fill in after creation]
- **Errors & System Health**: [Fill in after creation]

### Login
Use your Google account: `zeshan@tkzmgroup.com`

---

## Dashboard 1: Trading Performance

### Purpose
Real-time monitoring of trade execution, success rates, and premium collection.

### Key Metrics

**Total Trades Today**
- What it shows: Number of options contracts sold today
- Normal range: 0-5 trades per day
- Alert if: > 10 trades (unusually high activity)

**Success Rate**
- What it shows: Percentage of orders successfully filled
- Normal range: 80-100%
- Alert if: < 70% (order rejection issues)

**Premium Collected Today**
- What it shows: Total premium income from all trades
- Calculated as: `SUM(premium × contracts × 100)`
- Normal range: $500-$3,000 per day

**Symbols Traded**
- What it shows: Number of unique underlying stocks traded
- Normal range: 1-4 symbols per day
- Alert if: > 6 (over-diversification)

### Charts

**Daily Trade Volume (Last 30 Days)**
- Shows: Trade count trend over time
- Lines: Blue = puts, Orange = calls
- Use for: Identifying trading patterns and frequency

**Premium Collection Trend**
- Shows: Daily and cumulative premium collected
- Bars: Daily premium
- Line: Running total
- Use for: Tracking monthly performance against goals

**Recent Trades Table**
- Shows: Last 20 executed trades
- Use for: Verifying recent activity and order details
- Tip: Click column headers to sort

**Premium by Symbol**
- Shows: Which stocks generate most premium
- Use for: Identifying most profitable underlyings

### How to Use

1. **Morning Check (9:30 AM ET)**
   - Verify system is running (check if new trades appear)
   - Review overnight gap risk alerts

2. **Midday Check (12:00 PM ET)**
   - Monitor trade execution success rate
   - Check premium collected vs daily goal

3. **End of Day (4:00 PM ET)**
   - Review total daily activity
   - Compare to weekly/monthly trends

### Filters

- **Date Range**: Default is last 7 days, adjust as needed
- **Symbol**: Filter to specific underlying stock
- **Strategy**: Filter to puts or calls only

---

## Dashboard 2: Risk & Performance

### Purpose
Monitor gap risk, trade blocking, and system performance metrics.

### Section 1: Gap Risk Analysis

**Trades Blocked Today**
- What it shows: Number of potential trades blocked due to overnight gaps
- Normal range: 0-2 per day
- Alert if: > 5 (high market volatility)

**Top Symbols Blocked by Gap Risk**
- Shows: Which stocks get filtered out most often
- Use for: Understanding which stocks are too volatile
- Action: Consider removing high-risk symbols from universe

**Gap Blocks Over Time**
- Shows: Trend of gap-related trade blocking
- Use for: Identifying periods of high volatility
- Spike means: Market experiencing unusual overnight moves

**Gap % vs Risk Score Scatter**
- Shows: Relationship between gap size and risk score
- Upper right quadrant: Highest risk stocks
- Use for: Validating gap detection algorithm

### Section 2: Performance Metrics

**Average Scan Duration**
- What it shows: How long market scans take
- Normal range: 2-5 seconds
- Alert if: > 10 seconds (system slowdown)

**Scan Duration Over Time**
- Shows: Performance trend with min/max bands
- Spike means: Possible API rate limiting or data issues
- Trend up: System degradation, needs investigation

**Performance Metrics Summary**
- Shows: All timing metrics (scan, execution, cycle duration)
- Use for: Identifying performance bottlenecks

### How to Use

1. **Daily Volatility Check (9:00 AM ET)**
   - Review gap blocks from overnight
   - Check which symbols were filtered

2. **Weekly Performance Review**
   - Compare scan durations week-over-week
   - Identify any degradation trends

3. **Monthly Risk Analysis**
   - Review which symbols get blocked most
   - Adjust gap thresholds if needed

---

## Dashboard 3: Errors & System Health

### Purpose
Monitor system errors, component health, and completed wheel cycles.

### Section 1: Error Monitoring

**Total Errors Today**
- What it shows: Count of all logged errors
- Normal range: 0-10 per day (mostly API rate limits)
- Alert if: > 20 (systematic issue)

**Critical Errors (Non-recoverable)**
- What it shows: Errors that require manual intervention
- Normal range: 0
- Alert if: > 0 (immediate action required)

**Errors by Component**
- Shows: Which parts of system have most errors
- Components:
  - `put_seller`: Put selling logic
  - `call_seller`: Call selling logic
  - `gap_detector`: Gap risk detection
  - `alpaca_client`: API communication
  - `market_data`: Data fetching
  - `wheel_engine`: Main strategy coordinator

**Recent Errors Table**
- Shows: Last 20 errors with details
- Red rows: Non-recoverable errors
- Use for: Debugging and troubleshooting

**Error Rate Over Time**
- Shows: Error frequency trends
- Spike means: Possible system issue or API problems
- Use for: Identifying error patterns

### Section 2: Wheel Cycle Performance

**Completed Cycles This Month**
- What it shows: Number of complete wheel cycles (put → stock → call → sold)
- Normal range: 0-3 per month (depends on assignments)
- Higher is better: More cycles = more profit opportunities

**Average Cycle Duration**
- What it shows: How long each wheel cycle takes (in days)
- Normal range: 30-60 days
- Shorter is better: Faster capital rotation

**Average Total Return per Cycle**
- What it shows: Profit per completed cycle
- Includes: Premium + capital gains
- Use for: Evaluating strategy effectiveness

**Recent Completed Wheel Cycles**
- Shows: Details of each completed cycle
- Green rows: Profitable cycles
- Use for: Understanding which symbols work best

**Returns by Symbol**
- Shows: Total profit by underlying stock
- Use for: Identifying most profitable stocks for wheel strategy

### How to Use

1. **Morning Health Check (9:00 AM ET)**
   - Verify no critical errors overnight
   - Check error rate is normal

2. **Error Review (As needed)**
   - Investigate any critical errors immediately
   - Review non-critical errors weekly

3. **Monthly Strategy Review**
   - Analyze completed wheel cycles
   - Calculate average returns vs goals
   - Identify best-performing symbols

---

## Alert Interpretations

### "High Error Rate" Email

**What it means**: System logged > 10 errors in last 24 hours

**Possible causes**:
- Alpaca API rate limiting
- Network connectivity issues
- Bug in trading logic

**Action**:
1. Check error dashboard for details
2. Review error types (recoverable vs non-recoverable)
3. If all recoverable and API-related: Monitor, likely temporary
4. If non-recoverable: Investigate immediately

### "Gap Risk Blocks Alert" Email

**What it means**: > 3 trades blocked today due to gap risk

**Possible causes**:
- High market volatility
- Major news events affecting multiple stocks
- Gap thresholds too conservative

**Action**:
1. Check gap risk dashboard
2. Verify market conditions (check VIX, news)
3. If temporary volatility: No action needed
4. If persistent: Consider adjusting gap thresholds

### "Critical Error Alert" Email

**What it means**: Non-recoverable error detected

**Possible causes**:
- Code bug
- API authentication failure
- Missing required data

**Action**:
1. Check error details immediately
2. Review code component with error
3. Check Cloud Run logs for stack trace
4. Fix issue and redeploy if needed

---

## Common Questions

### Q: Why don't I see any data?

**A**: Either:
1. Views not created yet (run `bq query < docs/bigquery_views.sql`)
2. No logs exported yet (wait 5-10 minutes after first execution)
3. Filters are too restrictive (reset to default date range)

### Q: Data doesn't refresh automatically

**A**: Check data source freshness settings:
1. Resource → Manage added data sources
2. Select data source
3. Verify "Data Freshness" is set (e.g., 1 hour)

### Q: Success rate seems low

**A**: Check:
1. Market hours (orders outside hours will fail)
2. Alpaca subscription level (paper vs live)
3. Recent error logs for "order rejected" messages

### Q: No completed wheel cycles shown

**A**: This is normal if:
1. Strategy recently deployed (cycles take 30-60 days)
2. No put assignments yet (need stock to be assigned first)
3. Calls haven't been assigned yet (need stock price above strike)

### Q: Premium numbers seem off

**A**: Verify:
1. Currency format is set correctly
2. Calculation formula: `premium × contracts × 100`
3. Date range filter (might be showing different period)

---

## Dashboard Customization

### Adding Custom Metrics

1. Click on any chart
2. Click **"Add a metric"**
3. Create calculated field:
   ```
   Name: Win Rate
   Formula: SUM(IF(success, 1, 0)) / COUNT(*)
   Format: Percentage
   ```

### Changing Date Ranges

1. Click date range control (top right)
2. Select:
   - Last 7 days (default)
   - Last 30 days
   - Last 90 days
   - Custom range
   - Comparison period (e.g., vs previous week)

### Exporting Data

1. Click on any chart
2. Click **"⋮"** (more options)
3. Select **"Download"**
4. Choose format: CSV, Excel, PDF

### Creating Annotations

Mark significant events on charts:

1. Click on chart
2. Click date where event occurred
3. Click **"Add annotation"**
4. Add note (e.g., "Strategy parameter changed")
5. Annotation appears on all charts with same date dimension

---

## Best Practices

### Daily Monitoring Routine

**9:00 AM ET - Pre-Market Check**
- [ ] Review overnight gap alerts
- [ ] Check system error count
- [ ] Verify last scan completed successfully

**12:00 PM ET - Midday Check**
- [ ] Monitor active trades
- [ ] Check success rate
- [ ] Review premium collected vs daily goal

**4:00 PM ET - End of Day Review**
- [ ] Review total daily activity
- [ ] Check for any critical errors
- [ ] Compare to weekly trend

### Weekly Review Checklist

- [ ] Analyze trade success rate trend
- [ ] Review gap-blocked symbols
- [ ] Check performance metric trends
- [ ] Investigate any error spikes
- [ ] Update alert thresholds if needed

### Monthly Review Checklist

- [ ] Calculate total returns
- [ ] Review completed wheel cycles
- [ ] Analyze best-performing symbols
- [ ] Evaluate strategy effectiveness
- [ ] Adjust trading parameters if needed

---

## Troubleshooting Tips

### Slow Dashboard Loading

1. Reduce date range (use last 7 days instead of 30)
2. Increase data freshness interval
3. Limit table rows (20 instead of 100)
4. Remove unused breakout dimensions

### Incorrect Timezone

1. File → Report settings
2. Set timezone: America/New_York (ET)
3. Refresh dashboard

### Missing Recent Data

1. Check data freshness: Resource → Manage added data sources
2. Verify Cloud Run is running: `gcloud run services describe options-wheel-strategy`
3. Check log export: `bq ls options_wheel_logs`

---

## Support

For issues or questions:

1. **Dashboard issues**: Check [Looker Studio Help](https://support.google.com/looker-studio)
2. **Data issues**: Review logs in Cloud Logging
3. **Strategy questions**: See main README.md

---

## Version History

- **v1.0** (2025-10-01): Initial dashboard creation
- **v1.1** (TBD): Added wheel cycle tracking
- **v1.2** (TBD): Enhanced alert configuration

---

## Appendix: Metric Definitions

**Premium Collected**
- Formula: `premium × contracts × 100`
- Why ×100: Each contract = 100 shares
- Example: $0.74 premium × 2 contracts × 100 = $148

**Success Rate**
- Formula: `successful trades / total trades`
- Considers: Only filled orders, not rejected

**Wheel Cycle**
- Definition: Complete sequence: Sell put → Assignment → Sell call → Call away
- Duration: Days from first put sale to final call assignment
- Return: Total premium + capital gain

**Gap Risk Score**
- Range: 0.0 (low risk) to 1.0 (high risk)
- Components: Historical gap frequency + volatility + current gap
- Threshold: Stocks > 0.6 are filtered out

**Trade Collateral**
- For puts: `strike price × 100 × contracts`
- For calls: Shares must be owned (no collateral needed)
- Example: $155 strike, 2 contracts = $31,000 collateral

---

Last updated: 2025-10-01
