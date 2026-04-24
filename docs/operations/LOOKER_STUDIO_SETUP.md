# Looker Studio Dashboard Setup Guide

Complete guide for creating real-time monitoring dashboards for the Options Wheel Trading Strategy.

---

## Prerequisites

✅ BigQuery dataset created: `options_wheel_logs`
✅ Log sink configured and exporting
✅ Enhanced logging deployed to Cloud Run
✅ 6 BigQuery views created (see below)

---

## Step 1: Create BigQuery Views (One-time Setup)

### Verify Tables Exist

Wait 5-10 minutes after first logs generated, then check:

```bash
bq ls --project_id=gen-lang-client-0607444019 options_wheel_logs
```

You should see tables like: `cloud_run_logs_20251001`

### Create All 6 Views

Execute the views SQL file:

```bash
export PATH="/Users/zmemon/google-cloud-sdk/bin:$PATH"
bq query --use_legacy_sql=false < docs/bigquery_views.sql
```

This creates:
1. **trades** - All trading activity (puts/calls sold)
2. **risk_events** - Gap detection and trade blocking
3. **performance_metrics** - Timing and efficiency metrics
4. **errors** - Component-level error tracking
5. **system_events** - Strategy cycles and scheduled jobs
6. **position_updates** - Wheel state transitions and cycle completion

### Verify Views Created

```bash
bq ls --project_id=gen-lang-client-0607444019 options_wheel_logs
```

Should now show 6 views + daily log tables.

---

## Step 2: Access Looker Studio

1. Go to: https://lookerstudio.google.com
2. Sign in with: `zeshan@tkzmgroup.com` (your GCP account)
3. Click **"Create"** → **"Report"**

---

## Step 3: Connect to BigQuery

### Connect First Data Source (Trades)

1. In the data source panel, click **"BigQuery"**
2. Select:
   - **My Projects** tab
   - Project: `gen-lang-client-0607444019`
   - Dataset: `options_wheel_logs`
   - Table: **`trades`** (VIEW)
3. Click **"ADD"**

The schema will auto-detect all fields from the view.

### Configure Data Freshness

1. Click on the data source name (top left)
2. Under **"Data Freshness"**:
   - Set to: **"1 hour"** (balance between real-time and query costs)
   - For critical monitoring, use **"15 minutes"**

---

## Step 4: Create Dashboard 1 - Trading Performance

### Page Layout

Create a single page with the following components:

### Top Row: Key Metrics (Scorecards)

**Scorecard 1: Total Trades Today**
- Metric: `Record Count`
- Filter: `trade_date = TODAY()`
- Style: Large number, green background
- Label: "Trades Today"

**Scorecard 2: Success Rate**
- Metric: Custom field
  ```
  AVG(CAST(success AS NUMBER))
  ```
- Format: Percentage (0.00%)
- Filter: `trade_date = TODAY()`
- Style: Large number, blue background
- Label: "Success Rate"

**Scorecard 3: Total Premium Collected (Today)**
- Metric: Custom field
  ```
  SUM(premium * contracts * 100)
  ```
