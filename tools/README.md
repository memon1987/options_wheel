# Tools Directory

This directory contains all development, testing, deployment, and monitoring tools for the Options Wheel Strategy project.

## Directory Structure

### 📊 `/backtesting/`
**Backtesting and analysis tools**
- `backtest_runner.py` - Comprehensive backtesting engine with CLI interface
- `demo_backtest.py` - Simple backtesting demonstration and examples
- `scheduled_backtest.py` - Automated backtesting for Cloud Scheduler integration

### 🚀 `/deployment/`
**Deployment and infrastructure management**
- `deploy.sh` - Main deployment script for Cloud Run
- `setup_backtesting_schedule.sh` - Configure automated backtesting jobs
- `setup_github_deployment.sh` - Configure GitHub Actions CI/CD
- `setup_scheduled_backtesting.sh` - Legacy scheduler setup (use setup_backtesting_schedule.sh)
- `scheduler.py` - Cloud Scheduler job management utilities

### 🛠️ `/development/`
**Development and debugging tools**
- `monitor_build.py` - Real-time Cloud Build monitoring
- `watch_logs.sh` - Real-time log monitoring for Cloud Run

### 📈 `/monitoring/`
**Operational monitoring and management**
- `emergency_stop.sh` - Emergency trading halt procedures
- `maintenance.sh` - System maintenance and cleanup tasks
- `resume_trading.sh` - Resume trading after maintenance
- `monitoring.py` - System health monitoring utilities

### 🧪 `/testing/`
**Testing and validation tools**
- `test_endpoints.sh` - Comprehensive API endpoint testing
- `test_deployment.py` - Deployment validation and health checks
- `test_dashboard_local.py` - Local dashboard functionality testing
- `test_installation.py` - Installation and setup verification
- `check_options_status.py` - Options trading status validation
- `check_api_connection.py` - API connectivity testing

## Quick Reference

### Most Used Commands

**Development:**
```bash
# Monitor builds in real-time
python tools/development/monitor_build.py

# Watch logs
./tools/development/watch_logs.sh

# Test all endpoints
./tools/testing/test_endpoints.sh
```

**Deployment:**
```bash
# Deploy to Cloud Run
./tools/deployment/deploy.sh

# Setup backtesting schedule
./tools/deployment/setup_backtesting_schedule.sh
```

**Backtesting:**
```bash
# Run comprehensive backtest
python tools/backtesting/backtest_runner.py --symbol AAPL --days 30

# Demo backtesting
python tools/backtesting/demo_backtest.py
```

**Monitoring:**
```bash
# Emergency stop trading
./tools/monitoring/emergency_stop.sh

# System maintenance
./tools/monitoring/maintenance.sh
```

## Integration with Main Project

All tools are designed to work with the main project structure:
- **Configuration**: Uses `config/settings.yaml`
- **Source Code**: Imports from `src/` directory
- **Results**: Outputs to `backtest_results/` directory
- **Logs**: Integrates with structured logging system

## Cloud Integration

These tools are integrated with:
- **Google Cloud Run** - Primary deployment platform
- **Cloud Scheduler** - Automated job execution
- **Cloud Storage** - Data persistence and caching
- **Cloud Build** - CI/CD pipeline
- **Cloud Logging** - Centralized logging

For more information, see the main project README.md and individual tool documentation.