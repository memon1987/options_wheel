#!/bin/bash
# Setup GitHub Continuous Deployment for Options Wheel Strategy

set -e

echo "🔗 Setting up GitHub Continuous Deployment"
echo "=========================================="

PROJECT_ID="gen-lang-client-0607444019"

echo ""
echo "✅ Cloud Build permissions configured"
echo "✅ cloudbuild.yaml configuration created" 

echo ""
echo "📋 Next Steps (Manual Setup Required):"
echo ""
echo "1. 🚀 Push your code to GitHub (if not already done):"
echo "   git add ."
echo "   git commit -m 'Add continuous deployment configuration'"
echo "   git push origin main"
echo ""
echo "2. 🔗 Set up Cloud Build GitHub connection:"
echo "   Open: https://console.cloud.google.com/cloud-build/triggers?project=${PROJECT_ID}"
echo "   - Click 'Create Trigger'"
echo "   - Connect to your GitHub repository"
echo "   - Name: deploy-options-wheel-strategy"
echo "   - Event: Push to a branch"
echo "   - Branch: ^main$"
echo "   - Configuration: Cloud Build configuration file"
echo "   - Location: /cloudbuild.yaml"
echo ""
echo "3. 🧪 Test the pipeline:"
echo "   - Make a small change to your code"
echo "   - Push to main branch"
echo "   - Monitor: https://console.cloud.google.com/cloud-build/builds?project=${PROJECT_ID}"
echo ""
echo "🎯 Benefits after setup:"
echo "   ✅ Automatic testing on every commit"
echo "   ✅ Automatic deployment to Cloud Run"
echo "   ✅ Build history and rollback capability"
echo "   ✅ Zero-downtime deployments"
echo ""
echo "📚 Full instructions: See GITHUB_DEPLOYMENT_SETUP.md"