- Format: Currency ($#,##0.00)
- Filter: `trade_date = TODAY()`
- Style: Large number, gold background
- Label: "Premium Collected Today"

**Scorecard 4: Active Positions**
- Metric: `COUNT(DISTINCT underlying)`
- Filter: `trade_date = TODAY()` AND `success = true`
- Style: Large number, purple background
- Label: "Symbols Traded"

### Middle Section: Time Series

**Chart: Daily Trade Volume (Last 30 Days)**
- Chart type: Time series (line chart)
- Date Range Dimension: `trade_date`
- Metric: `Record Count`
- Date range: Last 30 days
- Breakout dimension: `strategy` (shows puts vs calls as separate lines)
- Style: Smooth lines, show data labels

**Chart: Premium Collection Trend**
- Chart type: Combo chart (line + bars)
- Date Range Dimension: `trade_date`
- Metric 1 (bars): `SUM(premium * contracts * 100)` - Daily premium
- Metric 2 (line): Running total (use calculated field)
- Date range: Last 30 days

### Bottom Section: Data Tables

**Table: Recent Trades (Last 20)**
- Dimensions:
  - `timestamp` (formatted as datetime)
  - `underlying`
  - `strategy`
  - `strike_price` (format: #,##0.00)
  - `premium` (format: $0.00)
  - `contracts`
  - `success` (conditional formatting: green checkmark if true)
  - `order_id`
- Sort: `timestamp` DESC
- Rows per page: 20
- Enable search/filter

**Chart: Premium by Symbol (Bar Chart)**
- Dimension: `underlying`
- Metric: `SUM(premium * contracts * 100)`
- Sort: Descending
- Date range: Last 7 days
- Style: Horizontal bars, color by value

---

## Step 5: Create Dashboard 2 - Risk & Performance

### Add New Page

Click **"Page"** → **"New Page"** → Name: "Risk & Performance"

### Add Data Sources

1. Click **"Resource"** → **"Manage added data sources"**
2. Add: `risk_events` (BigQuery view)
3. Add: `performance_metrics` (BigQuery view)

### Section 1: Gap Risk Analysis

**Scorecard: Trades Blocked Today**
- Data source: `risk_events`
- Metric: `Record Count`
- Filter: `event_date = TODAY()` AND `action_taken = 'trade_blocked'`
- Style: Red if > 5, yellow if > 2, green otherwise
- Use conditional formatting

**Table: Top Symbols Blocked by Gap Risk**
- Data source: `risk_events`
- Dimensions: `symbol`, `AVG(gap_percent)`, `AVG(gap_risk_score)`, `COUNT(*) as blocked_count`
- Filter: `action_taken = 'trade_blocked'`
- Sort: `blocked_count` DESC
- Date range: Last 30 days

**Chart: Gap Blocks Over Time**
- Data source: `risk_events`
- Chart type: Time series
- Date dimension: `event_date`
- Metric: `Record Count`
- Filter: `action_taken = 'trade_blocked'`
- Breakout: `symbol` (see which stocks get blocked most)
- Date range: Last 30 days

**Scatter Chart: Gap % vs Risk Score**
- Data source: `risk_events`
- X-axis: `gap_percent`
- Y-axis: `gap_risk_score`
- Bubble dimension: `symbol`
- Filter: Last 7 days
- Shows relationship between gap size and risk score

### Section 2: Performance Metrics

**Scorecard: Average Scan Duration**
- Data source: `performance_metrics`
- Metric: `AVG(metric_value)`
- Filter: `metric_name = 'market_scan_duration'` AND `metric_date >= CURRENT_DATE() - 7`
- Format: 0.00 seconds
- Style: Show trend sparkline

**Chart: Scan Duration Over Time**
- Data source: `performance_metrics`
- Chart type: Time series with trend line
- Date dimension: `metric_date`
- Metric: `AVG(metric_value)`
- Filter: `metric_name = 'market_scan_duration'`
- Date range: Last 30 days
- Show min/max bands

**Table: Performance Metrics Summary**
- Data source: `performance_metrics`
- Dimensions: `metric_name`, `metric_unit`
- Metrics: `AVG(metric_value)`, `MIN(metric_value)`, `MAX(metric_value)`
- Filter: Last 7 days
- Sort: `metric_name`

---

## Step 6: Create Dashboard 3 - Errors & Wheel Cycles

### Add New Page

Click **"Page"** → **"New Page"** → Name: "Errors & System Health"

### Add Data Sources

1. Add: `errors` (BigQuery view)
2. Add: `system_events` (BigQuery view)
3. Add: `position_updates` (BigQuery view)

### Section 1: Error Monitoring

**Scorecard: Total Errors Today**
- Data source: `errors`
- Metric: `Record Count`
- Filter: `error_date = TODAY()`
- Conditional formatting: Red if > 10, yellow if > 5

**Scorecard: Critical Errors (Non-recoverable)**
- Data source: `errors`
- Metric: `Record Count`
- Filter: `error_date = TODAY()` AND `recoverable = false`
- Style: Red background, alert icon

**Bar Chart: Errors by Component**
- Data source: `errors`
- Dimension: `component`
- Metric: `Record Count`
- Breakout dimension: `error_type`
- Sort: Descending
- Date range: Last 7 days
- Stacked bars

**Table: Recent Errors**
- Data source: `errors`
- Dimensions: `timestamp`, `component`, `error_type`, `error_message`, `recoverable`, `symbol`
- Sort: `timestamp` DESC
- Rows: 20
- Conditional formatting: Red row if not recoverable

**Chart: Error Rate Over Time**
- Data source: `errors`
- Chart type: Time series
- Date dimension: `error_date`
- Metric: `Record Count`
- Breakout: `component`
- Date range: Last 30 days

### Section 2: Wheel Cycle Performance

**Scorecard: Completed Cycles This Month**
- Data source: `position_updates`
- Metric: `Record Count`
- Filter: `wheel_cycle_completed = true` AND `update_date >= CURRENT_DATE() - 30`
- Style: Green, trophy icon

**Scorecard: Average Cycle Duration**
- Data source: `position_updates`
- Metric: `AVG(cycle_duration_days)`
- Filter: `wheel_cycle_completed = true` AND `update_date >= CURRENT_DATE() - 90`
- Format: 0 days

**Scorecard: Average Total Return per Cycle**
- Data source: `position_updates`
- Metric: `AVG(total_return)`
- Filter: `wheel_cycle_completed = true` AND `update_date >= CURRENT_DATE() - 90`
- Format: Currency

**Table: Recent Completed Wheel Cycles**
- Data source: `position_updates`
- Dimensions: `update_date`, `symbol`, `phase_before`, `phase_after`, `cycle_duration_days`, `total_return`, `capital_gain`
- Filter: `wheel_cycle_completed = true`
- Sort: `update_date` DESC
- Rows: 20
- Conditional formatting: Green if total_return > 0

**Bar Chart: Returns by Symbol**
- Data source: `position_updates`
- Dimension: `symbol`
- Metric: `SUM(total_return)`
- Filter: `wheel_cycle_completed = true` AND `update_date >= CURRENT_DATE() - 90`
- Sort: Descending
- Style: Color by value (gradient from red to green)

---

## Step 7: Add Global Filters

Add these filters to all pages for easy data exploration:

1. **Date Range Control**
   - Type: Date range picker
   - Default: Last 7 days
   - Position: Top right of each page

2. **Symbol Filter**
   - Type: Drop-down list
   - Field: `symbol` or `underlying` (depending on view)
   - Allow multiple selections
   - Include "All" option

3. **Strategy Filter** (for trading dashboard)
   - Type: Drop-down list
   - Field: `strategy`
   - Options: sell_put, sell_call
   - Default: All

---

## Step 8: Configure Email Alerts

### Alert 1: High Error Rate

1. Click **"Share"** → **"Schedule email delivery"**
2. Create new schedule:
   - Name: "Daily Error Summary"
   - Frequency: Daily at 5:00 PM ET
   - Condition: If `error_count > 10` in last 24 hours
   - Recipients: Your email
   - Include: Error dashboard page

### Alert 2: Gap Risk Blocks

1. Create alert:
   - Name: "Gap Risk Blocks Alert"
   - Frequency: Daily at 3:30 PM ET (after market close)
   - Condition: If `blocked_trades > 3` today
   - Recipients: Your email
   - Include: Risk analysis page

### Alert 3: Critical System Errors

1. Create alert:
   - Name: "Critical Error Alert"
   - Frequency: Every 1 hour (during market hours)
   - Condition: If non-recoverable errors > 0
   - Recipients: Your email + SMS (via email-to-SMS)
   - Include: Error details

---

## Step 9: Optimize for Mobile

1. Click **"View"** → **"Mobile layout"**
2. For each page:
   - Rearrange components vertically
   - Increase font sizes for scorecards
   - Stack charts (1 per row)
   - Reduce table columns (show only key fields)
3. Test on phone: Click **"View"** → **"View in mobile"**

---

## Step 10: Share Dashboard

### Option 1: View-Only Link

1. Click **"Share"**
2. Set access: **"Anyone with the link can view"**
3. Copy link
4. Share with stakeholders

### Option 2: Email Report

1. Click **"Share"** → **"Schedule email delivery"**
2. Set daily/weekly schedule
3. Add recipients
4. Include PDF or link

### Option 3: Embed in Website (Optional)

1. Click **"Share"** → **"Embed report"**
2. Copy iframe code
3. Add to internal monitoring page

---

## Step 11: Set Data Refresh Schedule

For each data source:

1. Click **"Resource"** → **"Manage added data sources"**
2. Select data source (e.g., `trades`)
3. Set **"Data Freshness"**:
   - **Critical metrics (errors, system_events)**: 15 minutes
   - **Trading data (trades, risk_events)**: 1 hour
   - **Analytics (performance_metrics, position_updates)**: 4 hours

**Cost vs Freshness Trade-off:**
- 15 min refresh = ~96 queries/day per dashboard viewer
- 1 hour refresh = ~24 queries/day per dashboard viewer
- 4 hour refresh = ~6 queries/day per dashboard viewer

With partitioned tables, each query scans ~10-50MB, so you'll stay within BigQuery free tier (1TB/month).

---

## Troubleshooting

### Issue: "No data available"

**Cause**: Views not created or no logs exported yet

**Solution**:
```bash
# Check if tables exist
bq ls options_wheel_logs

# If no tables, wait 5-10 minutes for log export
# Then create views
bq query --use_legacy_sql=false < docs/bigquery_views.sql
```

### Issue: "Access Denied" when connecting to BigQuery

**Cause**: Not using correct GCP account

**Solution**:
1. Sign out of Looker Studio
2. Sign in with `zeshan@tkzmgroup.com` (same account as GCP)
3. Reconnect data sources

### Issue: Dashboard is slow

**Cause**: Querying too much data without filters

**Solution**:
1. Add date range filters (default to last 7 days)
2. Reduce table row limits
3. Increase data freshness interval
4. Use aggregated metrics instead of raw data

### Issue: Metrics don't match expected values

**Cause**: Time zone differences or filter issues

**Solution**:
1. Check report timezone: **"File"** → **"Report settings"** → Set to "America/New_York"
2. Verify filters are applied correctly
3. Check date range selector

---

## Dashboard URLs (Fill in after creation)

Once dashboards are created, add URLs here:

- **Trading Performance**: https://lookerstudio.google.com/reporting/[REPORT_ID_1]
- **Risk & Performance**: https://lookerstudio.google.com/reporting/[REPORT_ID_2]
- **Errors & System Health**: https://lookerstudio.google.com/reporting/[REPORT_ID_3]

---

## Maintenance

### Weekly
- Review alert thresholds (adjust based on actual patterns)
- Check for new error types
- Verify data completeness

### Monthly
- Review BigQuery costs (should be $0-5/month)
- Clean up old partitioned tables if needed (auto-expires after 90 days)
- Update dashboard layout based on usage feedback

### Quarterly
- Add new metrics as strategy evolves
- Optimize slow-loading charts
- Archive old completed wheel cycles data

---

## Next Steps

1. ✅ Create all 3 dashboards
2. ⏳ Run for 1 week to collect baseline data
3. ⏳ Tune alert thresholds based on actual patterns
4. ⏳ Share with stakeholders and get feedback
5. ⏳ Add advanced features (annotations, custom calculations)

---

## Additional Resources

- **Looker Studio Help**: https://support.google.com/looker-studio
- **BigQuery Documentation**: https://cloud.google.com/bigquery/docs
- **Community Gallery**: https://lookerstudio.google.com/gallery (for template ideas)

---

## Cost Monitoring

Track your actual BigQuery costs:

```bash
# Check BigQuery usage
bq ls -j --project_id=gen-lang-client-0607444019 --max_results=100

# View storage costs
gcloud alpha billing accounts list
```

Expected monthly costs with 3 dashboards + 3 viewers:
- Storage: $0.40 (2GB partitioned logs)
- Queries: $0-5 (well within 1TB free tier)
- **Total: $0-5/month**
