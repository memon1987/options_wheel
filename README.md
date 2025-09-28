# Options Wheel Strategy

An algorithmic trading system that implements the options wheel strategy using the Alpaca API. The wheel strategy involves selling cash-secured puts and, when assigned, selling covered calls to generate consistent income from options premiums.

## Overview

The options wheel strategy consists of three main phases:
1. **Cash-Secured Puts**: Sell put options on quality stocks to collect premium
2. **Assignment**: If assigned, acquire stocks at the put strike price
3. **Covered Calls**: Sell call options against the assigned stock position

This system automates the entire process with comprehensive risk management and performance tracking.

## Features

### Live Trading
- **Automated Options Scanning**: Find the best put and call opportunities
- **Risk Management**: Position sizing, portfolio allocation limits, and stop losses
- **Real-time Monitoring**: Track positions and performance continuously
- **Paper Trading Support**: Test strategies safely with Alpaca's paper trading
- **Comprehensive Reporting**: Detailed performance analytics and trade history
- **Configurable Parameters**: Customize strategy settings via YAML configuration

### Backtesting Engine
- **Historical Data Integration**: Uses Alpaca's historical stock and options data
- **Realistic Trade Simulation**: Includes commissions, slippage, and assignment logic
- **Comprehensive Analysis**: Performance metrics, drawdown analysis, and trade statistics
- **Visualization Tools**: Portfolio performance charts and trade distribution plots
- **Export Capabilities**: Results exported to Excel/CSV for further analysis
- **Strategy Parameter Testing**: Test different DTE, delta ranges, and position sizing

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd options_wheel
```

2. Install dependencies:

**Quick Install (Essential Features):**
```bash
pip install -r requirements-minimal.txt
```

**Full Install (All Features - Recommended):**
```bash
pip install -r requirements.txt
```

**Developer Install (All Tools):**
```bash
pip install -r requirements-dev.txt
```

3. Verify installation:
```bash
python scripts/test_installation.py
```

4. Set up configuration:
```bash
cp .env.example .env
# Edit .env with your Alpaca API credentials
```

5. Test API connection:
```bash
python scripts/check_api_connection.py
```

> 📖 **Detailed Installation Guide:** See [INSTALL.md](INSTALL.md) for comprehensive installation instructions, troubleshooting, and platform-specific notes.

## Configuration

### API Credentials

Create a `.env` file with your Alpaca credentials:
```
ALPACA_API_KEY=your_api_key_here
ALPACA_SECRET_KEY=your_secret_key_here
ALPACA_ENV=paper
```

### Strategy Settings

Key configuration parameters in `config/settings.yaml`:

```yaml
# Strategy Parameters
strategy:
  put_target_dte: 7              # Maximum days to expiration
  call_target_dte: 7
  put_delta_range: [0.10, 0.20]  # Conservative delta range
  call_delta_range: [0.10, 0.20]
  min_put_premium: 0.50          # Minimum premium in dollars
  min_call_premium: 0.30

# Risk Management
risk:
  use_put_stop_loss: false       # Take assignment instead
  use_call_stop_loss: true       # Protect against runaway moves
  put_stop_loss_percent: 0.50
  call_stop_loss_percent: 0.50
  stop_loss_multiplier: 1.5      # Time decay adjustment
  profit_target_percent: 0.50    # 50% profit target
  max_position_size: 0.10        # 10% portfolio per position
```

- **Target DTE**: Maximum days to expiration for new positions (7 days for both puts and calls)
- **Delta Range**: Target delta range for option selection (0.10-0.20 for conservative approach)
- **Premium Thresholds**: Minimum premium to consider for trades
- **Risk Limits**: Maximum position sizes and portfolio allocation
- **Stock Universe**: List of stocks to trade

## Usage

### Live Trading Interface

Run a strategy cycle:
```bash
python main.py --command run --dry-run
```

Scan for opportunities:
```bash
python main.py --command scan
```

Check portfolio status:
```bash
python main.py --command status
```

Generate performance report:
```bash
python main.py --command report
```

### Backtesting Interface

Run a basic backtest:
```bash
python backtest_runner.py --start-date 2024-01-01 --end-date 2024-06-30 --symbols AAPL MSFT
```

Backtest with custom parameters:
```bash
python backtest_runner.py --start-date 2024-01-01 --end-date 2024-06-30 \
  --put-dte 7 --call-dte 7 --put-delta-min 0.10 --put-delta-max 0.20 \
  --initial-capital 50000 --save-plots --export-data
