# 🚀 Cloud Deployment Guide

Complete guide for deploying the Options Wheel Strategy in various cloud environments.

## 📋 Prerequisites

### Required Accounts & Access
- **Alpaca Trading Account** with options trading enabled
- **Cloud Provider Account** (AWS, GCP, Azure, or DigitalOcean)
- **Docker** installed locally (for building images)
- **kubectl** (for Kubernetes deployments)

### API Keys & Credentials
- Alpaca API Key and Secret
- Cloud provider credentials
- Optional: Slack webhook for alerts
- Optional: Email credentials for notifications

## 🐳 Docker Deployment

### Quick Start with Docker Compose

1. **Clone and prepare environment:**
```bash
git clone <your-repo>
cd options_wheel-1
cp .env.example .env
```

2. **Configure your credentials in `.env`:**
```bash
# Required
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_SECRET_KEY=your_alpaca_secret_key
ALPACA_PAPER_TRADING=true

# Optional customizations
EXECUTION_GAP_THRESHOLD=1.5
QUALITY_GAP_THRESHOLD=2.0
LOG_LEVEL=INFO
```

3. **Launch the strategy:**
```bash
# Basic deployment
docker-compose up -d

# With Redis caching
docker-compose --profile with-cache up -d

# With PostgreSQL logging
docker-compose --profile with-db up -d

# Full stack
docker-compose --profile with-cache --profile with-db up -d
```

4. **Monitor logs:**
```bash
docker-compose logs -f options-wheel
```

### Manual Docker Deployment

```bash
# Build image
docker build -t options-wheel:latest .

# Run container
docker run -d \
  --name options-wheel-strategy \
  -e ALPACA_API_KEY=your_key \
  -e ALPACA_SECRET_KEY=your_secret \
  -e ALPACA_PAPER_TRADING=true \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/config:/app/config \
  options-wheel:latest
```

## ☸️ Kubernetes Deployment

### 1. Prepare Secrets

```bash
# Create namespace
kubectl create namespace trading

# Create secret with your Alpaca credentials
kubectl create secret generic alpaca-credentials \
  --from-literal=api-key=your_alpaca_api_key \
  --from-literal=secret-key=your_alpaca_secret_key \
  -n trading
```

### 2. Deploy Application

```bash
# Apply Kubernetes manifests
kubectl apply -f kubernetes/deployment.yaml -n trading

# Check deployment status
kubectl get pods -n trading
kubectl logs -f deployment/options-wheel-strategy -n trading
```

### 3. Update Configuration

```bash
# Edit ConfigMap for strategy parameters
kubectl edit configmap options-wheel-config -n trading

# Restart deployment to pick up changes
kubectl rollout restart deployment/options-wheel-strategy -n trading
```

## ☁️ Cloud Provider Specific Deployments

### AWS ECS Deployment

1. **Create ECR repository:**
```bash
aws ecr create-repository --repository-name options-wheel
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com
```

2. **Build and push image:**
```bash
docker build -t options-wheel .
docker tag options-wheel:latest <account>.dkr.ecr.us-east-1.amazonaws.com/options-wheel:latest
docker push <account>.dkr.ecr.us-east-1.amazonaws.com/options-wheel:latest
```

3. **Create ECS task definition:**
```json
{
  "family": "options-wheel-strategy",
  "taskRoleArn": "arn:aws:iam::<account>:role/ecsTaskRole",
  "executionRoleArn": "arn:aws:iam::<account>:role/ecsTaskExecutionRole",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "containerDefinitions": [
    {
      "name": "options-wheel",
      "image": "<account>.dkr.ecr.us-east-1.amazonaws.com/options-wheel:latest",
      "environment": [
        {"name": "ALPACA_PAPER_TRADING", "value": "true"},
        {"name": "LOG_LEVEL", "value": "INFO"}
      ],
      "secrets": [
        {
          "name": "ALPACA_API_KEY",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:<account>:secret:alpaca-credentials:api-key::"
        },
        {
          "name": "ALPACA_SECRET_KEY",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:<account>:secret:alpaca-credentials:secret-key::"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/options-wheel",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

### Google Cloud Run Deployment

1. **Build and push to GCR:**
```bash
gcloud builds submit --tag gcr.io/your-project/options-wheel
```

2. **Deploy to Cloud Run:**
```bash
gcloud run deploy options-wheel-strategy \
  --image gcr.io/your-project/options-wheel \
  --platform managed \
  --region us-central1 \
  --set-env-vars ALPACA_PAPER_TRADING=true \
  --set-secrets ALPACA_API_KEY=alpaca-api-key:latest \
  --set-secrets ALPACA_SECRET_KEY=alpaca-secret-key:latest \
  --no-allow-unauthenticated \
  --memory 1Gi \
  --cpu 1
```

### Azure Container Instances

```bash
# Create resource group
az group create --name options-wheel-rg --location eastus

# Deploy container
az container create \
  --resource-group options-wheel-rg \
  --name options-wheel-strategy \
  --image options-wheel:latest \
  --cpu 1 \
  --memory 1 \
  --environment-variables ALPACA_PAPER_TRADING=true LOG_LEVEL=INFO \
  --secure-environment-variables ALPACA_API_KEY=your_key ALPACA_SECRET_KEY=your_secret \
  --restart-policy Always
