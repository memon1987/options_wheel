# Looker Studio Dashboard - Quick Start Guide

Get your trading monitoring dashboard up and running in 10 minutes.

---

## Prerequisites Checklist

✅ BigQuery dataset created: `options_wheel_logs`
✅ Log sink configured and active
✅ Enhanced logging deployed to Cloud Run
✅ Cloud Run service generating logs

---

## Quick Setup (3 Steps)

### Step 1: Create BigQuery Views (2 minutes)

Run the automated script:

```bash
cd /Users/zmemon/options_wheel-1
./scripts/create_bigquery_views.sh
```

This will:
- Wait for log tables to appear (if not ready yet)
- Create all 6 views automatically
- Verify views are working

**Or manually:**

```bash
# Check if tables exist
bq ls --project_id=gen-lang-client-0607444019 options_wheel_logs

# If you see cloud_run_logs_YYYYMMDD tables, create views:
bq query --use_legacy_sql=false < docs/bigquery_views.sql
```

---

### Step 2: Create Dashboard (5 minutes)

1. **Go to Looker Studio**
   https://lookerstudio.google.com

2. **Create New Report**
   - Click "Create" → "Report"
   - Select "BigQuery" connector
   - Authenticate with `zeshan@tkzmgroup.com`

3. **Connect to Data**
   - Project: `gen-lang-client-0607444019`
   - Dataset: `options_wheel_logs`
   - Table: `trades` (start here)
   - Click "ADD"

4. **Add Key Metrics (Drag & Drop)**

   **Scorecard 1:**
   - Metric: `Record Count`
   - Filter: `trade_date = TODAY()`
   - Label: "Trades Today"

   **Scorecard 2:**
   - Metric: Custom → `AVG(CAST(success AS NUMBER))`
   - Format: Percentage
   - Label: "Success Rate"

   **Scorecard 3:**
   - Metric: Custom → `SUM(premium * contracts * 100)`
   - Format: Currency
   - Label: "Premium Today"

5. **Add Time Series Chart**
   - Dimension: `trade_date`
   - Metric: `Record Count`
   - Date range: Last 30 days

6. **Add Recent Trades Table**
   - Dimensions: `timestamp`, `underlying`, `strategy`, `premium`, `success`
   - Sort: `timestamp` DESC
   - Limit: 20 rows

7. **Save Dashboard**
   - File → Rename: "Options Wheel - Trading Performance"
   - Click "Share" → Set to "Anyone with link can view"

---

### Step 3: Set Up Alerts (3 minutes)

1. **Daily Error Summary**
   - Share → Schedule email delivery
   - Frequency: Daily at 5 PM ET
   - Condition: If errors > 10
   - Recipients: Your email

2. **Critical Error Alert**
   - Create new schedule
   - Frequency: Hourly (9 AM - 4 PM ET)
   - Condition: If non-recoverable errors > 0
   - Recipients: Your email

---

## What You Get

### Trading Performance Dashboard
✅ Real-time trade count and success rate
✅ Daily premium collection tracking
✅ 30-day trend analysis
✅ Recent trades table

### Email Alerts
✅ Daily summary of trading activity
✅ Immediate notification of critical errors

---

## First Day Checklist

**Morning (9:00 AM ET)**
- [ ] Open dashboard
- [ ] Verify data is loading
- [ ] Check overnight activity

**Midday (12:00 PM ET)**
- [ ] Monitor trade execution
- [ ] Check success rate

**Evening (5:00 PM ET)**
- [ ] Review daily summary email
- [ ] Check total premium collected

---

## Common First-Time Issues

### "No data available"

**Solution:**
```bash
# Check if views exist
bq ls options_wheel_logs

# If no views shown, create them
bq query --use_legacy_sql=false < docs/bigquery_views.sql
```

### "Can't connect to BigQuery"

**Solution:**
- Sign out of Looker Studio
- Sign back in with `zeshan@tkzmgroup.com` (same as GCP)
- Try connecting again

### "Data is stale"

**Solution:**
- Click data source name
- Set "Data Freshness" to 15 minutes or 1 hour
- Refresh dashboard

---

## Next Steps

Once basic dashboard is working:

1. **Add More Pages**
   - Risk & Performance monitoring
   - Error tracking
   - Wheel cycle analysis

2. **Customize Metrics**
   - Add filters (symbol, date range)
   - Create custom calculations
   - Adjust refresh rates

3. **Share with Team**
   - Get dashboard URL
   - Share with stakeholders
   - Set up team alerts

---

## Full Documentation

- **Detailed Setup**: `docs/LOOKER_STUDIO_SETUP.md`
- **User Guide**: `docs/LOOKER_STUDIO_DASHBOARD.md`
- **BigQuery Views**: `docs/bigquery_views.sql`

---

## Support Quick Links

- **Looker Studio**: https://lookerstudio.google.com
- **BigQuery Console**: https://console.cloud.google.com/bigquery?project=gen-lang-client-0607444019
- **Cloud Run Logs**: https://console.cloud.google.com/run?project=gen-lang-client-0607444019

---

## Cost

**Total**: $0-5/month
- Looker Studio: FREE
- BigQuery storage: ~$0.40
- BigQuery queries: $0-5 (within free tier)

---

## Troubleshooting One-Liner

```bash
# Full health check
echo "Tables:" && bq ls options_wheel_logs && \
echo "Views test:" && bq query --use_legacy_sql=false "SELECT COUNT(*) FROM \`gen-lang-client-0607444019.options_wheel_logs.trades\`"
```

---

**Time to Dashboard: 10 minutes**
**Maintenance: 5 minutes/week**
**Value: Real-time trading insights** 📊

Get started now! →
