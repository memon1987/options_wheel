#!/bin/bash
# Options Wheel Strategy - Maintenance Script
# Usage: ./scripts/maintenance.sh [daily|weekly|monthly]

set -e

TASK=${1:-"daily"}

echo "🔧 Options Wheel Strategy Maintenance"
echo "====================================="
echo "Task: $TASK"

case $TASK in
    "daily")
        echo ""
        echo "📊 Daily Health Check"
        python monitoring/health_monitor.py
        
        echo ""
        echo "📈 Strategy Status"
        /Users/zmemon/google-cloud-sdk/bin/gcloud logging read 'resource.type="cloud_run_revision" AND textPayload:("scan" OR "execution")' --limit=5 --format="table(timestamp,textPayload)"
        ;;
        
    "weekly")
        echo ""
        echo "📊 Weekly Performance Review"
        python monitoring/health_monitor.py
        
        echo ""
        echo "⚠️  Recent Warnings/Errors"
        /Users/zmemon/google-cloud-sdk/bin/gcloud logging read 'resource.type="cloud_run_revision" AND severity>=WARNING' --limit=10 --format="table(timestamp,severity,textPayload)"
        
        echo ""
        echo "📈 Service Performance"
        /Users/zmemon/google-cloud-sdk/bin/gcloud run services describe options-wheel-strategy --region=us-central1 --format="table(spec.template.spec.containers[0].resources.limits.memory,spec.template.metadata.annotations[autoscaling.knative.dev/maxScale])"
        ;;
        
    "monthly")
        echo ""
        echo "📊 Monthly Review"
        python monitoring/health_monitor.py
        
        echo ""
        echo "💰 Cost Analysis (Last 30 days)"
        echo "Visit: https://console.cloud.google.com/billing"
        
        echo ""
        echo "🔍 Dependency Check"
        pip list --outdated || echo "No outdated packages found"
        
        echo ""
        echo "📋 Configuration Backup"
        mkdir -p backup
        /Users/zmemon/google-cloud-sdk/bin/gcloud run services describe options-wheel-strategy --region=us-central1 --format="export" > backup/service-config-$(date +%Y%m%d).yaml
        cp config/settings.yaml backup/settings-$(date +%Y%m%d).yaml
        echo "✅ Configuration backed up to backup/ directory"
        ;;
        
    *)
        echo "❌ Unknown task: $TASK"
        echo "Usage: $0 [daily|weekly|monthly]"
        exit 1
        ;;
esac

echo ""
echo "✅ Maintenance complete"
