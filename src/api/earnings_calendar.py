"""Earnings Calendar Service using Finnhub API.

Plan: docs/plans/fc-007.md

Provides earnings date lookups for trade decision gating (earnings blackout)
and log enrichment (earnings proximity on all trade events). Uses in-memory
caching with configurable TTL to minimize API calls.

Graceful degradation: fails open (allows trading) on API errors.
"""

import os
from datetime import date, datetime, timedelta
from typing import Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


class EarningsCalendarService:
    """Shared earnings calendar service backed by Finnhub.

    Consumers: PutSeller, CallSeller, CallRoller (FC-006), WheelEngine.
    """

    def __init__(self, config):
        """Initialize earnings calendar service.

        Args:
            config: Config instance with finnhub_api_key and earnings settings.
        """
        self._cache: Dict[str, Dict] = {}
        self._failure_cache: Dict[str, datetime] = {}
        self._client = None

        api_key = config.finnhub_api_key
        if not api_key:
            logger.warning(
                "Finnhub API key not configured, earnings calendar disabled",
                event_category="system",
                event_type="earnings_calendar_disabled",
            )
            return

        try:
            import finnhub
            self._client = finnhub.Client(api_key=api_key)
        except ImportError:
            logger.error(
                "finnhub-python package not installed",
                event_category="error",
                event_type="earnings_calendar_import_error",
                component="earnings_calendar",
                recoverable=True,
            )

        self._cache_ttl_hours = config.earnings_cache_ttl_hours
        self._lookahead_days = config.earnings_lookahead_days
        self._enabled = config.earnings_enabled

    def is_earnings_within_n_days(self, symbol: str, n_days: int) -> bool:
        """Check if a symbol has earnings within the next N calendar days.

        Returns False (allow trading) on API errors — fails open.

        Args:
            symbol: Stock ticker symbol.
            n_days: Number of days to look ahead.

        Returns:
            True if earnings are within n_days, False otherwise.
        """
        if not self._enabled or not self._client:
            return False

        proximity = self.get_earnings_proximity(symbol)
        if proximity["days_until"] is None:
            return False

        return proximity["days_until"] <= n_days

    def get_next_earnings_date(self, symbol: str) -> Optional[date]:
        """Get the next earnings date for a symbol.

        Args:
            symbol: Stock ticker symbol.

        Returns:
            Next earnings date, or None if unknown/unavailable.
        """
        if not self._enabled or not self._client:
            return None

        cached = self._get_cached(symbol)
        if cached is not None:
            return cached.get("date")

        fetched = self._fetch_earnings(symbol)
        if fetched:
            return fetched.get("date")
        return None

    def get_earnings_proximity(self, symbol: str) -> Dict:
        """Get earnings proximity info for log enrichment.

        Returns a dict suitable for passing as kwargs to log_trade_event.

        Args:
            symbol: Stock ticker symbol.

        Returns:
            Dict with keys: next_earnings_date (str|None), days_until (int|None),
            earnings_hour (str|None).
        """
        result = {
            "next_earnings_date": None,
            "days_until": None,
            "earnings_hour": None,
        }

        if not self._enabled or not self._client:
            return result

        cached = self._get_cached(symbol)
        if cached is None:
            cached = self._fetch_earnings(symbol)

        if cached and cached.get("date"):
            earnings_date = cached["date"]
            result["next_earnings_date"] = earnings_date.isoformat()
            result["days_until"] = (earnings_date - date.today()).days
            result["earnings_hour"] = cached.get("hour") or None

        return result

    def _get_cached(self, symbol: str) -> Optional[Dict]:
        """Return cached earnings data if still valid, else None."""
        if symbol not in self._cache:
            return None

        entry = self._cache[symbol]
        age_hours = (datetime.now() - entry["fetched_at"]).total_seconds() / 3600
        if age_hours > self._cache_ttl_hours:
            del self._cache[symbol]
            return None

        return entry

    def _fetch_earnings(self, symbol: str) -> Optional[Dict]:
        """Query Finnhub for next earnings date and cache the result.

        On failure, caches the error for 1 hour and returns None (fail open).
        """
        if symbol in self._failure_cache:
            failure_age = (datetime.now() - self._failure_cache[symbol]).total_seconds() / 3600
            if failure_age < 1.0:
                return None
            del self._failure_cache[symbol]

        try:
            today = date.today()
            end = today + timedelta(days=self._lookahead_days)
            result = self._client.earnings_calendar(
                _from=today.isoformat(),
                to=end.isoformat(),
                symbol=symbol,
            )

            calendar = result.get("earningsCalendar", [])
            if not calendar:
                entry = {"date": None, "hour": None, "fetched_at": datetime.now()}
                self._cache[symbol] = entry
                return entry

            earliest = min(calendar, key=lambda x: x.get("date", "9999-99-99"))
            earnings_date = date.fromisoformat(earliest["date"])
            entry = {
                "date": earnings_date,
                "hour": earliest.get("hour", ""),
                "fetched_at": datetime.now(),
            }
            self._cache[symbol] = entry

            logger.debug(
                "Fetched earnings date",
                event_category="system",
                event_type="earnings_date_fetched",
                symbol=symbol,
                earnings_date=earnings_date.isoformat(),
                hour=entry["hour"],
            )
            return entry

        except Exception as e:
            self._failure_cache[symbol] = datetime.now()
            from src.utils.logging_events import log_error_event
            log_error_event(
                logger,
                error_type="earnings_fetch_failed",
                error_message=str(e),
                component="earnings_calendar",
                recoverable=True,
                symbol=symbol,
            )
            return None
