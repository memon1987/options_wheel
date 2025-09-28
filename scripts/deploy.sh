#!/bin/bash
# Options Wheel Strategy - Deployment Script
# Usage: ./scripts/deploy.sh [--test]

set -e

echo "🚀 Options Wheel Strategy Deployment"
echo "====================================="

# Check if we're in test mode
TEST_MODE=false
if [[ "$1" == "--test" ]]; then
    TEST_MODE=true
    echo "🧪 TEST MODE: Will perform dry-run validation only"
fi

# Configuration
PROJECT_ID="gen-lang-client-0607444019"
SERVICE_NAME="options-wheel-strategy"
REGION="us-central1"
IMAGE_NAME="us-central1-docker.pkg.dev/${PROJECT_ID}/options-wheel/options-wheel-strategy"

echo "📋 Configuration:"
echo "   Project: ${PROJECT_ID}"
echo "   Service: ${SERVICE_NAME}"
echo "   Region: ${REGION}"
echo "   Image: ${IMAGE_NAME}"

# Step 1: Run tests
echo ""
echo "🧪 Running tests..."
pytest tests/ -v || {
    echo "❌ Tests failed! Stopping deployment."
    exit 1
}
echo "✅ Tests passed"

# Step 2: Build and push container (if not test mode)
if [[ "$TEST_MODE" == "true" ]]; then
    echo "🏗️  Skipping container build (test mode)"
else
    echo ""
    echo "🏗️  Building and pushing container..."
    gcloud builds submit --tag "${IMAGE_NAME}" . || {
        echo "❌ Container build failed! Stopping deployment."
        exit 1
    }
    echo "✅ Container built and pushed"
fi

# Step 3: Deploy to Cloud Run (if not test mode)
if [[ "$TEST_MODE" == "true" ]]; then
    echo "🚀 Skipping deployment (test mode)"
else
    echo ""
    echo "🚀 Deploying to Cloud Run..."
    gcloud run deploy "${SERVICE_NAME}" \
        --image="${IMAGE_NAME}" \
        --region="${REGION}" \
        --memory=512Mi \
        --concurrency=10 \
        --max-instances=1 \
        --min-instances=0 \
        --timeout=300 || {
        echo "❌ Deployment failed!"
        exit 1
    }
    echo "✅ Deployed successfully"
fi

# Step 4: Test deployment
echo ""
echo "🔍 Testing deployment..."
sleep 10  # Wait for deployment to stabilize

if [[ "$TEST_MODE" == "true" ]]; then
    echo "🧪 Skipping deployment test (test mode)"
else
    python test_deployment.py || {
        echo "⚠️  Deployment test had issues. Check logs."
    }
fi

# Step 5: Health check
echo ""
echo "🏥 Running health monitor..."
python monitoring/health_monitor.py

echo ""
echo "🎉 Deployment complete!"
echo ""
echo "📝 Next steps:"
echo "   - Monitor logs: gcloud logging read 'resource.type=\"cloud_run_revision\"' --limit=10"
echo "   - Check service: gcloud run services describe ${SERVICE_NAME} --region=${REGION}"
echo "   - Review costs: Visit Google Cloud Console Billing"
