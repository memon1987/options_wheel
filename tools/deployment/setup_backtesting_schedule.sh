#!/bin/bash
# Setup backtesting scheduled jobs for Options Wheel Strategy
# Creates Cloud Scheduler jobs for automated backtesting analysis

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
GCLOUD_PATH="/Users/zmemon/google-cloud-sdk/bin/gcloud"
PROJECT_ID="gen-lang-client-0607444019"
REGION="us-central1"
SERVICE_URL="https://options-wheel-strategy-omnlacz6ia-uc.a.run.app"

echo -e "${BLUE}🔧 Setting up Options Wheel Backtesting Schedule${NC}"
echo "=================================================="

# Function to create scheduler job
create_scheduler_job() {
    local job_name=$1
    local schedule=$2
    local endpoint=$3
    local description=$4
    local data=$5

    echo -e "\n${YELLOW}📅 Creating job: ${job_name}${NC}"
    echo "Schedule: ${schedule}"
    echo "Endpoint: ${endpoint}"
    echo "Description: ${description}"

    $GCLOUD_PATH scheduler jobs create http $job_name \
        --location=$REGION \
        --schedule="$schedule" \
        --uri="${SERVICE_URL}${endpoint}" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body="$data" \
        --description="$description" \
        --oidc-service-account-email="799970961417-compute@developer.gserviceaccount.com" \
        --quiet 2>/dev/null || {

        echo -e "${YELLOW}⚠️ Job $job_name already exists, updating...${NC}"
        $GCLOUD_PATH scheduler jobs update http $job_name \
            --location=$REGION \
            --schedule="$schedule" \
            --uri="${SERVICE_URL}${endpoint}" \
            --http-method=POST \
            --headers="Content-Type=application/json" \
            --message-body="$data" \
            --description="$description" \
            --oidc-service-account-email="799970961417-compute@developer.gserviceaccount.com" \
            --quiet
    }

    echo -e "${GREEN}✅ Job $job_name configured${NC}"
}

# Create backtesting jobs
echo -e "\n${YELLOW}📊 Creating Backtesting Schedule Jobs${NC}"

# Daily Quick Backtest (weekdays at 8 AM ET)
create_scheduler_job \
    "daily-quick-backtest" \
    "0 13 * * 1-5" \
    "/backtest" \
    "Daily quick backtest analysis for strategy optimization" \
    '{
        "analysis_type": "quick",
        "symbol": "SPY",
        "lookback_days": 7,
        "auto_symbols": true,
        "strategy_params": {
            "delta_range": [0.10, 0.20],
            "dte_target": 7
        }
    }'

# Weekly Comprehensive Backtest (Mondays at 6 AM ET)
create_scheduler_job \
    "weekly-comprehensive-backtest" \
    "0 11 * * 1" \
    "/backtest" \
    "Weekly comprehensive backtest across multiple symbols" \
    '{
        "analysis_type": "comprehensive",
        "symbol": "AAPL",
        "lookback_days": 30,
        "auto_symbols": true,
        "strategy_params": {
            "delta_range": [0.10, 0.20],
            "dte_target": 7
        }
    }'

# Monthly Performance Review (1st of month at 7 AM ET)
create_scheduler_job \
    "monthly-performance-review" \
    "0 12 1 * *" \
    "/backtest/performance-comparison" \
    "Monthly comprehensive performance review and comparison" \
    '{
        "period_days": 90,
        "include_benchmarks": true,
        "detailed_analysis": true
    }'

# Cache Maintenance (Daily at 2 AM ET)
create_scheduler_job \
    "daily-cache-maintenance" \
    "0 7 * * *" \
    "/cache/maintenance" \
    "Daily cache cleanup and optimization" \
    '{
        "cleanup_old_data": true,
        "optimize_storage": true,
        "max_cache_age_days": 30
    }'

# List all scheduler jobs
echo -e "\n${BLUE}📋 Current Scheduler Jobs:${NC}"
$GCLOUD_PATH scheduler jobs list --location=$REGION --format="table(name,schedule,state)" 2>/dev/null || echo "Unable to list jobs"

echo -e "\n${GREEN}🎉 Backtesting schedule setup complete!${NC}"
echo -e "\n${BLUE}📅 Schedule Summary:${NC}"
echo "  • Daily Quick Backtest: 8:00 AM ET (Mon-Fri)"
echo "  • Weekly Comprehensive: 6:00 AM ET (Mondays)"
echo "  • Monthly Review: 7:00 AM ET (1st of month)"
echo "  • Cache Maintenance: 2:00 AM ET (Daily)"
echo ""
echo -e "${YELLOW}💡 Backtesting Times (separate from trading):${NC}"
echo "  • Backtesting runs in the morning for analysis"
echo "  • Trading execution happens at 4:00 PM ET"
echo "  • This separation allows morning analysis to inform afternoon trades"
echo ""
echo -e "${BLUE}🔍 Monitor jobs with:${NC}"
echo "  gcloud scheduler jobs list --location=$REGION"
echo "  gcloud logging read 'resource.type=\"cloud_run_revision\"' --limit=10"