"""Historical data layer for the backtest.

Public surface:
    OptionsDataProvider, OptionContract, OptionBar, StockBar  - provider protocol
    AlpacaDataProvider                                        - Alpaca impl
    ChainBuilder, ChainSnapshot, ChainQuote                   - point-in-time chains
    SpreadModel                                               - modeled bid/ask
    ChainStore                                                - parquet cache
    CoverageReport, evaluate_coverage                         - the Phase 1 gate
"""

from .chain_builder import ChainBuilder, ChainQuote, ChainSnapshot
from .chain_store import ChainStore
from .provider import OptionBar, OptionContract, OptionsDataProvider, StockBar
from .quality import CoverageReport, DayCoverage, evaluate_coverage
from .spread_model import SpreadModel

__all__ = [
    "OptionsDataProvider",
    "OptionContract",
    "OptionBar",
    "StockBar",
    "ChainBuilder",
    "ChainSnapshot",
    "ChainQuote",
    "SpreadModel",
    "ChainStore",
    "CoverageReport",
    "DayCoverage",
    "evaluate_coverage",
]
