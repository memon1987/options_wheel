#!/bin/bash
# Resume Trading Script for Options Wheel Strategy
# Usage: ./scripts/resume_trading.sh

set -e

echo "🔄 RESUME TRADING - Options Wheel Strategy"
echo "========================================="
echo ""
echo "This will:"
echo "1. Re-enable all scheduled trading jobs"
echo "2. Restore normal trading mode (if not overridden)"
echo "3. Verify all operations resumed"
echo ""

read -p "Are you sure you want to resume trading? (yes/no): " -r
if [[ ! $REPLY =~ ^yes$ ]]; then
    echo "❌ Resume trading cancelled"
    exit 1
fi

echo ""
echo "▶️  Re-enabling scheduled jobs..."

# Enable all scheduled jobs
gcloud scheduler jobs resume morning-market-scan --location=us-central1 && echo "✅ Morning scan enabled"
gcloud scheduler jobs resume midday-strategy-execution --location=us-central1 && echo "✅ Midday execution enabled" 
gcloud scheduler jobs resume afternoon-position-check --location=us-central1 && echo "✅ Afternoon check enabled"

echo ""
echo "🔍 Running health check..."
python monitoring/health_monitor.py

echo ""
echo "📋 Current scheduled jobs status:"
gcloud scheduler jobs list --location=us-central1 --format="table(name,state,schedule)"

echo ""
echo "✅ TRADING RESUMED"
echo ""
echo "⚠️  IMPORTANT: Service is in paper trading mode by default"
echo "To enable live trading, update config/settings.yaml: paper_trading: false"
echo "Then redeploy: ./scripts/deploy.sh"
