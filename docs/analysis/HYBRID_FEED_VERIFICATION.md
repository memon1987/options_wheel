# Hybrid SIP+IEX Feed Verification Guide

**Implementation Date**: October 2, 2025 (12:20am ET)
**Git Commit**: 96a3bc4
**Build Status**: In Progress (f4c501f6)

---

## What Was Implemented

### Hybrid Feed Strategy:

1. **SIP Feed** (Securities Information Processor) - For historical bars
   - 100% market coverage (all 16 exchanges)
   - NBBO (National Best Bid Offer) prices
   - FREE with 15-minute delay
   - **20-minute buffer added** to avoid subscription errors

2. **IEX Feed** (Investors Exchange) - For real-time quotes
   - Real-time quotes, no delay
   - ~3% market volume (sufficient for wheel strategy)
   - FREE for all users

---

## Code Changes

### File: `src/api/alpaca_client.py`

**Line 102-105: `get_stock_quote()` now uses IEX**
```python
request = StockLatestQuoteRequest(
    symbol_or_symbols=[symbol],
    feed='iex'  # Real-time quotes from IEX exchange (FREE)
)
```

**Line 141-150: `get_stock_bars()` now has 20-min buffer for SIP**
```python
# Account for 15-min SIP delay with 20-min buffer for safety
end_date = datetime.now() - timedelta(minutes=20)
start_date = end_date - timedelta(days=days)

request = StockBarsRequest(
    symbol_or_symbols=[symbol],
    timeframe=TimeFrame.Day,
    start=start_date,
    end=end_date
    # No feed parameter = defaults to SIP (best quality, 15-min delayed)
)
```

---

## How to Verify It's Working

### Option 1: Wait for Next Scheduled Job

**Next scheduled execution**:
- **Morning Scan**: October 2, 2025 at 1:00pm ET (17:00 UTC)
- **Endpoint**: POST /scan

**What to check**:
```bash
# After 1pm ET, check logs for errors
gcloud logging read \
  'resource.type="cloud_run_revision" AND
   resource.labels.service_name="options-wheel-strategy" AND
   timestamp>="2025-10-02T17:00:00Z" AND
   timestamp<="2025-10-02T17:05:00Z"' \
  --limit=100 --format=json | \
  python3 -c "
import sys, json
logs = json.load(sys.stdin)
errors = [l for l in logs if 'subscription does not permit' in str(l).lower()]
print(f'Total logs: {len(logs)}')
print(f'Subscription errors: {len(errors)}')
if errors:
    print('\n❌ FAILED - Still seeing subscription errors')
    for e in errors[:3]:
        print(f'  {e.get(\"jsonPayload\", {}).get(\"symbol\")}: {e.get(\"jsonPayload\", {}).get(\"error\", \"\")}')
else:
    print('\n✅ SUCCESS - No subscription errors!')
"
```

---

### Option 2: Manual Test via API

**Trigger a scan manually**:
```bash
# Get service URL
SERVICE_URL=$(gcloud run services describe options-wheel-strategy \
  --region=us-central1 --format="value(status.url)")

# Trigger scan
curl -X POST "$SERVICE_URL/scan" \
  -H "Content-Type: application/json"

# Wait 30 seconds, then check logs
sleep 30

# Check for errors
gcloud logging read \
  'resource.type="cloud_run_revision" AND
   resource.labels.service_name="options-wheel-strategy"' \
  --limit=50 --format=json --freshness=2m | \
  grep -i "subscription" || echo "✅ No subscription errors found!"
```

---

### Option 3: Check Specific Stock (UNH)

**Look for UNH in logs**:
```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND
   resource.labels.service_name="options-wheel-strategy" AND
   jsonPayload.symbol="UNH"' \
  --limit=10 --format=json --freshness=1h | \
  python3 -c "
import sys, json
logs = json.load(sys.stdin)
print(f'UNH-related logs: {len(logs)}')
for log in logs[:5]:
    jp = log.get('jsonPayload', {})
    if 'error' in jp:
        print(f'❌ Error: {jp.get(\"event\")}: {jp.get(\"error\", \"\")[:100]}')
    else:
        print(f'✅ {jp.get(\"event\", \"Unknown\")}: {jp.get(\"symbol\")}')
"
```

---

## Expected Results

