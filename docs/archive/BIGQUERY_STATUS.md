# BigQuery Logging Setup Status

## ✅ Completed Steps

### 1. BigQuery Dataset Created
```bash
Dataset: gen-lang-client-0607444019:options_wheel_logs
Location: us-central1
Status: ✅ Active
```

### 2. Cloud Logging Sink Configured
```bash
Sink Name: options-wheel-logs
Destination: bigquery.googleapis.com/projects/gen-lang-client-0607444019/datasets/options_wheel_logs
Filter: resource.type="cloud_run_revision"
        resource.labels.service_name="options-wheel-strategy"
        jsonPayload.event_category=*
Status: ✅ Active
```

### 3. IAM Permissions Granted
```bash
Service Account: service-799970961417@gcp-sa-logging.iam.gserviceaccount.com
Role: roles/bigquery.dataEditor
Status: ✅ Granted
```

### 4. Enhanced Logging Code Deployed
```bash
Commits:
  - d26b422: Phase 1 core logging (put_seller, wheel_engine, gap_detector, cloud_run_server)
  - 5f0169c: Call seller & state transitions (call_seller, wheel_state_manager)

Build Status:
  - Build 3e29d3e1: SUCCESS ✅
  - Build 0eddf335: WORKING 🔄 (includes all enhanced logging)
```

## 🔄 Pending - Waiting for Logs to Flow

Once Build 0eddf335 completes and logs start flowing with `event_category`, we need to:

### 5. Create BigQuery Views

Run the SQL from `docs/bigquery_views.sql` to create 6 analytics views:

```bash
# Execute view creation (run when logs exist)
bq query --use_legacy_sql=false < docs/bigquery_views.sql
```

Views to create:
1. ✅ `trades` - All trading activity (puts/calls)
2. ✅ `risk_events` - Gap detection and blocking
3. ✅ `performance_metrics` - Timing and efficiency
4. ✅ `errors` - Error tracking by component
5. ✅ `system_events` - Strategy cycles and jobs
6. ✅ `position_updates` - Wheel state transitions

### 6. Verify Log Flow

Check that logs are being exported to BigQuery:

```bash
# Check for tables (should see cloud_run_logs_YYYYMMDD)
bq ls options_wheel_logs

# Check row count
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) as log_count FROM \`gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*\`"

# Sample enhanced logs
bq query --use_legacy_sql=false \
  "SELECT
    timestamp,
    jsonPayload.event_category,
    jsonPayload.event_type,
    jsonPayload.symbol
  FROM \`gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*\`
  WHERE jsonPayload.event_category IS NOT NULL
  LIMIT 10"
```

## 📊 Example Analytics Queries (Once Views Created)

### Trade Performance by Symbol
```sql
SELECT
  underlying,
  strategy,
  COUNT(*) as total_trades,
  SUM(CAST(success AS INT64)) as successful_trades,
  AVG(premium) as avg_premium,
  SUM(premium * contracts * 100) as total_premium_collected
FROM `gen-lang-client-0607444019.options_wheel_logs.trades`
WHERE trade_date >= CURRENT_DATE() - 30
GROUP BY underlying, strategy
ORDER BY total_premium_collected DESC;
```

### Complete Wheel Cycles
```sql
SELECT
  symbol,
  event_type,
  phase_before,
  phase_after,
  shares,
  capital_gain,
  total_return,
  cycle_duration_days,
  update_date
FROM `gen-lang-client-0607444019.options_wheel_logs.position_updates`
WHERE wheel_cycle_completed = true
ORDER BY update_date DESC;
```

### Gap Risk Analysis
```sql
SELECT
  symbol,
  COUNT(*) as blocked_count,
  AVG(gap_percent) as avg_gap_percent,
  AVG(gap_risk_score) as avg_risk_score
FROM `gen-lang-client-0607444019.options_wheel_logs.risk_events`
WHERE action_taken = 'trade_blocked'
GROUP BY symbol
ORDER BY blocked_count DESC;
```

### Performance Metrics
```sql
SELECT
  metric_name,
  DATE(metric_date) as date,
  AVG(metric_value) as avg_value,
  MIN(metric_value) as min_value,
  MAX(metric_value) as max_value,
  metric_unit
FROM `gen-lang-client-0607444019.options_wheel_logs.performance_metrics`
WHERE metric_date >= CURRENT_DATE() - 7
GROUP BY metric_name, date, metric_unit
ORDER BY date DESC, metric_name;
```

### Error Rate by Component
```sql
SELECT
  component,
  error_type,
  COUNT(*) as error_count,
  SUM(CAST(recoverable AS INT64)) as recoverable_errors,
  ARRAY_AGG(DISTINCT error_message LIMIT 5) as sample_messages
FROM `gen-lang-client-0607444019.options_wheel_logs.errors`
WHERE error_date >= CURRENT_DATE() - 7
GROUP BY component, error_type
ORDER BY error_count DESC;
```

## 🎯 Next Actions

1. **Wait for Build 0eddf335 to complete**
   - Check: `gcloud builds list --limit=1`

2. **Trigger test scan to generate logs**
   - Run: `gcloud scheduler jobs run morning-market-scan --location=us-central1`

3. **Wait 5-10 minutes for logs to export to BigQuery**
   - Logs are exported in batches, not real-time

4. **Verify table exists**
   - Run: `bq ls options_wheel_logs`
   - Should see: `cloud_run_logs_YYYYMMDD`

5. **Create BigQuery views**
   - Run: `bq query --use_legacy_sql=false < docs/bigquery_views.sql`
   - Or execute each view individually

6. **Test queries**
   - Run example queries from above to verify data

## 💰 Cost Estimation

Based on configuration:
- **Storage**: ~$0.02/GB/month (partitioned by date)
- **Queries**: ~$5/TB scanned
- **Expected monthly cost**: $5-20 depending on log volume

Optimization:
- Tables are partitioned by date automatically
- Views don't add storage cost
- Query only necessary date ranges to minimize scanning

## 📝 Monitoring

Check BigQuery dataset in GCP Console:
https://console.cloud.google.com/bigquery?project=gen-lang-client-0607444019&d=options_wheel_logs

Check Cloud Logging sink:
https://console.cloud.google.com/logs/router?project=gen-lang-client-0607444019

## ✅ Status: 80% Complete

**Completed:**
- ✅ Dataset created
- ✅ Sink configured
- ✅ Permissions granted
- ✅ Code deployed (1st build)
- 🔄 Code deploying (2nd build - in progress)

**Remaining:**
- ⏳ Wait for build completion
- ⏳ Generate test logs
- ⏳ Create views (automated once logs exist)
- ⏳ Verify and test queries
