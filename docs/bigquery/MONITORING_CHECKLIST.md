# BigQuery Monitoring Checklist

Quick reference for verifying BigQuery log sync after enhanced logging deployment.

---

## ✅ Pre-Flight Checks (Completed)

- [x] BigQuery dataset created (`options_wheel_logs`)
- [x] Cloud Logging sink configured (`options-wheel-logs`)
- [x] IAM permissions granted
- [x] Enhanced logging code committed (228785e)
- [x] Build started (ffb83934-1908-4a4d-a2ed-a170d5c1bcc0)

---

## 🔄 Build & Deployment (In Progress)

### 1. Monitor Build Completion
```bash
# Check build status
gcloud builds list --limit=1

# Expected: STATUS changes from WORKING → SUCCESS
```

**When**: Check every 5-10 minutes
**Current**: Build started at 5:17 AM UTC

---

## ⏳ Post-Deployment Verification

### 2. Verify New Revision Deployed
```bash
# Check active revision
gcloud run revisions list --service=options-wheel-strategy \
  --region=us-central1 --limit=1

# Expected: New revision with commit 228785e
```

**When**: Immediately after build SUCCESS
**Look for**: Revision name with recent timestamp

---

### 3. Wait for Next Hourly Execution

**Schedule**:
- Scan jobs run at `:00` (10am, 11am, 12pm, 1pm, 2pm, 3pm ET)
- Execute jobs run at `:15` (10:15am, 11:15am, etc. ET)

**Next opportunity**: 10:00 AM ET / 14:00 UTC
**Timeline**: ~8-9 hours from now (currently 1:24 AM ET)

---

### 4. Verify STAGE Logs in Cloud Logging
```bash
# Check for STAGE prefixed logs
gcloud logging read 'resource.labels.service_name="options-wheel-strategy" \
  AND jsonPayload.event=~"STAGE"' \
  --limit=20 \
  --freshness=1h

# Expected: Logs like "STAGE 1 COMPLETE: Price/Volume filtering"
```

**When**: Immediately after 10:15 AM ET execution
**Success criteria**: See logs from all 9 stages

---

### 5. Verify Event Categories
```bash
# Check for event_category field
gcloud logging read 'resource.labels.service_name="options-wheel-strategy" \
  AND jsonPayload.event_category:*' \
  --limit=10 \
  --freshness=1h \
  --format=json | jq -r '.[] | .jsonPayload.event_category' | sort | uniq

# Expected: trade, risk, performance, error, system, position
```

**When**: After first execution
**Success criteria**: Multiple event_category types present

---

### 6. Wait for BigQuery Export

**Timeline**: 5-10 minutes after first logs with `event_category`
**Process**: Cloud Logging batches and exports logs automatically

```bash
# Check every minute after 10:25 AM ET
bq ls options_wheel_logs
```

**Expected output**:
```
 tableId              Type
-------------------  -------
 cloud_run_logs_20251003   TABLE
```

---

### 7. Verify Table Schema
```bash
# Check table exists and view schema
bq show options_wheel_logs.cloud_run_logs_20251003

# Look for: jsonPayload with nested fields
```

**Success criteria**: Table has rows and jsonPayload structure

---

### 8. Sample Enhanced Logs from BigQuery
```bash
# Query recent STAGE logs
bq query --use_legacy_sql=false \
  "SELECT
     timestamp,
     jsonPayload.event,
     jsonPayload.symbol,
     jsonPayload.event_category
   FROM \`gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*\`
   WHERE jsonPayload.event LIKE 'STAGE%'
   ORDER BY timestamp DESC
   LIMIT 20"
```

**Success criteria**: Results show STAGE 1-9 logs with symbols

---

### 9. Create BigQuery Views
```bash
# Create all 6 analytics views
bq query --use_legacy_sql=false < docs/bigquery_views.sql

# Expected: 6 views created successfully
```

**Views created**:
1. `trades`
2. `risk_events`
3. `performance_metrics`
4. `errors`
5. `system_events`
6. `position_updates`

---

### 10. Test Analytics Queries

#### Test 1: Verify trades view
```bash
bq query --use_legacy_sql=false \
  "SELECT * FROM \`gen-lang-client-0607444019.options_wheel_logs.trades\` LIMIT 5"
```

#### Test 2: Verify risk events
```bash
bq query --use_legacy_sql=false \
  "SELECT * FROM \`gen-lang-client-0607444019.options_wheel_logs.risk_events\` LIMIT 5"
```

#### Test 3: Stage-by-stage flow
```bash
bq query --use_legacy_sql=false \
  "SELECT
     jsonPayload.event,
     COUNT(*) as count
   FROM \`gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*\`
   WHERE jsonPayload.event LIKE 'STAGE%'
     AND DATE(timestamp) = CURRENT_DATE()
   GROUP BY jsonPayload.event
   ORDER BY jsonPayload.event"
```

