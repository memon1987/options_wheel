# Quick Start: Testing Scan-to-Execution

## Prerequisites
- Alpaca paper trading account credentials in Google Secret Manager
- Google Cloud SDK installed and authenticated
- Python 3.9+ with dependencies installed

## Local Testing (Fast Iteration)

### 1. Setup Environment
```bash
cd /Users/zmemon/options_wheel-1

# Download credentials
gcloud secrets versions access latest --secret=alpaca-api-key > /tmp/key.txt
gcloud secrets versions access latest --secret=alpaca-secret-key > /tmp/secret.txt

# Create .env file
cat > .env <<EOF
ALPACA_API_KEY=$(cat /tmp/key.txt)
ALPACA_SECRET_KEY=$(cat /tmp/secret.txt)
EOF

rm /tmp/key.txt /tmp/secret.txt

# Install dependencies
pip3 install google-cloud-storage alpaca-py pyyaml python-dotenv structlog pandas
```

### 2. Test Position Sizing Only
```bash
python3 test_position_sizing.py
```
**Expected Output:**
```
✓ Position sizing SUCCESS
  Calculated contracts: 1
  Capital per contract: $15,500.00
  Portfolio value: $100,000.00
```

### 3. Test Full Execution Flow
```bash
python3 test_execution_flow.py
```
**Expected Output:**
```
✅ Trade EXECUTED successfully!
  Order ID: d2427a12-...
  Status: accepted

Opportunities evaluated: 2
Trades executed: 2
```

### 4. Verify Trades in Alpaca
```bash
# Check orders
curl -X GET "https://paper-api.alpaca.markets/v2/orders" \
  -H "APCA-API-KEY-ID: ${ALPACA_API_KEY}" \
  -H "APCA-API-SECRET-KEY: ${ALPACA_SECRET_KEY}" | jq '.[0:2]'
```

## Cloud Testing (Full Integration)

### 1. Trigger Manual Scan
```bash
# Run a market scan
gcloud scheduler jobs run scan-10am --location=us-central1

# Wait 5 seconds for completion
sleep 5

# Check scan results
gcloud logging read \
  'resource.labels.service_name="options-wheel-strategy"
   AND jsonPayload.event_type="market_scan_completed"' \
  --limit=1 --format=json | jq '.[] | .jsonPayload | {
    put_opportunities,
    call_opportunities,
    total_opportunities,
    stored_for_execution
  }'
```

**Expected Output:**
```json
{
  "put_opportunities": 10,
  "call_opportunities": 0,
  "total_opportunities": 10,
  "stored_for_execution": true
}
```

### 2. Trigger Manual Execution
```bash
# Execute trades from most recent scan
gcloud scheduler jobs run execute-10-15am --location=us-central1

# Wait 10 seconds for completion
sleep 10

# Check execution results
gcloud logging read \
  'resource.labels.service_name="options-wheel-strategy"
   AND jsonPayload.event_type="strategy_execution_completed"' \
  --limit=1 --format=json | jq '.[] | .jsonPayload | {
    opportunities_evaluated,
    trades_executed,
    trades_failed,
    duration_seconds
  }'
```

**Expected Output:**
```json
{
  "opportunities_evaluated": 10,
  "trades_executed": 8,
  "trades_failed": 2,
  "duration_seconds": 2.5
}
```

### 3. View Executed Trades
```bash
# Get trade execution logs
gcloud logging read \
  'resource.labels.service_name="options-wheel-strategy"
   AND jsonPayload.event_category="trade"
   AND jsonPayload.event_type="trade_executed"' \
  --limit=5 --format=json | jq '.[] | .jsonPayload | {
    symbol: .underlying,
    option_symbol,
    contracts,
    premium,
    order_id
  }'
```

### 4. Check Cloud Storage
```bash
# List stored opportunities
gsutil ls gs://options-wheel-opportunities/opportunities/$(date +%Y-%m-%d)/

# View specific scan
gsutil cat gs://options-wheel-opportunities/opportunities/$(date +%Y-%m-%d)/18-36.json | jq '.'
```

## Common Issues

### Issue: "No opportunities found"
```bash
# Check if scan ran successfully
gcloud logging read \
  'jsonPayload.event_type="market_scan_completed"' \
  --limit=1 --freshness=10m

# Check for scan failures
gcloud logging read \
  'jsonPayload.event_category="error"
   AND jsonPayload.component="options_scanner"' \
  --limit=5 --freshness=10m
```

### Issue: "Opportunities expired"
```bash
# Check opportunity age
gsutil cat gs://options-wheel-opportunities/opportunities/$(date +%Y-%m-%d)/*.json \
  | jq '.scan_time, .expires_at'

# Increase max age if needed
# Edit config/settings.yaml:
#   opportunity_max_age_minutes: 60  # increase from 30 to 60
```

### Issue: "Position sizing failed"
```bash
# Check buying power
gcloud logging read \
  'jsonPayload.event="STAGE 8 BLOCKED"' \
  --limit=5 --format=json | jq '.[] | .jsonPayload | {
    symbol,
    reason,
    capital_required,
    buying_power
  }'
```

### Issue: "Trade execution failed"
```bash
# Check trade failures
gcloud logging read \
  'jsonPayload.event_type="trade_execution_failed"' \
  --limit=5 --format=json | jq '.[] | .jsonPayload | {
    symbol,
    option_symbol,
    error_message
  }'
```

## Monitoring Commands

### Check Latest Revision
```bash
gcloud run services describe options-wheel-strategy \
  --region=us-central1 \
  --format="value(status.latestReadyRevisionName)"
```

### Check Build Status
```bash
gcloud builds list --limit=1 \
  --format="table(id,status,createTime,substitutions.SHORT_SHA)"
```

### Watch Logs in Real-Time
```bash
# All logs
gcloud logging tail "resource.labels.service_name=options-wheel-strategy"

# Only system events
gcloud logging tail \
  "resource.labels.service_name=options-wheel-strategy
   AND jsonPayload.event_category=system"

# Only trades
gcloud logging tail \
  "resource.labels.service_name=options-wheel-strategy
   AND jsonPayload.event_category=trade"
```

### Check Scheduled Jobs
```bash
gcloud scheduler jobs list --location=us-central1 \
  --format="table(name,schedule,lastAttemptTime,state)"
```

## Configuration Quick Reference

### Timing
```yaml
# config/settings.yaml
strategy:
  opportunity_max_age_minutes: 30  # Max age for valid opportunities
```

### Position Sizing
```yaml
risk:
  max_position_size: 0.80  # 80% max of portfolio per position

strategy:
  max_exposure_per_ticker: 25000  # $25k max per ticker
```

### API Endpoints
```yaml
alpaca:
  paper_trading: true  # Use paper API endpoints (required for current subscription)
```

## Success Checklist

- [ ] Local test executes 2+ trades successfully
- [ ] Cloud scan finds opportunities (total_opportunities > 0)
- [ ] Cloud execution retrieves scan (opportunities_evaluated > 0)
- [ ] Cloud execution places trades (trades_executed > 0)
- [ ] Trades visible in Alpaca paper account
- [ ] Logs show event_category for BigQuery export
- [ ] No API authorization errors (40110000)
- [ ] No data format errors (missing 'contracts' or 'mid_price')

## Next Steps After Testing

1. Review Alpaca paper account positions
2. Monitor automated hourly schedule
3. Analyze BigQuery logs for patterns
4. Adjust configuration based on results
5. Document any edge cases discovered
