"""Shared cost-basis floor resolution for covered calls (FC-029 chain, FC-050).

Writing a covered call below the cost basis of the shares it covers is a
guaranteed loss. The floor that prevents it has to be the *same* number
wherever it is computed, so the resolution chain FC-029 built for
``CallSeller`` lives here and is used by both the scanner (which produces
opportunities) and the seller (which executes them).
"""

import os
from typing import Any, Callable, Dict, Optional, Tuple

import structlog

from ..api.alpaca_client import AlpacaClient
from ..utils.config import Config

logger = structlog.get_logger(__name__)

# Source labels returned alongside a resolved basis.
SOURCE_WHEEL_STATE = "wheel_state"
SOURCE_BIGQUERY = "bigquery"
SOURCE_ALPACA = "alpaca"
SOURCE_UNRESOLVED = "unresolved"


class CostBasisResolver:
    """Resolve the per-share cost basis used as the covered-call strike floor."""

    def __init__(self, alpaca_client: AlpacaClient, config: Config,
                 wheel_state=None, allow_bigquery: bool = True,
                 opasn_lookup: Optional[Callable[[str], float]] = None):
        """Initialize the resolver.

        Args:
            alpaca_client: Alpaca API client.
            config: Configuration instance.
            wheel_state: Optional WheelStateManager — source 1 of the chain,
                and the back-fill target when source 2 resolves.
            allow_bigquery: whether the chain may fall back to a BigQuery
                OPASN lookup. A backtest passes False: the wheel-state path
                always holds the simulated assignment strike, and this
                fallback would otherwise query *production* trade history —
                against CURRENT_TIMESTAMP() — mixing real assignments into a
                simulated run.
            opasn_lookup: optional override for source 2, called as
                ``opasn_lookup(symbol)``. ``CallSeller`` passes a late-bound
                reference to its own delegating wrapper so that patching
                ``CallSeller._lookup_last_opasn_put_strike`` — which the test
                suite's hermeticity guard does — still intercepts the chain.
        """
        self.alpaca = alpaca_client
        self.config = config
        self.wheel_state = wheel_state
        self.allow_bigquery = allow_bigquery
        self._opasn_lookup = opasn_lookup
        # FC-029: cache the BigQuery client (constructed lazily on first
        # cost-basis lookup) so cold-start cycles don't pay the Client()
        # construction cost twice within a single resolution pass.
        self._bq_client = None

    def resolve(self, symbol: str, stock_position: Dict[str, Any],
                shares_owned: int) -> float:
        """Return the per-share cost basis, or 0 if no source resolves it."""
        return self.resolve_with_source(symbol, stock_position, shares_owned)[0]

    def resolve_with_source(self, symbol: str, stock_position: Dict[str, Any],
                            shares_owned: int) -> Tuple[float, str]:
        """Resolve the per-share cost basis and name the source it came from.

        FC-029 (R2): cost basis = strike of the assigning put. Sources, in order:

        1. ``wheel_state.symbol_states[symbol]['stock_cost_basis']`` — populated
           at OPASN time from the put strike, persisted to GCS.
        2. Most recent OPASN-put strike for ``symbol`` from
           ``options_wheel.trades_from_activities`` (handles silent assignments,
           cold starts, and synthetic-row corrections like FC-021/FC-025). When
           this path resolves, the result is back-filled into wheel_state so
           subsequent reads in the same cycle hit the fast path.
        3. Alpaca's reported ``cost_basis`` field — known-broken for assigned
           positions in paper trading (returns 0), but works for non-wheel
           positions like manual buys. Last-resort fallback.

        Returns (0.0, "unresolved") only if no source resolves; the caller
        treats that as "no floor" and must fail closed.

        Args:
            symbol: Underlying ticker (e.g. ``"AMD"``).
            stock_position: Alpaca position dict (provides the Alpaca fallback).
            shares_owned: Current share count for fallback per-share division.
        """
        # 1. wheel_state — canonical, in-memory + GCS persisted
        if self.wheel_state:
            try:
                state = self.wheel_state.get_position_summary(symbol)
                cb = float(state.get('stock_cost_basis', 0) or 0)
                if cb > 0:
                    return cb, SOURCE_WHEEL_STATE
            except Exception as e:
                logger.warning(
                    "wheel_state cost-basis read failed; trying BQ fallback",
                    event_category="risk",
                    event_type="cost_basis_state_read_failed",
                    symbol=symbol, error=str(e),
                )

        # 2. BQ — last OPASN-put strike for this symbol
        cb = self._opasn_lookup(symbol) if self._opasn_lookup else self._lookup_last_opasn_put_strike(symbol)
        if cb > 0:
            if self.wheel_state:
                try:
                    self.wheel_state.set_stock_cost_basis(symbol, cb)
                except Exception as e:
                    logger.warning(
                        "wheel_state cost-basis backfill failed",
                        event_category="risk",
                        event_type="cost_basis_state_backfill_failed",
                        symbol=symbol, error=str(e),
                    )
            return cb, SOURCE_BIGQUERY

        # 3. Alpaca — last resort. Broken for assigned paper positions but
        #    correct for manual buys (qty * avg_entry_price).
        try:
            alpaca_cb = float(stock_position.get('cost_basis', 0) or 0)
            resolved = alpaca_cb / max(shares_owned, 1)
        except Exception:
            return 0.0, SOURCE_UNRESOLVED
        return (resolved, SOURCE_ALPACA) if resolved > 0 else (resolved, SOURCE_UNRESOLVED)

    def _lookup_last_opasn_put_strike(self, symbol: str, lookback_days: int = 90) -> float:
        """Return strike of the most recent OPASN-put for ``symbol``.

        FC-029 review fixes:
          - HIGH 1: pass ``project=`` to ``bigquery.Client()`` so the lookup
            targets the right GCP project even when env vars are unset/wrong.
            Matches codebase pattern in `data/*_ingestor.py`.
          - HIGH 3: cache the client on ``self._bq_client`` so repeated calls
            within one evaluation don't pay the Client() construction cost.
          - HIGH 4: age-bound to ``lookback_days`` (default 90) so stale OPASN
            history doesn't get applied to long-after-the-fact manual buys
            on a previously-traded symbol.

        Returns 0 if no assigning put found within ``lookback_days``, BQ
        unavailable, or any error. Logged at WARNING when the lookup fails so
        missed floors are observable.
        """
        if not self.allow_bigquery:
            # Backtest mode. Returning 0.0 is the same "no floor from this
            # source" signal the fallback already emits on miss, so the caller's
            # resolution chain is unchanged.
            logger.debug("BigQuery cost-basis fallback disabled",
                         event_category="data",
                         event_type="cost_basis_bq_disabled",
                         symbol=symbol)
            return 0.0

        try:
            from google.cloud import bigquery
            if self._bq_client is None:
                project_id = (
                    os.environ.get('GCP_PROJECT')
                    or os.environ.get('GOOGLE_CLOUD_PROJECT')
                    or os.environ.get('GCP_PROJECT_ID')
                )
                self._bq_client = bigquery.Client(project=project_id) if project_id else bigquery.Client()
            query = """
            SELECT strike_price
            FROM `options_wheel.trades_from_activities`
            WHERE underlying = @symbol
              AND activity_type = 'OPASN'
              AND option_type = 'put'
              AND transaction_time <= CURRENT_TIMESTAMP()
              AND transaction_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @lookback_days DAY)
            ORDER BY transaction_time DESC
            LIMIT 1
            """
            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter('symbol', 'STRING', symbol),
                bigquery.ScalarQueryParameter('lookback_days', 'INT64', lookback_days),
            ])
            job = self._bq_client.query(query, job_config=job_config)
            for row in job.result(timeout=10):
                strike = row.get('strike_price')
                return float(strike) if strike is not None else 0.0
            return 0.0
        except Exception as e:
            logger.warning(
                "OPASN-strike lookup failed; falling back to Alpaca cost_basis",
                event_category="risk",
                event_type="opasn_strike_lookup_failed",
                symbol=symbol, error=str(e),
            )
            return 0.0