```

## 📊 Scheduling & Automation

### Using the Built-in Scheduler

The application includes a built-in scheduler that handles market hours and trading cycles:

```bash
# Run with scheduler (default mode)
python scripts/scheduler.py

# Test mode (single cycle)
python scripts/scheduler.py test

# Report only
python scripts/scheduler.py report
```

### Cron-based Scheduling

For simpler deployments, use cron for scheduling:

```bash
# Edit crontab
crontab -e

# Add trading schedule (Eastern Time)
# Pre-market scan at 8:00 AM ET
0 8 * * 1-5 /usr/local/bin/docker exec options-wheel-strategy python main.py --command scan

# Position management at 11:00 AM, 1:00 PM, 3:00 PM ET
0 11,13,15 * * 1-5 /usr/local/bin/docker exec options-wheel-strategy python main.py --command run

# End-of-day report at 4:30 PM ET
30 16 * * 1-5 /usr/local/bin/docker exec options-wheel-strategy python main.py --command report
```

### Kubernetes CronJobs

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: options-wheel-morning-scan
spec:
  schedule: "0 13 * * 1-5"  # 9:00 AM ET (UTC-4)
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: options-wheel
            image: options-wheel:latest
            command: ["python", "main.py", "--command", "scan"]
            envFrom:
            - secretRef:
                name: alpaca-credentials
          restartPolicy: OnFailure
```

## 📈 Monitoring & Alerting

### Health Checks

```bash
# Manual health check
python scripts/monitoring.py health

# Test alerts
python scripts/monitoring.py test-alert
```

### Slack Integration

1. **Create Slack webhook:**
   - Go to your Slack workspace settings
   - Create an incoming webhook
   - Copy the webhook URL

2. **Configure webhook:**
```bash
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK
```

### Email Alerts

```bash
export EMAIL_SMTP_SERVER=smtp.gmail.com
export EMAIL_USERNAME=your_email@gmail.com
export EMAIL_PASSWORD=your_app_password
```

### Prometheus Metrics

The application exposes metrics at `/metrics` endpoint when running with monitoring enabled:

```bash
# Enable metrics
export ENABLE_METRICS=true
export METRICS_PORT=8080

# Scrape metrics
curl http://localhost:8080/metrics
```

## 🔒 Security Best Practices

### Environment Variables
- **Never** commit credentials to git
- Use cloud provider secret management services
- Rotate API keys regularly

### Container Security
- Run as non-root user (already configured)
- Use minimal base images
- Scan images for vulnerabilities
- Keep dependencies updated

### Network Security
- Use private networks where possible
- Implement proper firewall rules
- Enable TLS for all communications

## 🔧 Configuration Management

### Environment-Specific Configs

Create separate configuration files for different environments:

```bash
# Development
config/settings-dev.yaml

# Staging
config/settings-staging.yaml

# Production
config/settings-prod.yaml
```

### Runtime Configuration Override

Use environment variables to override specific settings:

```bash
# Override gap thresholds
export EXECUTION_GAP_THRESHOLD=1.0
export QUALITY_GAP_THRESHOLD=1.5

# Override position limits
export MAX_POSITIONS=5
export MAX_EXPOSURE_PER_TICKER=25000
```

## 🚨 Troubleshooting

### Common Issues

1. **API Connection Failures:**
```bash
# Check credentials
python scripts/monitoring.py health

# Test API connectivity
python scripts/check_api_connection.py
```

2. **Market Data Issues:**
```bash
# Verify market hours
python -c "from scripts.scheduler import StrategyScheduler; print(StrategyScheduler().is_market_open())"
```

3. **Permission Errors:**
```bash
# Fix file permissions
chmod +x scripts/*.py
chown -R trader:trader /app
```

### Log Analysis

```bash
# View recent logs
docker-compose logs --tail=100 options-wheel

# Search for errors
docker-compose logs options-wheel | grep ERROR

# Monitor real-time
docker-compose logs -f options-wheel
```

## 📚 Scaling Considerations

### Horizontal Scaling
- Use Redis for shared state if running multiple instances
- Implement leader election for trade execution
- Consider event-driven architecture

### Performance Optimization
- Enable caching for market data
- Use connection pooling
- Optimize database queries if using PostgreSQL

### Cost Optimization
- Use spot instances where appropriate
- Implement auto-scaling based on market hours
- Monitor resource usage and right-size instances

## 🔄 Maintenance

### Updates & Deployments

```bash
# Zero-downtime deployment
docker-compose pull
docker-compose up -d

# Kubernetes rolling update
kubectl set image deployment/options-wheel-strategy options-wheel=options-wheel:v1.1
```

### Backup & Recovery

```bash
# Backup configuration
kubectl get configmap options-wheel-config -o yaml > backup-config.yaml

# Backup logs
docker cp options-wheel-strategy:/app/logs ./logs-backup
```

---

## 📞 Support

For issues or questions:
1. Check logs first
2. Run health checks
3. Review configuration
4. Check network connectivity
5. Verify market hours

The deployment is designed to be robust and self-healing, with comprehensive monitoring and alerting to ensure reliable operation in production environments.