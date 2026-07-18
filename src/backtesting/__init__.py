"""Backtesting engine for options-wheel symbol fitness evaluation.

Rebuilt under FC-032 (see docs/plans/fc-032.md). The engine replays the live
strategy components against historical data rather than re-implementing the
rules, so backtest behavior tracks live behavior by construction.

Subpackages:
    data      - historical options/stock data providers, point-in-time chain
                construction, greeks, spread modeling, caching, coverage report
    engine    - simulation clock, broker (ledger/fills/assignment), strategy
                replay adapter, day loop
    metrics   - per-cycle analytics and per-symbol fitness scoring
    reporting - markdown/JSON reports and BigQuery writers
"""