**Success criteria**: All queries return data

---

## 📊 Validation Queries

### Verify Complete Filter Pipeline
```sql
-- Should see all 9 stages represented
SELECT
  REGEXP_EXTRACT(jsonPayload.event, r'STAGE (\d+)') as stage_number,
  jsonPayload.event,
  COUNT(*) as occurrences
FROM `gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*`
WHERE jsonPayload.event LIKE 'STAGE%'
  AND DATE(timestamp) = CURRENT_DATE()
GROUP BY stage_number, jsonPayload.event
ORDER BY stage_number;
```

### Check for Gaps in Logging
```sql
-- Verify we have logs for each execution
SELECT
  TIMESTAMP_TRUNC(timestamp, HOUR) as execution_hour,
  COUNT(DISTINCT jsonPayload.event) as unique_events,
  COUNT(*) as total_logs
FROM `gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*`
WHERE DATE(timestamp) = CURRENT_DATE()
GROUP BY execution_hour
ORDER BY execution_hour DESC;
```

### Verify Event Categories
```sql
-- Should see trade, risk, performance, system, etc.
SELECT
  jsonPayload.event_category,
  COUNT(*) as count
FROM `gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*`
WHERE jsonPayload.event_category IS NOT NULL
  AND DATE(timestamp) = CURRENT_DATE()
GROUP BY jsonPayload.event_category;
```

---

## ✅ Success Criteria

BigQuery log sync is **fully operational** when:

- [x] Build completed successfully
- [x] New revision deployed
- [x] STAGE logs appear in Cloud Logging
- [x] event_category fields present
- [x] BigQuery table created
- [x] Table contains recent logs
- [x] All 6 views created
- [x] Analytics queries return data
- [x] All 9 stages visible in logs

---

## 🚨 Troubleshooting

### No BigQuery Tables Created

**Symptoms**: `bq ls options_wheel_logs` returns empty

**Possible causes**:
1. No logs with `event_category` yet
2. Export delay (wait 10-15 minutes)
3. Sink filter too restrictive

**Check**:
```bash
# Verify logs exist in Cloud Logging
gcloud logging read 'jsonPayload.event_category:*' --limit=5

# Verify sink is active
gcloud logging sinks describe options-wheel-logs
```

---

### STAGE Logs Not Appearing

**Symptoms**: Old log format still showing

**Possible causes**:
1. Old revision still deployed
2. Build failed
3. Code not committed/pushed

**Check**:
```bash
# Check active revision commit
gcloud run revisions list --service=options-wheel-strategy --region=us-central1 --limit=1

# Check recent builds
gcloud builds list --limit=3

# Verify local commit is pushed
git log --oneline -1
git status
```

---

### Views Creation Fails

**Symptoms**: `CREATE VIEW` returns error

**Possible causes**:
1. No tables exist yet (most common)
2. Syntax error in SQL
3. Permissions issue

**Solution**:
```bash
# Verify table exists first
bq ls options_wheel_logs

# Try creating one view at a time
bq query --use_legacy_sql=false \
  "CREATE OR REPLACE VIEW \`gen-lang-client-0607444019.options_wheel_logs.trades\` AS
   SELECT * FROM \`gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*\`
   WHERE jsonPayload.event_category = 'trade'
   LIMIT 1"
```

---

## 📅 Timeline

| Time (ET) | Event | Action |
|-----------|-------|--------|
| 1:17 AM | Build started | ✅ Initiated |
| 1:25 AM | Build completes (est.) | ⏳ Wait |
| 1:30 AM | New revision deployed | ⏳ Verify |
| 10:00 AM | First scan execution | ⏳ Monitor logs |
| 10:15 AM | First execute job | ⏳ Verify STAGE logs |
| 10:25 AM | BigQuery table created | ⏳ Check `bq ls` |
| 10:30 AM | Create views | ⏳ Run SQL |
| 10:35 AM | Test queries | ⏳ Validate |
| **10:40 AM** | **COMPLETE** | 🎉 **Verified** |

---

## 📞 Quick Commands Reference

```bash
# Check build
gcloud builds list --limit=1

# Check deployment
gcloud run revisions list --service=options-wheel-strategy --region=us-central1 --limit=1

# Check STAGE logs
gcloud logging read 'jsonPayload.event=~"STAGE"' --limit=10 --freshness=1h

# Check BigQuery tables
bq ls options_wheel_logs

# Sample BigQuery data
bq query --use_legacy_sql=false \
  "SELECT * FROM \`gen-lang-client-0607444019.options_wheel_logs.cloud_run_logs_*\` \
   WHERE jsonPayload.event LIKE 'STAGE%' LIMIT 10"

# Create views
bq query --use_legacy_sql=false < docs/bigquery_views.sql
```

---

**Last Updated**: October 3, 2025 1:24 AM ET
**Status**: Build in progress, ready for post-deployment verification
