# Installation Guide

## Quick Start

### 1. Basic Installation (Recommended)
```bash
# Install essential packages for live trading and basic backtesting
pip install -r requirements-minimal.txt
```

### 2. Full Installation (All Features)
```bash
# Install all packages including advanced visualization and analysis tools
pip install -r requirements.txt
```

### 3. Development Installation
```bash
# Install everything including development and testing tools
pip install -r requirements-dev.txt
```

## Installation Options Explained

### requirements-minimal.txt
**Use case:** Essential trading functionality only
- ✅ Live trading with Alpaca API
- ✅ Basic backtesting capabilities
- ✅ Configuration management
- ✅ Risk management
- ✅ Basic plotting with matplotlib
- ✅ Excel export

**Size:** ~15 packages, lightweight installation

### requirements.txt  
**Use case:** Full-featured installation (recommended)
- ✅ Everything from minimal
- ✅ Advanced visualizations (Plotly, Seaborn)
- ✅ Statistical analysis tools
- ✅ Performance optimization (Numba)
- ✅ Web interface (Streamlit)
- ✅ Jupyter notebook support
- ✅ Additional financial libraries

**Size:** ~30+ packages, comprehensive installation

### requirements-dev.txt
**Use case:** Development and contribution
- ✅ Everything from requirements.txt
- ✅ Code quality tools (Pylint, Black)
- ✅ Advanced testing frameworks
- ✅ Documentation generation
- ✅ Performance profiling tools
- ✅ Security scanning

**Size:** ~40+ packages, complete development environment

## Verification

Test your installation:
```bash
python scripts/test_installation.py
```

This will check:
- ✅ Core package availability
- ✅ Visualization libraries
- ✅ Project modules
- ✅ API connectivity

## Troubleshooting

### Common Issues

**1. TA-Lib Installation (Windows)**
```bash
# TA-Lib requires additional setup on Windows
# Download wheel from: https://www.lfd.uci.edu/~gohlke/pythonlibs/#ta-lib
pip install TA_Lib-0.4.28-cp39-cp39-win_amd64.whl  # Adjust for your Python version
```

**2. QuantLib Installation**
```bash
# QuantLib may require compilation on some systems
# Alternative: Use conda
conda install quantlib-python
```

**3. Memory Issues During Installation**
```bash
# If running out of memory during installation
pip install --no-cache-dir -r requirements.txt
```

**4. Permission Issues (macOS/Linux)**
```bash
# Use virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Platform-Specific Notes

**macOS:**
- Some packages may require Xcode command line tools
- Install with: `xcode-select --install`

**Windows:**
- Some financial libraries may not be available
- Consider using Anaconda/Miniconda for easier installation

**Linux:**
- May need development headers: `apt-get install python3-dev`

## Package Categories

### Core Trading (Always Required)
- `alpaca-py` - Alpaca API client
- `pandas` - Data manipulation
- `numpy` - Numerical operations
- `requests` - HTTP requests
- `structlog` - Structured logging

### Configuration & Environment
- `pyyaml` - YAML configuration files
- `python-dotenv` - Environment variable management
- `python-dateutil` - Date/time utilities

### Mathematical & Financial
- `scipy` - Scientific computing
- `statsmodels` - Statistical analysis
- `quantlib` - Quantitative finance (optional)
- `ta-lib` - Technical analysis (optional)

### Visualization
- `matplotlib` - Basic plotting
- `seaborn` - Statistical visualization
- `plotly` - Interactive charts

### Data Export
- `openpyxl` - Excel file handling
- `xlsxwriter` - Excel writing

### Development
- `pytest` - Testing framework
- `black` - Code formatting
- `mypy` - Type checking

## Next Steps

After installation:

1. **Configure API credentials:**
   ```bash
   cp .env.example .env
   # Edit .env with your Alpaca API keys
   ```

2. **Test API connection:**
   ```bash
   python scripts/check_api_connection.py
   ```

3. **Run your first backtest:**
   ```bash
   python demo_backtest.py
   ```

4. **Start live trading (paper mode):**
   ```bash
   python main.py --command scan
   ```