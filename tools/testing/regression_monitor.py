#!/usr/bin/env python3
"""
Production regression testing framework for Options Wheel Strategy.

Runs automated checks during market hours to validate the system is working
correctly. Designed to be invoked by Cloud Scheduler via the /regression
endpoint, or run standalone for ad-hoc verification.

Checks performed:
    1. Endpoint health checks (/, /status, /account, /positions)
    2. Trade execution validation (BigQuery: naked calls, duplicates, premiums)
    3. Log analysis (Cloud Logging: error rates, error patterns, correlation IDs)
    4. Position reconciliation (app positions vs Alpaca API)
    5. Performance baseline comparison (rolling 7-day metric deviations)
"""

import os
import sys
import time
import json
import traceback
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
import structlog

# Allow imports from project root when running standalone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.utils.logging_events import log_system_event, log_error_event, log_performance_metric

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVICE_URL = os.environ.get(
    "REGRESSION_SERVICE_URL",
    "https://options-wheel-strategy-799970961417.us-central1.run.app",
)
GCP_PROJECT = os.environ.get("GCP_PROJECT", "gen-lang-client-0607444019")
BQ_DATASET = os.environ.get("BQ_DATASET", "options_wheel")
BQ_TABLE = os.environ.get("BQ_TABLE", "trades")

# Thresholds
ERROR_WARNING_THRESHOLD = 5
ERROR_CRITICAL_THRESHOLD = 20
PREMIUM_MIN = 0.01
PREMIUM_MAX = 50.0
DUPLICATE_ORDER_WINDOW_SECONDS = 300  # 5 minutes
METRIC_DEVIATION_THRESHOLD = 2.0  # standard deviations

# Error patterns that indicate critical issues
CRITICAL_ERROR_PATTERNS = [
    "circuit_breaker_opened",
    "naked_call_blocked",
    "mark_executed_failed",
]


class CheckResult:
    """Result of a single regression check."""

    def __init__(self, name: str, status: str, message: str, details: Optional[Dict] = None):
        self.name = name
        self.status = status  # "pass", "warn", "fail"
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
        }