```

Run backtest demonstration:
```bash
python demo_backtest.py
```

### Strategy Commands

- `run`: Execute the wheel strategy (finds opportunities and places trades)
- `scan`: Scan for put and call opportunities without trading
- `status`: Show current portfolio status and positions
- `report`: Generate comprehensive performance report

### Safety Features

- **Paper Trading Default**: Enabled by default for safe testing
- **Separate Stop Loss Controls**: Puts ride to assignment, calls protected
- **Conservative Position Sizing**: 1 contract maximum per new position
- **Quality Stock Universe**: Focus on liquid, established companies (AAPL, MSFT, etc.)
- **Time Decay Awareness**: Stop loss thresholds adjusted for 7-day options

## Strategy Logic

### Put Selling Phase
1. Screen stocks for liquidity, price range, and volatility criteria
2. Find put options with ≤7 days to expiration and delta (0.10-0.20)
3. Calculate position size based on portfolio allocation limits (max 10% per position)
4. Place cash-secured put orders at 5% below mid-price for better fills

### Assignment Management
1. Monitor short put positions for assignment risk
2. Handle assignment by acquiring stock at strike price
3. Immediately look for covered call opportunities

### Call Selling Phase
1. Identify assigned stock positions (100+ shares in round lots)
2. Find call options with ≤7 days to expiration and delta (0.10-0.20)
3. Sell covered calls at strikes above current stock price
4. Manage until expiration, assignment, or 50% profit target

### Risk Management
- Maximum 10% of portfolio per position
- Maintain 20% cash reserves
- **Puts**: No stop losses - take assignment on quality stocks
- **Calls**: Stop losses at 75% premium loss (50% × 1.5 time decay multiplier)
- 50% profit target for early closure on both puts and calls
- Delta-based stop loss: exit if delta > 0.5 (likely ITM)

## Performance Tracking

The system tracks wheel-specific metrics:

- **Premium Collection**: Total premiums collected from puts and calls
- **Assignment Rates**: Percentage of puts that result in stock assignment
- **Wheel Completion**: Full cycles from put sale → assignment → call sale → call away
- **Early Closures**: Positions closed at 50% profit target before expiration
- **Stop Loss Events**: Calls closed due to adverse price movements
- **Risk Metrics**: Maximum drawdown, portfolio allocation, position sizing compliance

## Testing

Run the test suite:
```bash
pytest tests/ -v
```

Key test areas:
- Configuration loading and validation
- Risk management calculations
- Position sizing algorithms
- Strategy engine logic
- API integration (mocked)

## Architecture

### Project Structure
```
options_wheel-1/
├── config/
│   └── settings.yaml           # Strategy configuration
├── src/
│   ├── api/
│   │   ├── alpaca_client.py    # Alpaca API wrapper
│   │   └── market_data.py      # Options chain analysis
│   ├── strategy/
│   │   ├── wheel_engine.py     # Main orchestrator
│   │   ├── put_seller.py       # Put selling logic
│   │   └── call_seller.py      # Call selling logic
│   ├── risk/
│   │   ├── risk_manager.py     # Risk validation
│   │   └── position_sizing.py  # Position calculations
│   ├── data/
│   │   ├── portfolio_tracker.py # Performance monitoring
│   │   └── options_scanner.py   # Opportunity scanning
│   └── utils/
│       ├── config.py           # Configuration management
│       └── logger.py           # Structured logging
├── tests/                      # Test suite
└── logs/                       # Application logs
```

### Core Components

- **WheelEngine**: Main strategy orchestrator with complete cycle management
- **AlpacaClient**: API wrapper for trading operations and market data
- **MarketDataManager**: Options chain analysis and filtering with delta/DTE criteria
- **PutSeller/CallSeller**: Strategy-specific trade execution with separate risk controls
- **RiskManager**: Position validation against portfolio limits and risk controls
- **PortfolioTracker**: Performance monitoring with wheel-specific metrics
- **OptionsScanner**: Opportunity identification and ranking by return potential

### Data Flow

1. **Market Analysis**: Scan stocks and options chains
2. **Opportunity Identification**: Rank trading opportunities
3. **Risk Validation**: Check against position limits
4. **Trade Execution**: Place orders via Alpaca API
5. **Position Monitoring**: Track P&L and assignment risk
6. **Performance Reporting**: Generate analytics and reports

## Development

### Adding New Features

1. **New Risk Rules**: Extend `RiskManager` class
2. **Different Options Strategies**: Create new strategy modules
3. **Enhanced Scanning**: Modify `OptionsScanner` criteria
4. **Additional APIs**: Extend `AlpacaClient` wrapper

### Configuration Changes

Update `config/settings.yaml` for strategy parameters and `CLAUDE.md` for development guidelines.

## Disclaimer

This software is for educational and research purposes. Options trading involves significant risk and may not be suitable for all investors. Always test strategies thoroughly with paper trading before using real money. Past performance does not guarantee future results.

The authors are not responsible for any financial losses incurred from using this software. Please consult with a financial advisor before making investment decisions.

## License

This project is licensed under the MIT License - see the LICENSE file for details.