#!/bin/bash
# Emergency Stop Script for Options Wheel Strategy
# Usage: ./scripts/emergency_stop.sh

set -e

echo "🚨 EMERGENCY STOP - Options Wheel Strategy"
echo "=========================================="
echo ""
echo "This will:"
echo "1. Disable all scheduled trading jobs"
echo "2. Force paper trading mode"
echo "3. Verify all operations stopped"
echo ""

read -p "Are you sure you want to stop all trading? (yes/no): " -r
if [[ ! $REPLY =~ ^yes$ ]]; then
    echo "❌ Emergency stop cancelled"
    exit 1
fi

echo ""
echo "🛑 Disabling scheduled jobs..."

# Disable all scheduled jobs
gcloud scheduler jobs pause morning-market-scan --location=us-central1 && echo "✅ Morning scan disabled"
gcloud scheduler jobs pause midday-strategy-execution --location=us-central1 && echo "✅ Midday execution disabled"
gcloud scheduler jobs pause afternoon-position-check --location=us-central1 && echo "✅ Afternoon check disabled"

echo ""
echo "🔒 Forcing paper trading mode..."
gcloud run services update options-wheel-strategy --region=us-central1 --update-env-vars=ALPACA_PAPER_TRADING=true && echo "✅ Paper trading mode enabled"

echo ""
echo "🔍 Verification..."
gcloud scheduler jobs list --location=us-central1 --format="table(name,state)"

echo ""
echo "🚨 EMERGENCY STOP COMPLETE"
echo ""
echo "All trading operations have been stopped."
echo "To resume trading, run: ./scripts/resume_trading.sh"
