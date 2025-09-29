# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an algorithmic trading solution that executes an options wheel strategy. The options wheel is a systematic approach to generating income from stocks through selling cash-secured puts and covered calls. All trade execution is handled through the Alpaca.py APIs.

## Development Setup

Install dependencies:
```bash
pip install -r requirements.txt
```

Set up environment:
```bash
cp .env.example .env
# Edit .env with your Alpaca API credentials
```

## Commands

**Run Strategy:**
```bash
python main.py --command run --dry-run  # Test mode
python main.py --command run            # Live execution
```

**Analysis Commands:**
```bash
python main.py --command scan    # Scan for opportunities
python main.py --command status  # Portfolio status  
python main.py --command report  # Performance report
```

**Testing:**
```bash
pytest tests/ -v                 # Run all tests
pytest tests/test_config.py -v   # Run specific test file
```

**Code Quality:**
```bash
black src/ tests/                # Format code
flake8 src/ tests/               # Check style
mypy src/                        # Type checking
```

## Architecture

**Core Strategy Flow:**
1. `WheelEngine` orchestrates the complete strategy
2. `MarketDataManager` analyzes stocks and options chains  
3. `OptionsScanner` identifies and ranks opportunities
4. `PutSeller`/`CallSeller` execute strategy-specific trades
5. `RiskManager` validates all positions against limits
6. `PortfolioTracker` monitors performance and generates reports

**Key Integration Points:**
- All market data flows through `AlpacaClient` wrapper
- Configuration centralized in `Config` class with YAML + env vars
- Risk validation required before any trade execution
- Structured logging throughout for debugging and audit trails

## Trading APIs

- **Alpaca API**: Primary API for all trade execution via custom AlpacaClient wrapper
- **Paper Trading**: Enabled by default at https://paper-api.alpaca.markets/v2
- **Options Trading**: Full support for cash-secured puts and covered calls
- **Real-time Data**: Stock quotes, options chains, and portfolio positions

## Key Components (Implemented)

- **WheelEngine** (`src/strategy/wheel_engine.py`): Core orchestrator for wheel strategy
- **PutSeller** (`src/strategy/put_seller.py`): Cash-secured put selling logic
- **CallSeller** (`src/strategy/call_seller.py`): Covered call selling logic  
- **AlpacaClient** (`src/api/alpaca_client.py`): API wrapper for trading operations
- **MarketDataManager** (`src/api/market_data.py`): Options chain analysis and filtering
- **RiskManager** (`src/risk/risk_manager.py`): Position validation and risk controls
- **PortfolioTracker** (`src/data/portfolio_tracker.py`): Performance monitoring
- **OptionsScanner** (`src/data/options_scanner.py`): Opportunity identification
- **Config** (`src/utils/config.py`): Centralized configuration management

## Strategy Configuration

**Short-Term Focus**: 7-day maximum expiration for rapid theta decay
**Conservative Deltas**: 0.10-0.20 range for ~10-20% assignment probability
**Assignment Strategy**: Take assignment on puts (no stop losses), protect calls
**Position Sizing**: Maximum 1 contract per new position, 10% portfolio allocation

## Risk Management Philosophy

**Puts**: No stop losses - designed to take assignment on quality stocks
- Assignment probability ≈ |Delta| (10-20% for our range)
- Keep full premium on 80-90% of positions
- Take assignment on remaining 10-20% at favorable prices

**Calls**: Protected with stop losses adjusted for time decay
- 75% loss threshold (50% base × 1.5 multiplier) accounts for theta
- Delta > 0.5 triggers immediate exit (likely ITM)
- Prevents unlimited upside risk on covered positions

## Data Analysis Policy

**IMPORTANT: Cloud-First Data Analysis**
- For ALL data analysis requests, ONLY use data stored on Google Cloud Platform
- DO NOT analyze local files, local backtest results, or local cache data
- Primary data sources for analysis:
  - Google Cloud Storage: `gs://gen-lang-client-0607444019-options-data/`
  - Cloud Run API endpoints: Dashboard and backtest history endpoints
  - Cloud-based backtesting results and performance metrics
- If cloud data is not available, request user to trigger cloud-based backtesting first
- This ensures analysis reflects production-ready, persistent, and centralized data

## Development Notes

**Alpaca Setup**: Requires options trading approval and paper trading endpoint
**Testing**: Comprehensive test suite in `/tests` directory
**Logging**: Structured logging with structlog for trade audit trails
**Configuration**: YAML-based settings with environment variable substitution