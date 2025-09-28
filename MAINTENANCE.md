# Maintenance and Update Procedures

## Regular Maintenance Tasks

### Daily (Automated)
- ✅ Strategy executions via Cloud Scheduler (9 AM, 12 PM, 3 PM ET)
- ✅ Health monitoring via application logs
- ✅ Position monitoring and gap risk checks

### Weekly (Manual)
1. **Review Health Monitor Output**:
   ```bash
   python monitoring/health_monitor.py
   ```

2. **Check Service Performance**:
   ```bash
   gcloud run services describe options-wheel-strategy --region=us-central1
   ```

3. **Review Logs for Errors**:
   ```bash
   gcloud logging read 'resource.type="cloud_run_revision" AND severity>=WARNING' --limit=20 --format="table(timestamp,severity,textPayload)"
   ```

### Monthly (Manual)
1. **Performance Review**: Analyze execution times and success rates
2. **Cost Review**: Monitor billing and resource usage
3. **Strategy Review**: Evaluate P&L and position management
4. **Dependency Updates**: Check for critical security updates

## Update Procedures

### Strategy Configuration Updates

1. **Update settings.yaml**:
   ```bash
   # Edit configuration locally
   nano config/settings.yaml

   # Test changes locally first
   python main.py --command scan --dry-run
   ```

2. **Deploy Configuration Changes**:
   ```bash
   # Rebuild and push container
   gcloud builds submit --tag us-central1-docker.pkg.dev/gen-lang-client-0607444019/options-wheel/options-wheel-strategy .

   # Update Cloud Run service
   gcloud run deploy options-wheel-strategy --region=us-central1 --image=us-central1-docker.pkg.dev/gen-lang-client-0607444019/options-wheel/options-wheel-strategy
   ```

### Code Updates and Bug Fixes

1. **Development Workflow**:
   ```bash
   # Create feature branch
   git checkout -b fix/issue-description

   # Make changes and test locally
   pytest tests/ -v
   python main.py --command scan --dry-run

   # Commit changes
   git add .
   git commit -m "Fix: Description of changes"
   ```

2. **Deployment Workflow**:
   ```bash
   # Build and test container locally
   docker build -t options-wheel-test .
   docker run --rm options-wheel-test python -c "from src.utils.config import Config; Config()"

   # Deploy to production
   gcloud builds submit --tag us-central1-docker.pkg.dev/gen-lang-client-0607444019/options-wheel/options-wheel-strategy .
   gcloud run deploy options-wheel-strategy --region=us-central1

   # Test deployment
   python test_deployment.py
   ```

### Emergency Procedures

#### Service Failure
1. **Check Service Status**:
   ```bash
   gcloud run services describe options-wheel-strategy --region=us-central1
   ```

2. **Review Recent Logs**:
   ```bash
   gcloud logging read 'resource.type="cloud_run_revision"' --limit=50 --format="table(timestamp,severity,textPayload)"
   ```

3. **Restart Service** (if needed):
   ```bash
   gcloud run services update options-wheel-strategy --region=us-central1 --update-env-vars=RESTART_TIMESTAMP=$(date +%s)
   ```

#### Stop All Trading (Emergency)
1. **Disable Scheduled Jobs**:
   ```bash
   gcloud scheduler jobs pause morning-market-scan --location=us-central1
   gcloud scheduler jobs pause midday-strategy-execution --location=us-central1
   gcloud scheduler jobs pause afternoon-position-check --location=us-central1
   ```

2. **Force Paper Trading Mode**:
   ```bash
   gcloud run services update options-wheel-strategy --region=us-central1 --update-env-vars=ALPACA_PAPER_TRADING=true
   ```

#### Resume Operations
1. **Re-enable Scheduled Jobs**:
   ```bash
   gcloud scheduler jobs resume morning-market-scan --location=us-central1
   gcloud scheduler jobs resume midday-strategy-execution --location=us-central1
   gcloud scheduler jobs resume afternoon-position-check --location=us-central1
   ```

## Monitoring and Alerting

### Key Metrics to Monitor
- Service availability and response times
- Execution success rates
- Position changes and P&L
- Gap risk events and stops
- API rate limits and errors

### Health Check Endpoints
- `GET /health` - Comprehensive health status
- `GET /status` - Strategy and position status
- `GET /config` - Configuration validation

### Log Analysis Queries
```bash
# Check for authentication errors
gcloud logging read 'resource.type="cloud_run_revision" AND textPayload:"401"' --limit=10

# Monitor execution times
gcloud logging read 'resource.type="cloud_run_revision" AND textPayload:"execution_time"' --limit=10

# Check for gap events
gcloud logging read 'resource.type="cloud_run_revision" AND textPayload:"gap"' --limit=10

# Monitor position changes
gcloud logging read 'resource.type="cloud_run_revision" AND textPayload:"position"' --limit=10
```

## Security Maintenance

### API Key Rotation
1. **Update Alpaca Keys**:
   ```bash
   # Update secret in Secret Manager
   echo "NEW_API_KEY" | gcloud secrets versions add alpaca-api-key --data-file=-
   echo "NEW_SECRET_KEY" | gcloud secrets versions add alpaca-secret-key --data-file=-

   # Restart service to pick up new keys
   gcloud run services update options-wheel-strategy --region=us-central1 --update-env-vars=KEY_ROTATION=$(date +%s)
   ```

### Access Review
- Quarterly review of IAM permissions
- Monitor service account usage
- Audit Cloud Run access logs

## Backup and Recovery

### Configuration Backup
```bash
# Backup current configuration
gcloud run services describe options-wheel-strategy --region=us-central1 --format="export" > backup/service-config-$(date +%Y%m%d).yaml
cp config/settings.yaml backup/settings-$(date +%Y%m%d).yaml
```

### Recovery Procedures
```bash
# Restore from backup
gcloud run services replace backup/service-config-YYYYMMDD.yaml --region=us-central1
```

## Troubleshooting Guide

### Common Issues

**Service Won't Start**:
- Check environment variables and secrets
- Verify container image build succeeded
- Review startup logs for import errors

**Scheduled Jobs Failing**:
- Verify IAM permissions for service account
- Check OIDC token configuration
- Test manual job execution

**High Error Rates**:
- Check Alpaca API status and rate limits
- Verify market data availability
- Review gap detection thresholds

**Performance Issues**:
- Monitor memory usage and consider scaling
- Check API response times
- Review position scan complexity

---

*Last Updated: Production deployment complete*
*Maintained by: Options Wheel Strategy Team*