### Before Fix (What we saw on Oct 1):
```
❌ VZ - subscription does not permit querying recent SIP data
❌ KMI - subscription does not permit querying recent SIP data
❌ PFE - subscription does not permit querying recent SIP data
❌ F - subscription does not permit querying recent SIP data
❌ UNH - subscription does not permit querying recent SIP data
... (all 14 stocks failing)

Total errors: 28 (2 per stock: bars + metrics)
```

### After Fix (Expected):
```
✅ VZ - Got bars (30 days, SIP feed, end_date=3:40pm)
✅ KMI - Got bars (30 days, SIP feed, end_date=3:40pm)
✅ PFE - Got bars (30 days, SIP feed, end_date=3:40pm)
✅ F - Got bars (30 days, SIP feed, end_date=3:40pm)
✅ UNH - Got bars (30 days, SIP feed, end_date=3:40pm)
... (all 14 stocks working)

Total subscription errors: 0
```

---

## Why This Works

### Timing Analysis for Oct 2, 1pm ET Scan:

```
Current time:     1:00:00 PM ET
20-min buffer:  - 0:20:00
─────────────────────────────
Query end_date:  12:40:00 PM ET  ← 20 minutes ago

SIP data available from: 12:25 PM ET (15-min delay)
Our query asks for:      12:40 PM ET

Gap: 15 minutes of safety margin ✅
```

**Why it works**:
- We query data ending at 12:40pm
- SIP has data up to 12:25pm (current time - 15 min)
- We're well within the free tier limits!

### For 4pm ET Execution:

```
Current time:     4:00:00 PM ET (market close)
20-min buffer:  - 0:20:00
─────────────────────────────
Query end_date:  3:40:00 PM ET

SIP data available from: 3:45 PM ET (15-min delay)
Our query asks for:      3:40 PM ET

Perfect! We get data from 5 minutes BEFORE the delay kicks in! ✅
```

---

## Data Quality Verification

### Check Data Completeness:

After successful scan, verify we're getting quality data:

```sql
-- Query this in BigQuery once tables appear
SELECT
  DATE(timestamp) as date,
  symbol,
  COUNT(*) as bar_count,
  MIN(timestamp) as earliest_bar,
  MAX(timestamp) as latest_bar
FROM `gen-lang-client-0607444019.options_wheel_logs.performance_metrics`
WHERE metric_name IN ('put_opportunities_discovered', 'call_opportunities_discovered')
  AND DATE(timestamp) = CURRENT_DATE()
GROUP BY date, symbol
ORDER BY symbol
```

**Expected**:
- All 14 symbols present
- bar_count > 0 for each
- latest_bar within 20-25 minutes of scan time

---

## Rollback Plan (If Needed)

If the hybrid approach doesn't work, we have 3 fallback options:

### Fallback 1: Pure IEX (Real-time, Lower Quality)
```python
# In alpaca_client.py, add feed='iex' to bars:
request = StockBarsRequest(
    ...,
    feed='iex'  # Real-time but only 3% coverage
)
```

### Fallback 2: Increase Buffer (More Conservative)
```python
# Increase buffer from 20 to 30 minutes:
end_date = datetime.now() - timedelta(minutes=30)
```

### Fallback 3: Upgrade Subscription (Paid)
- Subscribe to Alpaca Algo Trader Plus (~$9/month)
- Get real-time SIP access
- No delays, best data quality

---

## Success Criteria

✅ **Primary**: No "subscription does not permit" errors in logs
✅ **Secondary**: All 14 stocks successfully scanned
✅ **Tertiary**: Enhanced logging events appear (opportunity discovery)
✅ **Quaternary**: Gap detection continues to work with quality data

---

## Timeline

| Time | Event | Verification |
|------|-------|--------------|
| **12:20am ET** | Code deployed (build in progress) | Check build status |
| **1:00pm ET** | Morning scan executes | Check logs immediately after |
| **4:00pm ET** | Midday strategy executes | Verify no errors, check trades |
| **7:00pm ET** | Evening position check | Confirm day's operations |

---

## Contact Points

**If verification fails**:
1. Check build completed successfully
2. Review logs for new error types
3. Verify API keys still valid in Cloud Run
4. Consider fallback options above

**Success indicators**:
- Logs show successful data retrieval
- Enhanced logging events appear
- BigQuery tables start populating
- Strategy execution proceeds normally

---

**This document will be used tomorrow (Oct 2) to verify the hybrid feed implementation is working correctly in production.**
