#!/bin/bash
# Real-time log monitoring for Options Wheel Strategy
# Polls Cloud Run logs every 10 seconds

echo "🔍 Monitoring Options Wheel Strategy logs in real-time..."
echo "Press Ctrl+C to stop"
echo "======================================================="

while true; do
    echo -e "\n⏰ $(date): Checking for new logs..."
    /Users/zmemon/google-cloud-sdk/bin/gcloud logging read \
        'resource.type="cloud_run_revision" AND resource.labels.service_name="options-wheel-strategy"' \
        --limit=5 \
        --format="table(timestamp,severity,textPayload)" \
        --freshness=30s 2>/dev/null || echo "No new logs in last 30 seconds"

    sleep 10
done