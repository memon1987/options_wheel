"""Configuration management for Options Wheel strategy."""

import os
import yaml
from pathlib import Path
from dotenv import load_dotenv
from typing import Dict, Any, List, Optional
import structlog

logger = structlog.get_logger(__name__)

class Config:
    """Configuration manager for the options wheel strategy."""
    
    def __init__(self, config_path: str = "config/settings.yaml"):
        """Initialize configuration.
        
        Args:
            config_path: Path to the YAML configuration file
        """
        # Load environment variables
        load_dotenv()
        
        # Load YAML configuration
        self.config_path = Path(config_path)
        self._config = self._load_config()
        
        # Substitute environment variables
        self._substitute_env_vars()
        
        logger.info("Configuration loaded", config_path=config_path)
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        try:
            with open(self.config_path, 'r') as file:
                return yaml.safe_load(file)
        except FileNotFoundError:
            logger.error("Configuration file not found", path=self.config_path)
            raise
        except yaml.YAMLError as e:
            logger.error("Error parsing YAML configuration", error=str(e))
            raise
    
    def _substitute_env_vars(self):
        """Substitute environment variables in configuration values."""
        def substitute_recursive(obj):
            if isinstance(obj, dict):
                return {k: substitute_recursive(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [substitute_recursive(item) for item in obj]
            elif isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
                env_var = obj[2:-1]
                return os.getenv(env_var, obj)
            else:
                return obj
        
        self._config = substitute_recursive(self._config)
    
    # Alpaca API Settings
    @property
    def alpaca_api_key(self) -> str:
        """Get Alpaca API key."""
        return self._config["alpaca"]["api_key_id"]
    
    @property
    def alpaca_secret_key(self) -> str:
        """Get Alpaca secret key."""
        return self._config["alpaca"]["secret_key"]
    
    @property
    def paper_trading(self) -> bool:
        """Check if paper trading is enabled."""
        return self._config["alpaca"]["paper_trading"]
    
    # Strategy Parameters
    @property
    def put_target_dte(self) -> int:
        """Target days to expiration for puts."""
        return self._config["strategy"]["put_target_dte"]
    
    @property
    def call_target_dte(self) -> int:
        """Target days to expiration for calls."""
        return self._config["strategy"]["call_target_dte"]
    
    @property
    def put_delta_range(self) -> List[float]:
        """Delta range for put options."""
        return self._config["strategy"]["put_delta_range"]
    
    @property
    def call_delta_range(self) -> List[float]:
        """Delta range for call options."""
        return self._config["strategy"]["call_delta_range"]
    
    @property
    def min_put_premium(self) -> float:
        """Minimum premium for put options."""
        return self._config["strategy"]["min_put_premium"]
    
    @property
    def min_call_premium(self) -> float:
        """Minimum premium for call options."""
        return self._config["strategy"]["min_call_premium"]
    
    @property
    def min_stock_price(self) -> float:
        """Minimum stock price for selection."""
        return self._config["strategy"]["min_stock_price"]
    
    @property
    def max_stock_price(self) -> float:
        """Maximum stock price for selection."""
        return self._config["strategy"]["max_stock_price"]
    
    @property
    def min_avg_volume(self) -> int:
        """Minimum average volume for stock selection."""
        return self._config["strategy"]["min_avg_volume"]
    
    @property
    def max_positions_per_stock(self) -> int:
        """Maximum positions per stock."""
        return self._config["strategy"]["max_positions_per_stock"]
    
    @property
    def max_total_positions(self) -> int:
        """Maximum total positions."""
        return self._config["strategy"]["max_total_positions"]
    
    @property
    def max_exposure_per_ticker(self) -> float:
        """Maximum exposure per ticker (dollar amount assuming assignment)."""
        return self._config["strategy"]["max_exposure_per_ticker"]

    @property
    def max_stocks_evaluated_per_cycle(self) -> Optional[int]:
        """Maximum stocks to evaluate per cycle (None = no limit)."""
        return self._config["strategy"].get("max_stocks_evaluated_per_cycle")

    @property
    def max_new_positions_per_cycle(self) -> Optional[int]:
        """Maximum new positions to open per cycle (None = no limit)."""
        return self._config["strategy"].get("max_new_positions_per_cycle")

    # Risk Management
    @property
    def max_portfolio_allocation(self) -> float:
        """Maximum portfolio allocation."""
        return self._config["risk"]["max_portfolio_allocation"]
    
    @property
    def max_position_size(self) -> float:
        """Maximum position size as percentage of portfolio."""
        return self._config["risk"]["max_position_size"]
    
    @property
    def min_cash_reserve(self) -> float:
        """Minimum cash reserve percentage."""
        return self._config["risk"]["min_cash_reserve"]
    
    @property
    def use_put_stop_loss(self) -> bool:
        """Whether to use stop loss for put positions."""
        return self._config["risk"]["use_put_stop_loss"]
    
    @property
    def use_call_stop_loss(self) -> bool:
        """Whether to use stop loss for call positions."""
        return self._config["risk"]["use_call_stop_loss"]
    
    @property
    def put_stop_loss_percent(self) -> float:
        """Stop loss percentage for put positions."""
        return self._config["risk"]["put_stop_loss_percent"]
    
    @property
    def call_stop_loss_percent(self) -> float:
        """Stop loss percentage for call positions."""
        return self._config["risk"]["call_stop_loss_percent"]
    
    @property
    def stop_loss_multiplier(self) -> float:
        """Stop loss multiplier for short-term options (accounts for time decay)."""
        return self._config["risk"]["stop_loss_multiplier"]
    
    @property
    def profit_target_percent(self) -> float:
        """Profit target percentage for early closure."""
        return self._config["risk"]["profit_target_percent"]
    
    # Stock Universe
    @property
    def stock_symbols(self) -> List[str]:
        """List of stock symbols to trade."""
        return self._config["stocks"]["symbols"]
    
    # Monitoring
    @property
    def check_interval_minutes(self) -> int:
        """Position check interval in minutes."""
        return self._config["monitoring"]["check_interval_minutes"]

    # Gap Risk Controls
    @property
    def enable_gap_detection(self) -> bool:
        """Enable overnight gap monitoring."""
        return self._config["risk"]["gap_risk_controls"]["enable_gap_detection"]

    @property
    def max_overnight_gap_percent(self) -> float:
        """Maximum overnight gap percentage before position closure."""
        return self._config["risk"]["gap_risk_controls"]["max_overnight_gap_percent"]

    @property
    def gap_lookback_days(self) -> int:
        """Days to analyze historical gap frequency."""
        return self._config["risk"]["gap_risk_controls"]["gap_lookback_days"]

    @property
    def max_gap_frequency(self) -> float:
        """Maximum allowed gap frequency for stock selection."""
        return self._config["risk"]["gap_risk_controls"]["max_gap_frequency"]

    @property
    def earnings_avoidance_days(self) -> int:
        """Days to avoid new positions before earnings."""
        return self._config["risk"]["gap_risk_controls"]["earnings_avoidance_days"]

    @property
    def premarket_gap_threshold(self) -> float:
        """Pre-market gap threshold that triggers review."""
        return self._config["risk"]["gap_risk_controls"]["premarket_gap_threshold"]

    @property
    def market_open_delay_minutes(self) -> int:
        """Minutes to wait after market open if gap detected."""
        return self._config["risk"]["gap_risk_controls"]["market_open_delay_minutes"]

    @property
    def max_historical_vol(self) -> float:
        """Maximum historical volatility for stock selection."""
        return self._config["risk"]["gap_risk_controls"]["max_historical_vol"]

    @property
    def vol_lookback_days(self) -> int:
        """Days for historical volatility calculation."""
        return self._config["risk"]["gap_risk_controls"]["vol_lookback_days"]

    @property
    def quality_gap_threshold(self) -> float:
        """Threshold for counting significant gaps in stock quality filtering."""
        return self._config["risk"]["gap_risk_controls"]["quality_gap_threshold"]

    @property
    def execution_gap_threshold(self) -> float:
        """Hard threshold for blocking trade execution due to gaps."""
        return self._config["risk"]["gap_risk_controls"]["execution_gap_threshold"]

    @property
    def execution_gap_lookback_hours(self) -> int:
        """Hours to look back for execution gap calculation."""
        return self._config["risk"]["gap_risk_controls"]["execution_gap_lookback_hours"]

    # Legacy property for backward compatibility
    @property
    def max_execution_gap_percent(self) -> float:
        """Maximum gap allowed for trade execution (legacy name)."""
        return self.execution_gap_threshold

    # Legacy property for backward compatibility
    @property
    def significant_gap_threshold(self) -> float:
        """Threshold for counting significant gaps (legacy name)."""
        return self.quality_gap_threshold

    def get(self, key: str, default=None):
        """Get configuration value by key path (e.g., 'alpaca.paper_trading')."""
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value