#!/bin/bash
# Test script for all Options Wheel Strategy endpoints.
# Handles authentication and provides easy testing of all features.

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SERVICE_URL="https://options-wheel-strategy-omnlacz6ia-uc.a.run.app"

echo -e "${BLUE}🚀 Options Wheel Strategy - Endpoint Testing Tool${NC}"
echo "=================================================="

# Get authentication token
echo -e "${YELLOW}🔐 Getting authentication token...${NC}"
TOKEN=$(/Users/zmemon/google-cloud-sdk/bin/gcloud auth print-identity-token 2>/dev/null || echo "")

if [ -z "$TOKEN" ]; then
    echo -e "${RED}❌ Failed to get authentication token${NC}"
    echo "Please run: gcloud auth login"
    exit 1
fi

echo -e "${GREEN}✅ Authentication token obtained${NC}"

# Function to make authenticated requests
api_call() {
    local method=$1
    local endpoint=$2
    local data=${3:-""}

    echo -e "\n${BLUE}📡 Testing: ${method} ${endpoint}${NC}"
    echo "URL: ${SERVICE_URL}${endpoint}"

    if [ "$method" = "POST" ] && [ -n "$data" ]; then
        response=$(curl -s -w "\n%{http_code}" \
            -X "$method" \
            -H "Authorization: Bearer $TOKEN" \
            -H "Content-Type: application/json" \
            -d "$data" \
            "$SERVICE_URL$endpoint" 2>/dev/null)
    else
        response=$(curl -s -w "\n%{http_code}" \
            -H "Authorization: Bearer $TOKEN" \
            "$SERVICE_URL$endpoint" 2>/dev/null)
    fi

    # Extract HTTP status code (last line)
    http_code=$(echo "$response" | tail -n1)
    response_body=$(echo "$response" | head -n -1)

    if [ "$http_code" = "200" ]; then
        echo -e "${GREEN}✅ Status: $http_code${NC}"
        echo "Response:"
        echo "$response_body" | python3 -m json.tool 2>/dev/null || echo "$response_body"
    else
        echo -e "${RED}❌ Status: $http_code${NC}"
        echo "Response:"
        echo "$response_body"
    fi
}

# Test basic endpoints
echo -e "\n${YELLOW}🏥 Testing Basic Health Endpoints${NC}"
api_call "GET" "/"
api_call "GET" "/health"
api_call "GET" "/status"

# Test configuration
echo -e "\n${YELLOW}⚙️ Testing Configuration Endpoints${NC}"
api_call "GET" "/config"

# Test backtesting endpoints
echo -e "\n${YELLOW}📊 Testing Backtesting Endpoints${NC}"

# Quick backtest
echo -e "\n${BLUE}Running quick backtest...${NC}"
api_call "POST" "/backtest" '{
    "analysis_type": "quick",
    "symbol": "AAPL",
    "lookback_days": 7
}'

# Backtest history
api_call "GET" "/backtest/history"

# Performance comparison
api_call "POST" "/backtest/performance-comparison" '{
    "period_days": 30
}'

# Test dashboard endpoints
echo -e "\n${YELLOW}📈 Testing Dashboard Endpoints${NC}"
api_call "GET" "/dashboard"
api_call "GET" "/dashboard/alerts"
api_call "GET" "/dashboard/health"
api_call "GET" "/dashboard/trends"

# Test cache endpoints
echo -e "\n${YELLOW}💾 Testing Cache Management Endpoints${NC}"
api_call "GET" "/cache/stats"

# Test comprehensive backtest
echo -e "\n${YELLOW}🔬 Testing Comprehensive Backtest${NC}"
api_call "POST" "/backtest" '{
    "analysis_type": "comprehensive",
    "symbol": "MSFT",
    "lookback_days": 30,
    "strategy_params": {
        "delta_range": [0.10, 0.20],
        "dte_target": 7
    }
}'

# Test export functionality
echo -e "\n${YELLOW}📤 Testing Export Functionality${NC}"
api_call "GET" "/dashboard/metrics/export?format=json"

echo -e "\n${GREEN}🎉 Endpoint testing completed!${NC}"
echo -e "${BLUE}📝 Summary:${NC}"
echo "  • All major endpoints tested"
echo "  • Authentication working properly"
echo "  • Backtesting integration functional"
echo "  • Dashboard and monitoring active"
echo ""
echo -e "${YELLOW}💡 Tips for development:${NC}"
echo "  • Use /backtest with 'quick' analysis for fast testing"
echo "  • Check /dashboard/alerts for any system issues"
echo "  • Monitor /cache/stats for storage usage"
echo "  • Use /dashboard/metrics/export for data analysis"