# GitHub Continuous Deployment Setup

## Overview
This guide sets up automatic deployment from GitHub to Google Cloud Run. When you push code to your GitHub repository, it will automatically build, test, and deploy your options wheel strategy.

## Step 1: Push Your Code to GitHub (If Not Already Done)

```bash
# Initialize git repository (if not already done)
git init
git add .
git commit -m "Initial commit: Complete options wheel strategy with cloud deployment"

# Add your GitHub repository as remote
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
git branch -M main
git push -u origin main
```

## Step 2: Set Up Cloud Build GitHub Connection

**⚠️ This requires manual steps in Google Cloud Console:**

1. **Go to Cloud Build Triggers**:
   ```
   https://console.cloud.google.com/cloud-build/triggers?project=gen-lang-client-0607444019
   ```

2. **Click "Create Trigger"**

3. **Connect Repository**:
   - Source: Select "GitHub (Cloud Build GitHub App)"
   - Click "Connect Repository"
   - Follow the GitHub OAuth flow to authorize Google Cloud Build
   - Select your repository: `YOUR_USERNAME/options_wheel-1` (or your repo name)

4. **Configure Trigger Settings**:
   ```
   Name: deploy-options-wheel-strategy
   Description: Deploy options wheel strategy on push to main
   Event: Push to a branch
   Source: 1st gen
   Repository: YOUR_USERNAME/options_wheel-1
   Branch: ^main$
   Configuration: Cloud Build configuration file (yaml or json)
   Cloud Build configuration file location: /cloudbuild.yaml
   ```

5. **Click "Create"**

## Step 3: Grant Cloud Build Permissions

Run these commands to give Cloud Build the necessary permissions:

```bash
# Get the Cloud Build service account
PROJECT_NUMBER=$(gcloud projects describe gen-lang-client-0607444019 --format="value(projectNumber)")
CLOUD_BUILD_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

# Grant Cloud Run Developer role
gcloud projects add-iam-policy-binding gen-lang-client-0607444019 \
    --member="serviceAccount:${CLOUD_BUILD_SA}" \
    --role="roles/run.developer"

# Grant Service Account User role (to deploy Cloud Run services)
gcloud projects add-iam-policy-binding gen-lang-client-0607444019 \
    --member="serviceAccount:${CLOUD_BUILD_SA}" \
    --role="roles/iam.serviceAccountUser"

# Grant Artifact Registry Writer role (already granted, but confirming)
gcloud projects add-iam-policy-binding gen-lang-client-0607444019 \
    --member="serviceAccount:${CLOUD_BUILD_SA}" \
    --role="roles/artifactregistry.writer"
```

## Step 4: Test the Pipeline

After setting up the trigger:

1. **Make a small change** to your code (e.g., update a comment)
2. **Commit and push**:
   ```bash
   git add .
   git commit -m "Test: Trigger continuous deployment"
   git push origin main
   ```
3. **Monitor the build**:
   - Go to [Cloud Build History](https://console.cloud.google.com/cloud-build/builds?project=gen-lang-client-0607444019)
   - Watch your build progress
   - Build should complete in ~5-10 minutes

## What Happens During Each Build

The `cloudbuild.yaml` file defines these steps:

1. **🧪 Run Tests**: Validates all tests pass before building
2. **🏗️ Build Image**: Creates container image with latest code
3. **📤 Push Image**: Uploads to Artifact Registry with commit SHA tag
4. **🚀 Deploy**: Updates Cloud Run service with new image
5. **✅ Health Check**: Verifies deployment succeeded

## Build Triggers

**Automatic Triggers**:
- ✅ Push to `main` branch
- ✅ Pull request merge to `main`

**Manual Triggers** (in Cloud Console):
- You can manually trigger builds from the Cloud Build console
- Useful for testing without code changes

## Monitoring Builds

**View Build Status**:
```bash
# List recent builds
gcloud builds list --limit=5

# View specific build logs
gcloud builds log BUILD_ID
```

**Build Notifications** (Optional):
- Set up Slack/email notifications for build success/failure
- Configure in Cloud Build settings

## Security Considerations

✅ **Safe Deployment**:
- All builds run tests first - deployment fails if tests fail
- Paper trading mode enforced via environment variable
- No secrets in repository (stored in Secret Manager)
- Immutable container tags with commit SHA

✅ **Branch Protection**:
- Consider requiring pull request reviews for `main` branch
- Set up branch protection rules in GitHub

## Cost Impact

**Build Costs**:
- ~$0.003 per build minute
- Expected 5-10 minutes per build
- ~$0.02-0.05 per deployment
- Still well under $1/month total

## Troubleshooting

**Build Fails**:
1. Check build logs in Cloud Build console
2. Verify all tests pass locally: `pytest tests/ -v`
3. Check Dockerfile builds locally: `docker build -t test .`

**Permission Errors**:
1. Verify Cloud Build service account has correct roles
2. Check Secret Manager access if deployment fails

**Deployment Issues**:
1. Monitor Cloud Run logs after deployment
2. Run health monitor: `python monitoring/health_monitor.py`

---

## 🎉 Benefits of Continuous Deployment

✅ **Automated Testing**: Every deploy runs your full test suite
✅ **Consistent Builds**: Same environment every time
✅ **Fast Iteration**: Push code → automatic deployment in minutes
✅ **Rollback Capability**: Each deployment tagged with commit SHA
✅ **Audit Trail**: Full build history and logs
✅ **Zero Downtime**: Rolling deployments to Cloud Run

Your options wheel strategy now has professional-grade CI/CD! 🚀