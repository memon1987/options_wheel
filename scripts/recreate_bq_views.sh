#!/bin/bash
# Recreate all BigQuery views with corrected JSON_VALUE() extraction

set -e  # Exit on error

export PATH="/Users/zmemon/google-cloud-sdk/bin:$PATH"

echo "Recreating BigQuery views..."

# Function to extract and run each CREATE VIEW statement
recreate_view() {
    local view_name=$1
    echo "Creating view: $view_name..."

    # Extract the view definition from the SQL file and execute it
    awk "/CREATE OR REPLACE VIEW.*${view_name}/,/;/" docs/bigquery_views.sql | \
    sed 's/;$//' | \
    bq query --use_legacy_sql=false

    if [ $? -eq 0 ]; then
        echo "✓ Successfully created $view_name"
    else
        echo "✗ Failed to create $view_name"
        return 1
    fi
}

# Create each view
recreate_view "risk_events"
recreate_view "performance_metrics"
recreate_view "errors"
recreate_view "system_events"
recreate_view "position_updates"
recreate_view "backtest_results"

echo ""
echo "All views recreated successfully!"
