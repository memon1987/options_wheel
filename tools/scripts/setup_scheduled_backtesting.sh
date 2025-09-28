#!/bin/bash
"""
Setup script for scheduled backtesting jobs using Cloud Scheduler.
Creates Cloud Scheduler jobs that trigger backtesting analysis on a regular schedule.
"""

set -euo pipefail

# Configuration
PROJECT_ID="gen-lang-client-0607444019"
REGION="us-central1"
SERVICE_NAME="options-wheel-strategy"
SERVICE_URL="https://options-wheel-strategy-omnlacz6ia-uc.a.run.app"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🔧 Setting up scheduled backtesting jobs...${NC}"

# Function to create a scheduler job
create_scheduler_job() {
    local job_name=$1
    local schedule=$2
    local endpoint=$3
    local description=$4
    local payload=$5

    echo -e "${YELLOW}Creating job: ${job_name}${NC}"

    # Delete existing job if it exists
    if gcloud scheduler jobs describe "${job_name}" --location="${REGION}" &>/dev/null; then
        echo "  Deleting existing job..."
        gcloud scheduler jobs delete "${job_name}" --location="${REGION}" --quiet
    fi

    # Create the new job
    gcloud scheduler jobs create http "${job_name}" \
        --location="${REGION}" \
        --schedule="${schedule}" \
        --uri="${SERVICE_URL}${endpoint}" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body="${payload}" \
        --description="${description}" \
        --time-zone="America/New_York" \
        --max-retry-attempts=3 \
        --max-retry-duration=300s \
        --min-backoff-duration=30s \
        --max-backoff-duration=120s

    echo -e "${GREEN}  ✅ Job created successfully${NC}"
}

# Weekly backtesting analysis - Every Monday at 6 AM ET
echo -e "${BLUE}Setting up weekly backtesting analysis...${NC}"
create_scheduler_job \
    "weekly-backtest-analysis" \
    "0 6 * * 1" \
    "/backtest" \
    "Weekly backtesting analysis for strategy performance review" \
    '{"analysis_type": "quick", "lookback_days": 30, "symbol": "AAPL"}'

# Bi-weekly comprehensive analysis - Every other Sunday at 7 AM ET
echo -e "${BLUE}Setting up bi-weekly comprehensive analysis...${NC}"
create_scheduler_job \
    "biweekly-comprehensive-backtest" \
    "0 7 */14 * 0" \
    "/backtest" \
    "Bi-weekly comprehensive backtesting analysis" \
    '{"analysis_type": "comprehensive", "lookback_days": 60, "symbol": "MSFT"}'

# Monthly strategy review - First Sunday of every month at 8 AM ET
echo -e "${BLUE}Setting up monthly strategy review...${NC}"
create_scheduler_job \
    "monthly-strategy-review" \
    "0 8 1-7 * 0" \
    "/backtest/performance-comparison" \
    "Monthly strategy performance review and comparison" \
    '{"period_days": 90}'

# Cache maintenance - Weekly on Saturday at 2 AM ET
echo -e "${BLUE}Setting up cache maintenance...${NC}"
create_scheduler_job \
    "weekly-cache-cleanup" \
    "0 2 * * 6" \
    "/cache/cleanup" \
    "Weekly cache cleanup to manage storage costs" \
    '{"days_old": 30}'

# Performance monitoring - Daily at 4 PM ET (after market close)
echo -e "${BLUE}Setting up daily performance monitoring...${NC}"
create_scheduler_job \
    "daily-performance-check" \
    "0 16 * * 1-5" \
    "/backtest/performance-comparison" \
    "Daily performance monitoring vs backtested expectations" \
    '{"period_days": 7}'

echo -e "${GREEN}✅ All scheduled backtesting jobs created successfully!${NC}"

# List all the jobs
echo -e "${BLUE}📋 Current scheduled jobs:${NC}"
gcloud scheduler jobs list --location="${REGION}" --filter="name:backtest OR name:cache OR name:performance" --format="table(name,schedule,state)"

echo -e "${BLUE}🎯 Scheduled backtesting setup complete!${NC}"
echo ""
echo -e "${YELLOW}Job Schedule Summary:${NC}"
echo "  • Weekly Analysis:       Monday 6 AM ET"
echo "  • Bi-weekly Comprehensive: Every 2 weeks, Sunday 7 AM ET"
echo "  • Monthly Review:        1st Sunday of month, 8 AM ET"
echo "  • Cache Cleanup:         Saturday 2 AM ET"
echo "  • Daily Monitoring:      Weekdays 4 PM ET"
echo ""
echo -e "${GREEN}All jobs use EST/EDT timezone and include retry logic.${NC}"

# Test one of the jobs
echo -e "${BLUE}🧪 Testing weekly analysis job...${NC}"
if gcloud scheduler jobs run weekly-backtest-analysis --location="${REGION}"; then
    echo -e "${GREEN}✅ Test job triggered successfully${NC}"
    echo "Check Cloud Logging for execution results:"
    echo "gcloud logging read 'resource.type=\"cloud_run_revision\"' --limit=10"
else
    echo -e "${RED}❌ Failed to trigger test job${NC}"
fi

echo -e "${BLUE}📊 Setup complete! Scheduled backtesting is now active.${NC}"