class RegressionMonitor:
    """Runs automated regression checks against the production system.

    The monitor can operate in two modes:

    * **Internal** (default when running inside Cloud Run) -- calls endpoints
      on localhost and uses Google Cloud client libraries for BigQuery /
      Cloud Logging.
    * **External** (when running standalone) -- calls the public Cloud Run
      URL with an API key and uses ``gcloud`` for auth where needed.
    """

    def __init__(
        self,
        service_url: Optional[str] = None,
        api_key: Optional[str] = None,
        internal: bool = False,
    ):
        self.service_url = service_url or SERVICE_URL
        self.api_key = api_key or os.environ.get("STRATEGY_API_KEY", "")
        self.internal = internal
        self.results: List[CheckResult] = []
        self.start_time = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        """Build request headers with authentication."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _get(self, path: str, timeout: int = 30) -> requests.Response:
        url = f"{self.service_url}{path}"
        return requests.get(url, headers=self._headers(), timeout=timeout)

    def _post(self, path: str, payload: Optional[Dict] = None, timeout: int = 60) -> requests.Response:
        url = f"{self.service_url}{path}"
        return requests.post(url, headers=self._headers(), json=payload or {}, timeout=timeout)

    # ------------------------------------------------------------------
    # 1. Endpoint health checks
    # ------------------------------------------------------------------

    def check_endpoints(self) -> List[CheckResult]:
        """Verify all critical endpoints respond correctly."""
        checks: List[CheckResult] = []

        # --- / (root health) ---
        try:
            resp = self._get("/")
            if resp.status_code == 200:
                body = resp.json()
                if body.get("status") == "healthy":
                    checks.append(CheckResult("endpoint_root", "pass", "Root returns healthy"))
                else:
                    checks.append(CheckResult(
                        "endpoint_root", "warn",
                        f"Root returned status={body.get('status')}",
                        {"response": body},
                    ))
            else:
                checks.append(CheckResult(
                    "endpoint_root", "fail",
                    f"Root returned HTTP {resp.status_code}",
                    {"status_code": resp.status_code},
                ))
        except Exception as exc:
            checks.append(CheckResult("endpoint_root", "fail", f"Root unreachable: {exc}"))

        # --- /status ---
        try:
            resp = self._get("/status")
            if resp.status_code == 200:
                body = resp.json()
                checks.append(CheckResult(
                    "endpoint_status", "pass",
                    f"Status endpoint OK (strategy status={body.get('status', 'unknown')})",
                    {"strategy_status": body.get("status")},
                ))
            else:
                checks.append(CheckResult(
                    "endpoint_status", "fail",
                    f"/status returned HTTP {resp.status_code}",
                ))
        except Exception as exc:
            checks.append(CheckResult("endpoint_status", "fail", f"/status unreachable: {exc}"))

        # --- /account ---
        try:
            resp = self._get("/account")
            if resp.status_code == 200:
                body = resp.json()
                portfolio_value = float(body.get("portfolio_value", 0))
                buying_power = float(body.get("buying_power", 0))
                if portfolio_value > 0 and buying_power >= 0:
                    checks.append(CheckResult(
                        "endpoint_account", "pass",
                        f"Account valid (portfolio=${portfolio_value:,.2f}, bp=${buying_power:,.2f})",
                        {"portfolio_value": portfolio_value, "buying_power": buying_power},
                    ))
                else:
                    checks.append(CheckResult(
                        "endpoint_account", "warn",
                        f"Account data suspicious (portfolio=${portfolio_value}, bp=${buying_power})",
                        {"portfolio_value": portfolio_value, "buying_power": buying_power},
                    ))
            elif resp.status_code == 401:
                checks.append(CheckResult(
                    "endpoint_account", "fail",
                    "Authentication failed for /account",
                ))
            else:
                checks.append(CheckResult(
                    "endpoint_account", "fail",
                    f"/account returned HTTP {resp.status_code}",
                ))
        except Exception as exc:
            checks.append(CheckResult("endpoint_account", "fail", f"/account unreachable: {exc}"))

        # --- /positions ---
        try:
            resp = self._get("/positions")
            if resp.status_code == 200:
                body = resp.json()
                positions = body.get("positions", [])
                if isinstance(positions, list):
                    checks.append(CheckResult(
                        "endpoint_positions", "pass",
                        f"Positions endpoint OK ({len(positions)} positions)",
                        {"count": len(positions)},
                    ))
                else:
                    checks.append(CheckResult(
                        "endpoint_positions", "warn",
                        "Positions response is not a list",
                        {"type": type(positions).__name__},
                    ))
            else:
                checks.append(CheckResult(
                    "endpoint_positions", "fail",
                    f"/positions returned HTTP {resp.status_code}",
                ))
        except Exception as exc:
            checks.append(CheckResult("endpoint_positions", "fail", f"/positions unreachable: {exc}"))

        self.results.extend(checks)
        return checks

    # ------------------------------------------------------------------
    # 2. Trade execution validation (BigQuery)
    # ------------------------------------------------------------------

    def check_trade_execution(self) -> List[CheckResult]:
        """Query BigQuery for recent trades and validate correctness."""
        checks: List[CheckResult] = []

        try:
            from google.cloud import bigquery
            client = bigquery.Client(project=GCP_PROJECT)
        except Exception as exc:
            checks.append(CheckResult(
                "trade_bigquery_client", "warn",
                f"Cannot connect to BigQuery: {exc}",
            ))
            self.results.extend(checks)
            return checks

        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        # Fetch recent trades
        query = f"""
            SELECT *
            FROM `{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}`
            WHERE timestamp_iso >= '{one_hour_ago}'
            ORDER BY timestamp_iso DESC
        """

        try:
            rows = list(client.query(query).result())
        except Exception as exc:
            checks.append(CheckResult(
                "trade_query", "warn",
                f"BigQuery trade query failed: {exc}",
            ))
            self.results.extend(checks)
            return checks

        if not rows:
            checks.append(CheckResult(
                "trade_recent_activity", "pass",
                "No trades in the last hour (nothing to validate)",
            ))
            self.results.extend(checks)
            return checks

        trades = [dict(row) for row in rows]

        # -- No naked calls --
        call_trades = [t for t in trades if str(t.get("option_type", "")).lower() == "call"]
        naked_calls = []
        if call_trades:
            # Get current stock positions to verify coverage
            try:
                resp = self._get("/positions")
                if resp.status_code == 200:
                    positions = resp.json().get("positions", [])
                    stock_symbols = {
                        p.get("symbol") for p in positions
                        if p.get("asset_class") != "us_option"
                    }
                    for ct in call_trades:
                        underlying = ct.get("underlying", "")
                        if underlying and underlying not in stock_symbols:
                            naked_calls.append(ct.get("symbol", "unknown"))
            except Exception:
                pass  # Position check failure is non-blocking here

        if naked_calls:
            checks.append(CheckResult(
                "trade_naked_calls", "fail",
                f"Naked calls detected: {naked_calls}",
                {"naked_call_symbols": naked_calls},
            ))
        else:
            checks.append(CheckResult(
                "trade_naked_calls", "pass",
                f"No naked calls ({len(call_trades)} call trades validated)",
            ))

        # -- No duplicate orders (same option_symbol within 5 minutes) --
        duplicates = []
        sorted_trades = sorted(trades, key=lambda t: t.get("timestamp_iso", ""))
        for i, trade in enumerate(sorted_trades):
            for j in range(i + 1, len(sorted_trades)):
                other = sorted_trades[j]
                if trade.get("symbol") == other.get("symbol"):
                    try:
                        t1 = datetime.fromisoformat(str(trade.get("timestamp_iso", "")))
                        t2 = datetime.fromisoformat(str(other.get("timestamp_iso", "")))
                        if abs((t2 - t1).total_seconds()) < DUPLICATE_ORDER_WINDOW_SECONDS:
                            duplicates.append(trade.get("symbol"))
                    except (ValueError, TypeError):
                        pass

        if duplicates:
            checks.append(CheckResult(
                "trade_duplicates", "warn",
                f"Possible duplicate orders: {set(duplicates)}",
                {"duplicate_symbols": list(set(duplicates))},
            ))
        else:
            checks.append(CheckResult(
                "trade_duplicates", "pass",
                "No duplicate orders detected",
            ))

        # -- client_order_id present --
        missing_client_id = [
            t.get("symbol", "unknown")
            for t in trades
            if not t.get("client_order_id")
        ]
        if missing_client_id:
            checks.append(CheckResult(
                "trade_client_order_id", "warn",
                f"{len(missing_client_id)} trades missing client_order_id",
                {"symbols": missing_client_id[:10]},
            ))
        else:
            checks.append(CheckResult(
                "trade_client_order_id", "pass",
                "All trades have client_order_id",
            ))

        # -- Premium values within bounds --
        bad_premiums = []
        for t in trades:
            premium = t.get("premium")
            if premium is not None:
                try:
                    pval = float(premium)
                    if pval <= 0 or pval < PREMIUM_MIN or pval > PREMIUM_MAX:
                        bad_premiums.append({
                            "symbol": t.get("symbol", "unknown"),
                            "premium": pval,
                        })
                except (ValueError, TypeError):
                    bad_premiums.append({
                        "symbol": t.get("symbol", "unknown"),
                        "premium": premium,
                    })

        if bad_premiums:
            checks.append(CheckResult(
                "trade_premiums", "warn",
                f"{len(bad_premiums)} trades with out-of-bounds premiums",
                {"bad_premiums": bad_premiums[:10]},
            ))
        else:
            checks.append(CheckResult(
                "trade_premiums", "pass",
                "All premium values within reasonable bounds",
            ))

        self.results.extend(checks)
        return checks

    # ------------------------------------------------------------------
    # 3. Log analysis (Cloud Logging)
    # ------------------------------------------------------------------

    def check_logs(self) -> List[CheckResult]:
        """Analyze Cloud Logging for error rates and known error patterns."""
        checks: List[CheckResult] = []

        try:
            from google.cloud import logging as cloud_logging
            logging_client = cloud_logging.Client(project=GCP_PROJECT)
        except Exception as exc:
            checks.append(CheckResult(
                "logs_client", "warn",
                f"Cannot connect to Cloud Logging: {exc}",
            ))
            self.results.extend(checks)
            return checks

        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat("T") + "Z"

        # -- Error count in last hour --
        error_filter = (
            f'resource.labels.service_name="options-wheel-strategy" '
            f'severity>=ERROR '
            f'timestamp>="{one_hour_ago}"'
        )

        try:
            error_entries = list(logging_client.list_entries(
                filter_=error_filter,
                order_by="timestamp desc",
                page_size=100,
            ))
            error_count = len(error_entries)

            if error_count >= ERROR_CRITICAL_THRESHOLD:
                status = "fail"
                msg = f"Critical error rate: {error_count} errors in the last hour"
            elif error_count >= ERROR_WARNING_THRESHOLD:
                status = "warn"
                msg = f"Elevated error rate: {error_count} errors in the last hour"
            else:
                status = "pass"
                msg = f"Error rate normal: {error_count} errors in the last hour"

            checks.append(CheckResult(
                "logs_error_rate", status, msg,
                {"error_count": error_count, "threshold_warn": ERROR_WARNING_THRESHOLD,
                 "threshold_critical": ERROR_CRITICAL_THRESHOLD},
            ))
        except Exception as exc:
            checks.append(CheckResult(
                "logs_error_rate", "warn",
                f"Error rate query failed: {exc}",
            ))

        # -- Critical error patterns --
        for pattern in CRITICAL_ERROR_PATTERNS:
            pattern_filter = (
                f'resource.labels.service_name="options-wheel-strategy" '
                f'jsonPayload.event_type="{pattern}" '
                f'timestamp>="{one_hour_ago}"'
            )
            try:
                pattern_entries = list(logging_client.list_entries(
                    filter_=pattern_filter,
                    page_size=10,
                ))
                if pattern_entries:
                    checks.append(CheckResult(
                        f"logs_pattern_{pattern}", "fail",
                        f"Critical pattern detected: {pattern} ({len(pattern_entries)} occurrences)",
                        {"pattern": pattern, "count": len(pattern_entries)},
                    ))
                else:
                    checks.append(CheckResult(
                        f"logs_pattern_{pattern}", "pass",
                        f"No occurrences of {pattern}",
                    ))
            except Exception as exc:
                checks.append(CheckResult(
                    f"logs_pattern_{pattern}", "warn",
                    f"Pattern query failed for {pattern}: {exc}",
                ))

        # -- request_id correlation present --
        missing_reqid_filter = (
            f'resource.labels.service_name="options-wheel-strategy" '
            f'NOT jsonPayload.request_id:* '
            f'jsonPayload.event_category:* '
            f'timestamp>="{one_hour_ago}"'
        )
        try:
            missing_entries = list(logging_client.list_entries(
                filter_=missing_reqid_filter,
                page_size=50,
            ))
            if len(missing_entries) > 10:
                checks.append(CheckResult(
                    "logs_request_id", "warn",
                    f"{len(missing_entries)} log entries missing request_id",
                    {"missing_count": len(missing_entries)},
                ))
            else:
                checks.append(CheckResult(
                    "logs_request_id", "pass",
                    "request_id correlation present in logs",
                ))
        except Exception as exc:
            checks.append(CheckResult(
                "logs_request_id", "warn",
                f"request_id check failed: {exc}",
            ))

        # -- event_category populated --
        missing_category_filter = (
            f'resource.labels.service_name="options-wheel-strategy" '
            f'NOT jsonPayload.event_category:* '
            f'jsonPayload.event_type:* '
            f'timestamp>="{one_hour_ago}"'
        )
        try:
            missing_cat_entries = list(logging_client.list_entries(
                filter_=missing_category_filter,
                page_size=50,
            ))
            if len(missing_cat_entries) > 5:
                checks.append(CheckResult(
                    "logs_event_category", "warn",
                    f"{len(missing_cat_entries)} log entries missing event_category (won't export to BigQuery)",
                    {"missing_count": len(missing_cat_entries)},
                ))
            else:
                checks.append(CheckResult(
                    "logs_event_category", "pass",
                    "event_category populated in logs",
                ))
        except Exception as exc:
            checks.append(CheckResult(
                "logs_event_category", "warn",
                f"event_category check failed: {exc}",
            ))

        self.results.extend(checks)
        return checks

    # ------------------------------------------------------------------
    # 4. Position reconciliation
    # ------------------------------------------------------------------

    def check_position_reconciliation(self) -> List[CheckResult]:
        """Compare positions from /positions endpoint against Alpaca API directly."""
        checks: List[CheckResult] = []

        # Get positions from the app endpoint
        try:
            resp = self._get("/positions")
            if resp.status_code != 200:
                checks.append(CheckResult(
                    "reconcile_app_positions", "fail",
                    f"/positions returned HTTP {resp.status_code}",
                ))
                self.results.extend(checks)
                return checks
            app_positions = resp.json().get("positions", [])
        except Exception as exc:
            checks.append(CheckResult(
                "reconcile_app_positions", "fail",
                f"Cannot fetch app positions: {exc}",
            ))
            self.results.extend(checks)
            return checks

        # Get positions directly from Alpaca
        try:
            from src.utils.config import Config
            from src.api.alpaca_client import AlpacaClient

            config = Config()
            alpaca_client = AlpacaClient(config)
            alpaca_positions = alpaca_client.get_positions()
        except Exception as exc:
            checks.append(CheckResult(
                "reconcile_alpaca_positions", "warn",
                f"Cannot fetch Alpaca positions directly: {exc}",
            ))
            self.results.extend(checks)
            return checks

        # Compare: build symbol sets
        app_symbols = {p.get("symbol") for p in app_positions if p.get("symbol")}
        alpaca_symbols = {p.get("symbol") for p in alpaca_positions if p.get("symbol")}

        only_in_app = app_symbols - alpaca_symbols
        only_in_alpaca = alpaca_symbols - app_symbols

        if only_in_app or only_in_alpaca:
            checks.append(CheckResult(
                "reconcile_positions", "warn",
                "Position discrepancies detected",
                {
                    "only_in_app": list(only_in_app),
                    "only_in_alpaca": list(only_in_alpaca),
                    "app_count": len(app_symbols),
                    "alpaca_count": len(alpaca_symbols),
                },
            ))
        else:
            checks.append(CheckResult(
                "reconcile_positions", "pass",
                f"Positions match ({len(app_symbols)} positions reconciled)",
                {"count": len(app_symbols)},
            ))

        # Check for orphaned wheel states (options without underlying stock for calls)
        option_positions = [p for p in alpaca_positions if p.get("asset_class") == "us_option"]
        stock_symbols = {
            p.get("symbol") for p in alpaca_positions
            if p.get("asset_class") != "us_option"
        }

        import re
        orphaned = []
        for opt in option_positions:
            symbol = opt.get("symbol", "")
            # Call options should have corresponding stock
            if "C" in symbol:
                match = re.match(r"^([A-Z]+)", symbol)
                if match:
                    underlying = match.group(1)
                    if underlying not in stock_symbols:
                        orphaned.append(symbol)

        if orphaned:
            checks.append(CheckResult(
                "reconcile_orphaned", "warn",
                f"Orphaned call positions (no underlying stock): {orphaned}",
                {"orphaned_symbols": orphaned},
            ))
        else:
            checks.append(CheckResult(
                "reconcile_orphaned", "pass",
                "No orphaned call positions",
            ))

        self.results.extend(checks)
        return checks

    # ------------------------------------------------------------------
    # 5. Performance baseline comparison
    # ------------------------------------------------------------------

    def check_performance_baseline(self) -> List[CheckResult]:
        """Compare current metrics against rolling 7-day averages.

        Queries BigQuery performance logs to build a baseline, then checks
        whether recent values deviate by more than 2 standard deviations.
        """
        checks: List[CheckResult] = []

        try:
            from google.cloud import bigquery
            client = bigquery.Client(project=GCP_PROJECT)
        except Exception as exc:
            checks.append(CheckResult(
                "perf_bigquery_client", "warn",
                f"Cannot connect to BigQuery for performance check: {exc}",
            ))
            self.results.extend(checks)
            return checks

        seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        metrics_to_check = [
            ("market_scan_duration", "seconds"),
            ("strategy_execution_duration", "seconds"),
        ]

        for metric_name, unit in metrics_to_check:
            # Get 7-day baseline
            baseline_query = f"""
                SELECT
                    metric_value
                FROM `{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}`
                WHERE event_category = 'performance'
                  AND metric_name = '{metric_name}'
                  AND timestamp_iso >= '{seven_days_ago}'
                  AND timestamp_iso < '{one_hour_ago}'
            """

            try:
                baseline_rows = list(client.query(baseline_query).result())
                baseline_values = [float(r["metric_value"]) for r in baseline_rows if r.get("metric_value") is not None]
            except Exception as exc:
                checks.append(CheckResult(
                    f"perf_baseline_{metric_name}", "warn",
                    f"Baseline query failed for {metric_name}: {exc}",
                ))
                continue

            if len(baseline_values) < 3:
                checks.append(CheckResult(
                    f"perf_baseline_{metric_name}", "pass",
                    f"Insufficient baseline data for {metric_name} ({len(baseline_values)} samples)",
                ))
                continue

            mean = statistics.mean(baseline_values)
            stdev = statistics.stdev(baseline_values)

            # Get recent values
            recent_query = f"""
                SELECT
                    metric_value
                FROM `{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}`
                WHERE event_category = 'performance'
                  AND metric_name = '{metric_name}'
                  AND timestamp_iso >= '{one_hour_ago}'
            """

            try:
                recent_rows = list(client.query(recent_query).result())
                recent_values = [float(r["metric_value"]) for r in recent_rows if r.get("metric_value") is not None]
            except Exception as exc:
                checks.append(CheckResult(
                    f"perf_recent_{metric_name}", "warn",
                    f"Recent query failed for {metric_name}: {exc}",
                ))
                continue

            if not recent_values:
                checks.append(CheckResult(
                    f"perf_baseline_{metric_name}", "pass",
                    f"No recent data for {metric_name} (nothing to compare)",
                ))
                continue

            recent_mean = statistics.mean(recent_values)

            if stdev > 0:
                z_score = abs(recent_mean - mean) / stdev
            else:
                z_score = 0.0

            details = {
                "metric": metric_name,
                "unit": unit,
                "baseline_mean": round(mean, 3),
                "baseline_stdev": round(stdev, 3),
                "recent_mean": round(recent_mean, 3),
                "z_score": round(z_score, 2),
                "baseline_samples": len(baseline_values),
                "recent_samples": len(recent_values),
            }

            if z_score > METRIC_DEVIATION_THRESHOLD:
                checks.append(CheckResult(
                    f"perf_baseline_{metric_name}", "warn",
                    f"{metric_name} deviates {z_score:.1f} std devs from baseline "
                    f"(recent={recent_mean:.2f}{unit}, baseline={mean:.2f}+/-{stdev:.2f}{unit})",
                    details,
                ))
            else:
                checks.append(CheckResult(
                    f"perf_baseline_{metric_name}", "pass",
                    f"{metric_name} within normal range (z={z_score:.1f})",
                    details,
                ))

        self.results.extend(checks)
        return checks

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 6. Risk parameter validation
    # ------------------------------------------------------------------

    def check_risk_parameters(self) -> List[CheckResult]:
        """Validate all risk guardrails against live positions and account.

        Checks every risk rule from config/settings.yaml against the current
        state of the account, positions, and recent trades.
        """
        checks: List[CheckResult] = []

        # --- Fetch live data ---
        try:
            account_resp = self._get("/account")
            account = account_resp.json() if account_resp.status_code == 200 else {}
        except Exception:
            account = {}

        try:
            positions_resp = self._get("/positions")
            positions = positions_resp.json() if positions_resp.status_code == 200 else []
            if isinstance(positions, dict):
                positions = positions.get("positions", [])
        except Exception:
            positions = []

        portfolio_value = float(account.get("portfolio_value", 0))
        cash = float(account.get("cash", 0))
        buying_power = float(account.get("buying_power", 0))

        if portfolio_value <= 0:
            checks.append(CheckResult(
                "risk_account_data", "fail",
                "Cannot validate risk: portfolio_value is 0 or unavailable",
            ))
            return checks

        checks.append(CheckResult("risk_account_data", "pass", f"Portfolio value: ${portfolio_value:,.2f}"))

        # Separate stock and option positions
        stock_positions = [p for p in positions if p.get("asset_class") == "us_equity"]
        option_positions = [p for p in positions if p.get("asset_class") == "us_option"]

        # --- 1. Max total positions (10) ---
        total_positions = len(option_positions)
        if total_positions > 10:
            checks.append(CheckResult(
                "risk_max_total_positions", "fail",
                f"Total option positions ({total_positions}) exceeds max_total_positions (10)",
                {"total_positions": total_positions},
            ))
        else:
            checks.append(CheckResult(
                "risk_max_total_positions", "pass",
                f"Total option positions ({total_positions}) within limit (10)",
            ))

        # --- 2. Max positions per stock (1) ---
        underlying_counts: Dict[str, int] = {}
        for pos in option_positions:
            symbol = pos.get("symbol", "")
            # Extract underlying from option symbol (letters before first digit)
            underlying = ""
            for ch in symbol:
                if ch.isdigit():
                    break
                underlying += ch
            underlying_counts[underlying] = underlying_counts.get(underlying, 0) + 1

        duplicates = {k: v for k, v in underlying_counts.items() if v > 1}
        if duplicates:
            checks.append(CheckResult(
                "risk_max_positions_per_stock", "fail",
                f"Multiple positions for same underlying: {duplicates}",
                {"duplicates": duplicates},
            ))
        else:
            checks.append(CheckResult(
                "risk_max_positions_per_stock", "pass",
                "No duplicate underlying positions",
            ))

        # --- 3. Min cash reserve (20%) ---
        cash_pct = cash / portfolio_value if portfolio_value > 0 else 0
        if cash_pct < 0.20:
            checks.append(CheckResult(
                "risk_min_cash_reserve", "warn",
                f"Cash reserve ({cash_pct:.1%}) below minimum (20%)",
                {"cash": cash, "portfolio_value": portfolio_value, "cash_pct": round(cash_pct, 4)},
            ))
        else:
            checks.append(CheckResult(
                "risk_min_cash_reserve", "pass",
                f"Cash reserve ({cash_pct:.1%}) meets minimum (20%)",
            ))

        # --- 4. Max single position size (35%) ---
        for pos in positions:
            market_value = abs(float(pos.get("market_value", 0)))
            pos_pct = market_value / portfolio_value if portfolio_value > 0 else 0
            if pos_pct > 0.35:
                checks.append(CheckResult(
                    "risk_max_position_size", "fail",
                    f"Position {pos.get('symbol')} is {pos_pct:.1%} of portfolio (max 35%)",
                    {"symbol": pos.get("symbol"), "market_value": market_value, "pct": round(pos_pct, 4)},
                ))

        if not any(r.name == "risk_max_position_size" for r in checks):
            checks.append(CheckResult("risk_max_position_size", "pass", "All positions within 35% limit"))

        # --- 5. Max portfolio allocation (80%) ---
        total_position_value = sum(abs(float(p.get("market_value", 0))) for p in positions)
        allocation_pct = total_position_value / portfolio_value if portfolio_value > 0 else 0
        if allocation_pct > 0.80:
            checks.append(CheckResult(
                "risk_max_portfolio_allocation", "warn",
                f"Portfolio allocation ({allocation_pct:.1%}) exceeds 80% limit",
                {"total_position_value": total_position_value, "allocation_pct": round(allocation_pct, 4)},
            ))
        else:
            checks.append(CheckResult(
                "risk_max_portfolio_allocation", "pass",
                f"Portfolio allocation ({allocation_pct:.1%}) within 80% limit",
            ))

        # --- 6. Max exposure per ticker ($40,000) ---
        ticker_exposure: Dict[str, float] = {}
        for pos in positions:
            symbol = pos.get("symbol", "")
            underlying = ""
            for ch in symbol:
                if ch.isdigit():
                    break
                underlying += ch
            exposure = abs(float(pos.get("market_value", 0)))
            ticker_exposure[underlying] = ticker_exposure.get(underlying, 0) + exposure

        over_exposed = {k: v for k, v in ticker_exposure.items() if v > 40000}
        if over_exposed:
            checks.append(CheckResult(
                "risk_max_exposure_per_ticker", "fail",
                f"Tickers exceeding $40k exposure: {over_exposed}",
                {"over_exposed": {k: round(v, 2) for k, v in over_exposed.items()}},
            ))
        else:
            checks.append(CheckResult(
                "risk_max_exposure_per_ticker", "pass",
                "All tickers within $40k exposure limit",
            ))

        # --- 7. Naked call detection (calls must have underlying shares) ---
        stock_symbols = {p.get("symbol") for p in stock_positions}
        stock_qty = {p.get("symbol"): int(float(p.get("qty", 0))) for p in stock_positions}

        for pos in option_positions:
            symbol = pos.get("symbol", "")
            qty = abs(int(float(pos.get("qty", 0))))
            side = pos.get("side", "")

            # Detect short calls (sold calls)
            is_short_call = ("C" in symbol and side == "short") or \
                            ("C" in symbol and float(pos.get("qty", 0)) < 0)

            if is_short_call:
                underlying = ""
                for ch in symbol:
                    if ch.isdigit():
                        break
                    underlying += ch

                owned_shares = stock_qty.get(underlying, 0)
                required_shares = qty * 100

                if owned_shares < required_shares:
                    checks.append(CheckResult(
                        "risk_naked_call", "fail",
                        f"Naked call detected: {symbol} (need {required_shares} shares of {underlying}, own {owned_shares})",
                        {"option_symbol": symbol, "underlying": underlying,
                         "required_shares": required_shares, "owned_shares": owned_shares},
                    ))

        if not any(r.name == "risk_naked_call" for r in checks):
            checks.append(CheckResult("risk_naked_call", "pass", "No naked calls detected"))

        # --- 8. Cost basis protection (call strikes >= cost basis) ---
        for pos in option_positions:
            symbol = pos.get("symbol", "")
            if "C" not in symbol or float(pos.get("qty", 0)) >= 0:
                continue  # Only check short calls

            underlying = ""
            for ch in symbol:
                if ch.isdigit():
                    break
                underlying += ch

            # Extract strike from OCC symbol (last 8 digits / 1000)
            try:
                strike = float(symbol[-8:]) / 1000.0
            except (ValueError, IndexError):
                continue

            stock_pos = next((p for p in stock_positions if p.get("symbol") == underlying), None)
            if stock_pos:
                cost_basis_per_share = float(stock_pos.get("cost_basis", 0)) / max(int(float(stock_pos.get("qty", 1))), 1)
                if cost_basis_per_share > 0 and strike < cost_basis_per_share:
                    checks.append(CheckResult(
                        "risk_cost_basis_protection", "fail",
                        f"Call {symbol} strike ${strike:.2f} below cost basis ${cost_basis_per_share:.2f}",
                        {"option_symbol": symbol, "strike": strike, "cost_basis": round(cost_basis_per_share, 2)},
                    ))

        if not any(r.name == "risk_cost_basis_protection" for r in checks):
            checks.append(CheckResult("risk_cost_basis_protection", "pass", "All call strikes above cost basis"))

        # --- 9. Recent trade validation (BigQuery) ---
        try:
            from google.cloud import bigquery
            bq = bigquery.Client(project=GCP_PROJECT)
            query = f"""
                SELECT symbol, option_type, premium, dte, strike_price, client_order_id
                FROM `{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}`
                WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
                ORDER BY timestamp DESC
                LIMIT 50
            """
            rows = list(bq.query(query).result())

            for row in rows:
                # Premium thresholds
                premium = float(row.get("premium") or 0)
                opt_type = row.get("option_type", "")
                if opt_type == "put" and 0 < premium < 0.50:
                    checks.append(CheckResult(
                        "risk_min_premium", "warn",
                        f"Put trade {row.get('symbol')} premium ${premium:.2f} below min ($0.50)",
                    ))
                elif opt_type == "call" and 0 < premium < 0.30:
                    checks.append(CheckResult(
                        "risk_min_premium", "warn",
                        f"Call trade {row.get('symbol')} premium ${premium:.2f} below min ($0.30)",
                    ))

                # client_order_id must be present
                if not row.get("client_order_id"):
                    checks.append(CheckResult(
                        "risk_client_order_id", "warn",
                        f"Trade {row.get('symbol')} missing client_order_id",
                    ))

            if not any(r.name == "risk_min_premium" for r in checks):
                checks.append(CheckResult("risk_min_premium", "pass", "All recent trade premiums meet minimums"))
            if not any(r.name == "risk_client_order_id" for r in checks):
                checks.append(CheckResult("risk_client_order_id", "pass", "All recent trades have client_order_id"))

        except ImportError:
            checks.append(CheckResult("risk_recent_trades", "warn", "BigQuery not available, skipping trade validation"))
        except Exception as exc:
            checks.append(CheckResult("risk_recent_trades", "warn", f"Trade validation query failed: {exc}"))

        return checks

    def run_all_checks(self) -> Dict[str, Any]:
        """Execute all regression checks and return a consolidated report."""
        self.results = []
        self.start_time = datetime.now(timezone.utc)

        check_groups = {
            "endpoint_health": self.check_endpoints,
            "trade_execution": self.check_trade_execution,
            "log_analysis": self.check_logs,
            "position_reconciliation": self.check_position_reconciliation,
            "performance_baseline": self.check_performance_baseline,
            "risk_parameters": self.check_risk_parameters,
        }

        group_results: Dict[str, List[Dict]] = {}
        for group_name, check_fn in check_groups.items():
            try:
                results = check_fn()
                group_results[group_name] = [r.to_dict() for r in results]
            except Exception as exc:
                group_results[group_name] = [
                    CheckResult(
                        f"{group_name}_exception", "fail",
                        f"Check group failed with exception: {exc}",
                        {"traceback": traceback.format_exc()},
                    ).to_dict()
                ]

        duration_seconds = (datetime.now(timezone.utc) - self.start_time).total_seconds()

        # Aggregate status
        all_statuses = [r["status"] for group in group_results.values() for r in group]
        has_failures = "fail" in all_statuses
        has_warnings = "warn" in all_statuses

        if has_failures:
            overall_status = "fail"
        elif has_warnings:
            overall_status = "warn"
        else:
            overall_status = "pass"

        report = {
            "overall_status": overall_status,
            "timestamp": self.start_time.isoformat(),
            "duration_seconds": round(duration_seconds, 2),
            "summary": {
                "total_checks": len(all_statuses),
                "passed": all_statuses.count("pass"),
                "warnings": all_statuses.count("warn"),
                "failures": all_statuses.count("fail"),
            },
            "check_groups": group_results,
        }

        # Log via structlog with event_category for BigQuery export
        log_system_event(
            logger,
            event_type="regression_test_completed",
            status=overall_status,
            duration_seconds=round(duration_seconds, 2),
            total_checks=len(all_statuses),
            passed=all_statuses.count("pass"),
            warnings=all_statuses.count("warn"),
            failures=all_statuses.count("fail"),
        )

        log_performance_metric(
            logger,
            metric_name="regression_test_duration",
            metric_value=round(duration_seconds, 2),
            metric_unit="seconds",
            total_checks=len(all_statuses),
            overall_status=overall_status,
        )

        if has_failures:
            failed_checks = [
                r["name"] for group in group_results.values()
                for r in group if r["status"] == "fail"
            ]
            log_error_event(
                logger,
                error_type="regression_test_failures",
                error_message=f"{len(failed_checks)} regression checks failed: {failed_checks}",
                component="regression_monitor",
                recoverable=True,
                failed_checks=failed_checks,
            )

        return report


# ---------------------------------------------------------------------------
# Flask app for standalone deployment
# ---------------------------------------------------------------------------

def create_app() -> "Flask":
    """Create a minimal Flask app for standalone deployment."""
    from flask import Flask, jsonify, request as flask_request

    standalone_app = Flask(__name__)

    @standalone_app.route("/", methods=["GET"])
    def health():
        return jsonify({"status": "healthy", "service": "regression-monitor"})

    @standalone_app.route("/regression", methods=["POST"])
    def run_regression():
        monitor = RegressionMonitor()
        report = monitor.run_all_checks()
        status_code = 200 if report["overall_status"] != "fail" else 500
        return jsonify(report), status_code

    return standalone_app


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """Run regression checks from the command line."""
    import argparse

    parser = argparse.ArgumentParser(description="Options Wheel Regression Monitor")
    parser.add_argument("--url", default=SERVICE_URL, help="Service URL to test")
    parser.add_argument("--api-key", default=os.environ.get("STRATEGY_API_KEY", ""), help="API key")
    parser.add_argument("--serve", action="store_true", help="Start as a web server")
    parser.add_argument("--port", type=int, default=8081, help="Port for web server mode")
    args = parser.parse_args()

    if args.serve:
        app = create_app()
        app.run(host="0.0.0.0", port=args.port, debug=False)
        return

    print(f"Running regression checks against {args.url}")
    print("=" * 70)

    monitor = RegressionMonitor(service_url=args.url, api_key=args.api_key)
    report = monitor.run_all_checks()

    # Print summary
    summary = report["summary"]
    overall = report["overall_status"].upper()
    print(f"\nOverall: {overall}")
    print(f"Checks: {summary['total_checks']} total, "
          f"{summary['passed']} passed, "
          f"{summary['warnings']} warnings, "
          f"{summary['failures']} failures")
    print(f"Duration: {report['duration_seconds']}s")

    # Print details for non-passing checks
    for group_name, group_checks in report["check_groups"].items():
        non_pass = [c for c in group_checks if c["status"] != "pass"]
        if non_pass:
            print(f"\n--- {group_name} ---")
            for check in non_pass:
                print(f"  [{check['status'].upper()}] {check['name']}: {check['message']}")

    # Print full report as JSON
    print("\n" + "=" * 70)
    print("Full report:")
    print(json.dumps(report, indent=2, default=str))

    # Exit with appropriate code
    sys.exit(1 if report["overall_status"] == "fail" else 0)


if __name__ == "__main__":
    main()
