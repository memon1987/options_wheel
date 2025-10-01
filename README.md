# Options Wheel Trading Strategy

[![Cloud Run](https://img.shields.io/badge/Google%20Cloud-Run-blue)](https://cloud.google.com/run)
[![Python](https://img.shields.io/badge/Python-3.11+-green)](https://python.org)
[![License](https://img.shields.io/badge/License-Private-red)]()

## Overview

A fully automated options wheel trading strategy deployed on Google Cloud Run with comprehensive risk management, gap detection, and continuous deployment.

## 🚀 Quick Start

### Cloud Deployment (Production)
The strategy runs automatically on Google Cloud:
- **Service URL**: https://options-wheel-strategy-omnlacz6ia-uc.a.run.app
- **Schedule**: 9 AM, 12 PM, 3 PM ET (market hours)
- **Mode**: Paper trading (safe default)

### Local Development
```bash
# Clone and setup
git clone https://github.com/memon1987/options_wheel.git
cd options_wheel

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Alpaca API credentials

# Run strategy
python main.py --command scan --dry-run
```

## 📁 Project Structure

```
├── src/                    # Core strategy code (production)
│   ├── strategy/          # Options wheel implementation
│   ├── risk/              # Risk management and gap detection
│   ├── api/               # Alpaca API integration
│   ├── backtesting/       # Backtesting framework
│   ├── data/              # Data management and scanning
│   └── utils/             # Configuration and utilities
│
├── deploy/                # Cloud deployment configuration
│   ├── cloud_run_server.py # Production web server
│   ├── monitoring/        # Health checks and performance dashboard
│   └── kubernetes/        # K8s configs (optional)
│
├── scripts/               # Standalone utility scripts
│   └── testing/           # Manual test scripts (test_*.py)
│
├── tools/                 # Operational tools
│   ├── backtesting/       # Backtest runners
│   ├── deployment/        # Deployment utilities
│   ├── monitoring/        # Emergency stop, maintenance
│   └── testing/           # Integration test utilities
│
├── tests/                 # Unit tests (pytest)
├── config/                # Strategy configuration (settings.yaml)
├── docs/                  # Documentation
├── examples/              # Example usage and demos
├── research/              # Experimental features
│   └── experiments/       # Active research projects
│
├── main.py                # Local entry point
├── setup.py               # Package setup
└── cloudbuild.yaml        # CI/CD pipeline
```

## 🎯 Strategy Features

### Options Wheel Implementation
- **Cash-secured puts** → Assignment → **Covered calls**
- **7-day DTE** for rapid theta decay
- **Conservative deltas** (0.10-0.20) for controlled risk
- **Quality stock universe** (AAPL, MSFT, GOOGL, etc.)

### Advanced Risk Management
- **Multi-layer gap protection** prevents overnight volatility exposure
- **Historical gap analysis** filters volatile stocks
- **Real-time execution controls** block trades during gaps
- **Conservative position sizing** with portfolio allocation limits

### Cloud Infrastructure
- **Serverless deployment** with scale-to-zero cost optimization
- **Automated CI/CD** with testing and deployment pipeline
- **Comprehensive monitoring** with health checks and alerting
- **Enterprise security** with secret management and authentication

## 🛠️ Development

### Scripts
```bash
# Deployment
./tools/scripts/deploy.sh              # Deploy to production
./tools/scripts/deploy.sh --test       # Test deployment

# Maintenance
./tools/scripts/maintenance.sh daily   # Daily health check
./tools/scripts/maintenance.sh weekly  # Weekly review
./tools/scripts/maintenance.sh monthly # Monthly analysis

# Emergency controls
./tools/scripts/emergency_stop.sh      # Stop all trading
./tools/scripts/resume_trading.sh      # Resume operations
```

### Testing
```bash
# Run test suite
pytest tests/ -v

# Test specific modules
pytest tests/test_config.py -v
pytest tests/test_risk_manager.py -v

# Test deployment
python tools/test_deployment.py
```

### Monitoring
```bash
# Health check
python deploy/monitoring/health_monitor.py

# Build monitoring
python tools/monitor_build.py
```

## 📊 Configuration

Strategy parameters are configured in `config/settings.yaml`:

- **Target DTE**: 7 days for rapid theta decay
- **Delta ranges**: 0.10-0.20 for puts and calls
- **Position sizing**: Max $25K exposure per ticker
- **Gap controls**: 2% execution threshold with 30-day analysis
- **Stock universe**: High-quality, liquid stocks only

## 🔐 Security

- **Paper trading by default** for safety
- **API credentials** stored in Google Secret Manager
- **Authenticated endpoints** with OIDC tokens
- **No secrets in repository** - all sensitive data externalized

## 📈 Performance

### Expected Costs
- **Monthly cloud costs**: <$1.00
- **Resource usage**: 512MB memory, scale-to-zero
- **Build time**: 7-13 minutes per deployment

### Monitoring Metrics
- Execution success rates
- Position P&L tracking
- Gap detection accuracy
- API response times

## 🚨 Emergency Procedures

**Stop Trading Immediately**:
```bash
./tools/scripts/emergency_stop.sh
```

**Resume Trading**:
```bash
./tools/scripts/resume_trading.sh
```

**Check Health**:
```bash
python deploy/monitoring/health_monitor.py
```

## 📚 Documentation

- [`docs/DEPLOYMENT_SUMMARY.md`](docs/DEPLOYMENT_SUMMARY.md) - Complete deployment guide
- [`docs/PRODUCTION_CONFIG.md`](docs/PRODUCTION_CONFIG.md) - Strategy configuration details
- [`docs/MAINTENANCE.md`](docs/MAINTENANCE.md) - Operations procedures
- [`docs/GITHUB_DEPLOYMENT_SETUP.md`](docs/GITHUB_DEPLOYMENT_SETUP.md) - CI/CD setup guide

## 🎯 Next Steps

1. **Monitor paper trading** for 4-6 weeks
2. **Review gap detection** during volatile periods
3. **Analyze performance metrics** and adjust parameters
4. **Consider live trading** after thorough validation

## ⚡ Quick Commands

```bash
# Check service status
curl https://options-wheel-strategy-omnlacz6ia-uc.a.run.app/health

# Manual strategy execution
python main.py --command run --dry-run

# View recent logs
gcloud logging read 'resource.type="cloud_run_revision"' --limit=10

# Monitor builds
gcloud builds list --limit=5
```

---

**Status**: ✅ Production Ready - Paper Trading Active
**Deployed**: Google Cloud Run with automated CI/CD
**Next Review**: Monitor for 4-6 weeks before live trading consideration

*Built with ❤️ using Claude Code*