# Cloud Run Cost Optimization Summary

## Current Configuration (Optimized)

### Cloud Run Service Resources
- **CPU**: 1 vCPU (required for service stability)
- **Memory**: 512 MiB (reduced from 1 GiB - 50% savings)
- **Concurrency**: 10 requests (sufficient for scheduled jobs)
- **Max Instances**: 1 (prevents unexpected scaling costs)
- **Min Instances**: 0 (scales to zero when inactive)

### Cost Breakdown (Estimated Monthly)

**Cloud Run Pricing (us-central1):**
- CPU: $0.00002400 per vCPU-second
- Memory: $0.00000250 per GiB-second
- Requests: $0.40 per million requests

**Expected Usage:**
- 3 scheduled executions per trading day
- ~22 trading days per month = 66 executions
- ~30 seconds execution time per run
- Plus health checks and manual triggers

**Monthly Cost Estimate:**
- CPU Usage: 66 runs × 30 sec × $0.024/sec = ~$0.05
- Memory Usage: 66 runs × 30 sec × 0.5 GiB × $0.0025/sec = ~$0.002
- Request Charges: ~200 requests × $0.40/1M = negligible
- **Total: ~$0.10-0.20 per month**

### Additional Google Cloud Costs

**Secret Manager:**
- 2 active secrets: ~$0.12/month
- API calls: negligible for our usage

**Cloud Scheduler:**
- 3 scheduled jobs: ~$0.30/month

**Cloud Logging:**
- Expected logs: <1 GB/month = free tier

**Artifact Registry:**
- Container storage: ~$0.10/month

**Total Estimated Monthly Cost: $0.60-0.80**

## Cost Optimization Features Implemented

1. **Scale-to-Zero**: Service automatically scales down when not in use
2. **Reduced Memory**: 50% memory reduction (1 GiB → 512 MiB)
3. **Limited Concurrency**: Prevents unnecessary parallel processing
4. **Single Instance Limit**: Prevents accidental scaling
5. **Efficient Scheduling**: Only 3 executions per trading day

## Additional Cost Optimization Opportunities

1. **Use Startup CPU Boost**: Already enabled for faster cold starts
2. **Optimize Container Image**: Current image is reasonably sized
3. **Efficient Logging**: Log only essential information
4. **Regional Deployment**: Already using cost-effective us-central1

## Monitoring Cost Efficiency

### Key Metrics to Watch:
- Instance start count (should be ~66/month)
- Average execution time (target: <30 seconds)
- Memory utilization (should be <512 MiB)
- Request count (should be minimal outside scheduled jobs)

### Cost Alerts Recommended:
```bash
# Set up billing alerts for unexpected charges
gcloud alpha billing budgets create \\
  --billing-account=[BILLING_ACCOUNT] \\
  --display-name="Options Wheel Budget" \\
  --budget-amount=10 \\
  --threshold-rule=percent:50 \\
  --threshold-rule=percent:90
```

## Performance vs. Cost Trade-offs

**Current Settings Optimize For:**
- ✅ Cost efficiency (scale-to-zero)
- ✅ Predictable billing
- ✅ Adequate performance for scheduled tasks
- ✅ Cold start mitigation with startup CPU boost

**Trade-offs Accepted:**
- Slightly longer cold start times (mitigated by CPU boost)
- Limited concurrent request handling (not needed for our use case)
- Manual scaling for high-frequency trading (not our use case)

---

*Optimized for automated options wheel strategy with minimal cloud costs*
*Expected monthly cost: <$1.00 including all Google Cloud services*