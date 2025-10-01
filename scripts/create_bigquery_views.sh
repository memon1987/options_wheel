#!/bin/bash
#
# Script to create BigQuery views for Options Wheel Trading Strategy logs
# Waits for log tables to appear, then creates all 6 views
#

set -e

PROJECT_ID="gen-lang-client-0607444019"
DATASET="options_wheel_logs"
VIEWS_SQL="docs/bigquery_views.sql"

echo "===================================="
echo "BigQuery Views Creation Script"
echo "===================================="
echo ""

# Check if bq command exists
if ! command -v bq &> /dev/null; then
    echo "❌ Error: 'bq' command not found"
    echo "Please ensure Google Cloud SDK is installed and in PATH"
    exit 1
fi

# Check if views SQL file exists
if [ ! -f "$VIEWS_SQL" ]; then
    echo "❌ Error: Views SQL file not found: $VIEWS_SQL"
    exit 1
fi

echo "Step 1: Checking if log tables exist..."
echo ""

# Function to check if tables exist
check_tables() {
    bq ls --project_id=$PROJECT_ID --format=json $DATASET 2>/dev/null | python3 -c "
import sys, json
try:
    tables = json.load(sys.stdin)
    log_tables = [t for t in tables if t['tableReference']['tableId'].startswith('cloud_run_logs_')]
    if log_tables:
        print(f'✅ Found {len(log_tables)} log table(s)')
        for t in log_tables[:3]:
            print(f\"  - {t['tableReference']['tableId']}\")
        sys.exit(0)
    else:
        print('⏳ No log tables found yet')
        sys.exit(1)
except Exception as e:
    print(f'Error checking tables: {e}')
    sys.exit(1)
"
}

# Check for tables, with retry logic
MAX_RETRIES=5
RETRY_COUNT=0
WAIT_SECONDS=60

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if check_tables; then
        break
    else
        RETRY_COUNT=$((RETRY_COUNT + 1))
        if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
            echo ""
            echo "Waiting $WAIT_SECONDS seconds for logs to export (attempt $RETRY_COUNT/$MAX_RETRIES)..."
            sleep $WAIT_SECONDS
        fi
    fi
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo ""
    echo "❌ Timeout: No log tables found after $MAX_RETRIES attempts"
    echo ""
    echo "Troubleshooting steps:"
    echo "1. Verify Cloud Run service is running and generating logs"
    echo "2. Check log sink is configured: gcloud logging sinks list"
    echo "3. Verify logs have event_category field"
    echo "4. Wait longer (logs export in batches every 5-10 minutes)"
    exit 1
fi

echo ""
echo "Step 2: Creating BigQuery views..."
echo ""

# Create views from SQL file
if bq query --use_legacy_sql=false --project_id=$PROJECT_ID < "$VIEWS_SQL"; then
    echo ""
    echo "✅ Successfully created all views!"
else
    echo ""
    echo "❌ Error creating views"
    exit 1
fi

echo ""
echo "Step 3: Verifying views..."
echo ""

# List all tables and views
bq ls --project_id=$PROJECT_ID $DATASET | python3 -c "
import sys
views = []
tables = []
for line in sys.stdin:
    line = line.strip()
    if 'VIEW' in line:
        parts = line.split()
        views.append(parts[0])
    elif 'TABLE' in line and 'cloud_run_logs_' in line:
        parts = line.split()
        tables.append(parts[0])

print(f'📊 Dataset Summary:')
print(f'  Tables (raw logs): {len(tables)}')
print(f'  Views (analytics): {len(views)}')
print('')
if views:
    print('Available views:')
    for view in sorted(views):
        print(f'  ✓ {view}')
else:
    print('⚠️  No views found')
"

echo ""
echo "Step 4: Testing views with sample queries..."
echo ""

# Test each view with a simple count query
VIEWS=("trades" "risk_events" "performance_metrics" "errors" "system_events" "position_updates")

for VIEW in "${VIEWS[@]}"; do
    echo -n "Testing $VIEW... "
    COUNT=$(bq query --use_legacy_sql=false --format=csv --project_id=$PROJECT_ID \
        "SELECT COUNT(*) as count FROM \`$PROJECT_ID.$DATASET.$VIEW\`" 2>/dev/null | tail -n 1)

    if [ $? -eq 0 ]; then
        echo "✅ OK ($COUNT rows)"
    else
        echo "❌ FAILED"
    fi
done

echo ""
echo "===================================="
echo "✅ BigQuery Setup Complete!"
echo "===================================="
echo ""
echo "Next steps:"
echo "1. Open Looker Studio: https://lookerstudio.google.com"
echo "2. Create new report and connect to BigQuery"
echo "3. Select project: $PROJECT_ID"
echo "4. Select dataset: $DATASET"
echo "5. Choose a view to start: 'trades' (recommended)"
echo ""
echo "Documentation:"
echo "- Setup guide: docs/LOOKER_STUDIO_SETUP.md"
echo "- User guide: docs/LOOKER_STUDIO_DASHBOARD.md"
echo ""