def opportunity_floor_per_share(opportunity: Dict[str, Any]) -> float:
    """Return the per-share cost-basis floor carried by an opportunity.

    FC-050: the two producers of call opportunities disagree on shape — the
    scanner emits ``cost_basis_per_share`` + ``max_contracts``, the wheel
    engine emits a *total* ``stock_cost_basis`` + ``shares_covered``. Reading
    only the wheel-engine keys is why the execute-time floor never fired on
    the path production runs.

    Resolution order, first positive wins:
      1. ``cost_basis_per_share`` (scanner shape).
      2. ``stock_cost_basis / shares_covered`` (wheel-engine shape), where
         ``shares_covered`` falls back to ``contracts * 100``. Never a bare
         100: post-FC-038 a covered call can be multi-contract, and dividing
         a total basis by 100 would understate the floor by the contract
         count.

    Returns 0.0 when no floor can be derived; callers must fail closed.
    """
    try:
        per_share = float(opportunity.get('cost_basis_per_share') or 0)
        if per_share > 0:
            return per_share

        total_basis = float(opportunity.get('stock_cost_basis') or 0)
        if total_basis > 0:
            shares_covered = float(opportunity.get('shares_covered') or 0)
            if shares_covered <= 0:
                shares_covered = float(opportunity.get('contracts') or 0) * 100
            if shares_covered > 0:
                return total_basis / shares_covered
    except (TypeError, ValueError):
        return 0.0

    return 0.0
