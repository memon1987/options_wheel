"""Earnings Calendar Service using Finnhub API.

Plan: docs/plans/fc-007.md (original), docs/plans/fc-013.md (rev 2.2 — the gate)

Provides earnings date lookups for trade decision gating (earnings blackout)
and log enrichment (earnings proximity on all trade events).

**Two surfaces, two failure postures — deliberately.**

``is_earnings_within_n_days`` / ``get_next_earnings_date`` /
``get_earnings_proximity`` are the *roller's* contract (FC-006/FC-007). They
fail OPEN: an API error answers "no earnings", allowing the roll. FC-013's
operator decision keeps the roller's behaviour exactly as-is, so those three
methods are untouched.

``next_earnings_info`` / ``earnings_within`` are FC-013's tri-state surface for
the *scanner's* gate. They distinguish "no earnings in the lookahead" (clear —
allow) from "could not determine" (unknown — the gate skips the symbol, fail
CLOSED). Rev 1 of FC-013 tried to reuse the boolean surface by flipping its
error paths to ``True``; that conflated the two states and would have blocked
every known-clear symbol — an account-wide brick on a normal day. Hence a
separate method rather than a changed one.

**Caching is two-layer (FC-013 §Approach 1).** L1 is module-scope, not instance-
scope: ``/scan`` builds a fresh ``OptionsScanner`` per request, so an instance
cache never survived a single request. L2 is a small GCS blob, because the
service runs at ``min-instances=0`` and the module cache is cold nearly every
scan. GCS trouble is a cache MISS, never a block — only Finnhub's answer, or
its absence, decides gate state.
"""

import json
import os
from datetime import date, datetime, timedelta
from typing import Dict, Optional, Tuple

import structlog

from ..utils import clock

logger = structlog.get_logger(__name__)

# --------------------------------------------------------------------------- #
# The tri-state vocabulary (FC-013 DD-2)
# --------------------------------------------------------------------------- #
EARNINGS_KNOWN = "known"      # a date inside the lookahead
EARNINGS_CLEAR = "clear"      # fetch succeeded, nothing inside the lookahead
EARNINGS_UNKNOWN = "unknown"  # could not determine -> the gate skips the symbol

# --------------------------------------------------------------------------- #
# L1 — module scope
# --------------------------------------------------------------------------- #
# Instance scope was fictional at request scope (FC-013 Context finding 1):
# `/scan` constructs a fresh OptionsScanner — and therefore a fresh service —
# per request, so `earnings.cache_ttl_hours` never governed anything.
_EARNINGS_CACHE: Dict[str, Dict] = {}
_EARNINGS_FAILURE_CACHE: Dict[str, datetime] = {}
# Whether this process has already attempted the one L2 read. Set even on a
# failed read: a broken GCS path must not be retried once per symbol.
_L2_HYDRATED = False

L2_BLOB_NAME = "earnings_cache.json"


def clear_earnings_cache() -> None:
    """Drop every cached entry and re-arm the L2 read. For tests and ops.

    Module-scope state that leaks between tests is the ``_reset_time_seam``
    lesson; ``tests/conftest.py`` calls this before and after every test.
    """
    global _L2_HYDRATED
    _EARNINGS_CACHE.clear()
    _EARNINGS_FAILURE_CACHE.clear()
    _L2_HYDRATED = False


def _as_int(value, default: int) -> int:
    """Coerce a config value to int, falling back rather than raising.

    Config objects in this suite are frequently ``Mock``s; a half-built service
    that raises on arithmetic is precisely the failure mode the constructor fix
    exists to remove.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class EarningsCalendarService:
    """Shared earnings calendar service backed by Finnhub.

    Consumers: ``OptionsScanner`` (FC-013 gate, tri-state surface),
    ``CallRoller`` (FC-006, boolean surface).
    """

    def __init__(self, config):
        """Initialize earnings calendar service.

        **Every attribute is set on every construction path** (FC-013 rev 2.1,
        both plan reviewers). The pre-FC-013 constructor returned early on a
        missing key *before* assigning ``_cache_ttl_hours`` / ``_lookahead_days``
        / ``_enabled``, so every later method call raised ``AttributeError`` —
        which the scanner's broad ``except`` misfiled as ``scan_failure``,
        producing zero opportunities *and* zero gate telemetry. A configured-
        but-unresolvable dependency must fail loudly, never silently no-op
        (FC-069 item 8), and never crash.

        Args:
            config: Config instance with finnhub_api_key and earnings settings.
        """
        self.config = config
        self._cache_ttl_hours = _as_int(
            getattr(config, "earnings_cache_ttl_hours", 24), 24)
        self._lookahead_days = _as_int(
            getattr(config, "earnings_lookahead_days", 90), 90)
        self._enabled = bool(getattr(config, "earnings_enabled", False))
        self._client = None

        api_key = getattr(config, "finnhub_api_key", "")
        if not api_key:
            self._degraded("Finnhub API key not configured")
            return

        try:
            import finnhub
            self._client = finnhub.Client(api_key=api_key)
        except ImportError as exc:
            logger.error(
                "finnhub-python package not installed",
                event_category="error",
                event_type="earnings_calendar_import_error",
                component="earnings_calendar",
                recoverable=True,
            )
            self._degraded(f"finnhub-python not importable: {exc}")

    def _degraded(self, why: str) -> None:
        """Record an enabled-but-unusable calendar, loudly.

        ``enabled: false`` and *broken* are different states with different
        behaviour, by design: disabled means no gate at all, broken means every
        symbol answers ``unknown`` and the gate fails closed on all of them.
        The second one must be visible within minutes, not weeks — hence the
        error event, which ``deploy/monitoring/earnings_gate_alert_policy.json``
        matches.
        """
        self._client = None
        if not self._enabled:
            logger.warning(
                "Earnings calendar unusable (gate disabled, so nothing is blocked)",
                event_category="system",
                event_type="earnings_calendar_disabled",
                reason=why,
            )
            return
        from ..utils.logging_events import log_error_event
        log_error_event(
            logger,
            error_type="earnings_gate_unusable",
            error_message=(
                f"earnings.enabled is true but the calendar cannot answer: {why}. "
                "Every symbol will report 'unknown' and the scanner gate will "
                "fail closed on both legs until this is fixed."
            ),
            component="earnings_calendar",
            recoverable=True,
        )

    # ------------------------------------------------------------------ #
    # FC-013 — the tri-state surface the scanner gate consumes
    # ------------------------------------------------------------------ #
    def next_earnings_info(self, symbol: str) -> Tuple[str, Optional[date]]:
        """The gate's primary question: what do we know about ``symbol``?

        Returns:
            ``('known', date)``  — earnings inside the lookahead window.
            ``('clear', None)``  — the fetch succeeded and found none.
            ``('unknown', None)`` — could not determine (no client, no key,
                Finnhub error, or inside the 1h failure-cache window). The gate
                skips the symbol on BOTH legs; a span test needs a date, and no
                date means no candidate can be cleared.
        """
        if not self._client:
            return (EARNINGS_UNKNOWN, None)

        entry = self._get_cached(symbol)
        if entry is None:
            entry = self._fetch_earnings(symbol)
        if entry is None:
            return (EARNINGS_UNKNOWN, None)

        earnings_date = entry.get("date")
        if earnings_date is None:
            return (EARNINGS_CLEAR, None)
        return (EARNINGS_KNOWN, earnings_date)

    def earnings_within(self, symbol: str, n_days: int) -> Optional[bool]:
        """The put leg's predicate — tri-state, derived from the date.

        ``None`` means "could not tell" and is NOT ``False``. That distinction
        is the whole point: ``False`` allows the trade, ``None`` blocks it.

        The window is inclusive at both ends and counted in **calendar** days:
        day-of (0) is blocked. Trading-day semantics were considered and
        rejected (market-calendar dependency; the weekend asymmetry is stated
        and accepted — FC-013 DD-3).
        """
        status, earnings_date = self.next_earnings_info(symbol)
        if status == EARNINGS_UNKNOWN:
            return None
        if status == EARNINGS_CLEAR:
            return False
        return 0 <= (earnings_date - clock.now().date()).days <= n_days

    # ------------------------------------------------------------------ #
    # The roller's contract — behaviour unchanged (FC-013 DD-5, operator)
    # ------------------------------------------------------------------ #
    def is_earnings_within_n_days(self, symbol: str, n_days: int) -> bool:
        """Check if a symbol has earnings within the next N calendar days.

        Returns False (allow trading) on API errors — **fails open**. This is
        the roller's gate and the operator decided it keeps its existing
        behaviour; FC-013's fail-closed semantics live in ``earnings_within``.

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

    # ------------------------------------------------------------------ #
    # Cache — L1 (module) over L2 (GCS blob)
    # ------------------------------------------------------------------ #
    def _get_cached(self, symbol: str) -> Optional[Dict]:
        """Return cached earnings data if still valid, else None.

        Ladder: L1 -> L2 -> None (which makes the caller fetch). The L2 read is
        one blob for the whole universe, attempted once per process.
        """
        entry = _EARNINGS_CACHE.get(symbol)
        if entry is None:
            self._hydrate_from_l2()
            entry = _EARNINGS_CACHE.get(symbol)
        if entry is None:
            return None

        if self._is_stale(entry):
            # `.pop`, never bare `del`: `/scan` runs under `strategy_lock` so
            # mutation is de facto serialized, but a future concurrent caller
            # must not be able to KeyError here (FC-013 §1, trader MEDIUM-7).
            _EARNINGS_CACHE.pop(symbol, None)
            return None

        return entry

    def _is_stale(self, entry: Dict) -> bool:
        fetched_at = entry.get("fetched_at")
        if not isinstance(fetched_at, datetime):
            return True
        age_hours = (datetime.now() - fetched_at).total_seconds() / 3600
        return age_hours > self._cache_ttl_hours

    def _fetch_earnings(self, symbol: str) -> Optional[Dict]:
        """Query Finnhub for next earnings date and cache the result.

        On failure, caches the error for 1 hour and returns None. ``None`` is
        the *unknown* signal — ``next_earnings_info`` turns it into a fail-closed
        skip; the roller-facing methods still fail open on it.
        """
        if symbol in _EARNINGS_FAILURE_CACHE:
            failure_age = (
                datetime.now() - _EARNINGS_FAILURE_CACHE[symbol]
            ).total_seconds() / 3600
            if failure_age < 1.0:
                return None
            _EARNINGS_FAILURE_CACHE.pop(symbol, None)

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
                _EARNINGS_CACHE[symbol] = entry
                # A 200 with an empty calendar is cached as known-CLEAR. That is
                # correct for ETFs (IWM/QQQ/SPY) and genuine quiet windows, but a
                # coverage regression on Finnhub's side would read as permanently
                # clear — a silent fail-open for that symbol. Accepted (treating
                # empty as unknown bricks every ETF), and made visible here plus
                # retrospectively by tools/diagnostics/fc013_earnings_exposure_audit.py,
                # which cross-checks fills against the independent yfinance table.
                logger.debug(
                    "Fetched earnings calendar (empty)",
                    event_category="system",
                    event_type="earnings_date_fetched",
                    symbol=symbol,
                    calendar_empty=True,
                )
                self._store_to_l2()
                return entry

            earliest = min(calendar, key=lambda x: x.get("date", "9999-99-99"))
            earnings_date = date.fromisoformat(earliest["date"])
            entry = {
                "date": earnings_date,
                "hour": earliest.get("hour", ""),
                "fetched_at": datetime.now(),
            }
            _EARNINGS_CACHE[symbol] = entry

            logger.debug(
                "Fetched earnings date",
                event_category="system",
                event_type="earnings_date_fetched",
                symbol=symbol,
                earnings_date=earnings_date.isoformat(),
                hour=entry["hour"],
                calendar_empty=False,
            )
            self._store_to_l2()
            return entry

        except Exception as e:
            _EARNINGS_FAILURE_CACHE[symbol] = datetime.now()
            from ..utils.logging_events import log_error_event
            log_error_event(
                logger,
                error_type="earnings_fetch_failed",
                error_message=str(e),
                component="earnings_calendar",
                recoverable=True,
                symbol=symbol,
            )
            return None

    # ------------------------------------------------------------------ #
    # L2 — the durable blob
    # ------------------------------------------------------------------ #
    #
    # Patched to no-ops class-wide in tests/conftest.py, the same way the
    # BigQuery chokepoints are: no unit test may touch GCS.
    def _hydrate_from_l2(self) -> None:
        """Populate L1 from the durable blob, once per process.

        Every failure mode here — no bucket, no credentials, no blob, malformed
        JSON — is a cache MISS. The blob can never block a trade by itself;
        only Finnhub's answer or its absence decides gate state.
        """
        global _L2_HYDRATED
        if _L2_HYDRATED:
            return
        # Set first: a broken GCS path must cost one attempt per process, not
        # one per symbol per scan.
        _L2_HYDRATED = True
        payload = self._l2_read()
        if not payload:
            return
        for symbol, raw in payload.items():
            entry = _decode_entry(raw)
            if entry is None or self._is_stale(entry):
                continue
            _EARNINGS_CACHE.setdefault(symbol, entry)

    def _l2_read(self) -> Optional[Dict[str, Dict]]:
        """Read and parse the durable cache blob, or None on any trouble."""
        try:
            from google.cloud import storage
            client = storage.Client()
            blob = client.bucket(self._l2_bucket_name()).blob(L2_BLOB_NAME)
            if not blob.exists():
                return None
            payload = json.loads(blob.download_as_text())
            entries = payload.get("entries")
            return entries if isinstance(entries, dict) else None
        except Exception as e:
            logger.debug(
                "Earnings L2 cache unavailable (treated as a miss)",
                event_category="system",
                event_type="earnings_cache_l2_unavailable",
                operation="read",
                error=str(e),
            )
            return None

    def _store_to_l2(self) -> None:
        """Write L1 through to the durable blob. Never raises."""
        try:
            from google.cloud import storage
            client = storage.Client()
            blob = client.bucket(self._l2_bucket_name()).blob(L2_BLOB_NAME)
            blob.upload_from_string(
                json.dumps({
                    "written_at": datetime.now().isoformat(),
                    "entries": {
                        symbol: _encode_entry(entry)
                        for symbol, entry in _EARNINGS_CACHE.items()
                    },
                }),
                content_type="application/json",
            )
        except Exception as e:
            logger.debug(
                "Earnings L2 cache write failed (entry still cached in L1)",
                event_category="system",
                event_type="earnings_cache_l2_unavailable",
                operation="write",
                error=str(e),
            )

    def _l2_bucket_name(self) -> str:
        """The opportunity bucket — already strategy-scoped (FC-075 Seam 1)."""
        bucket = getattr(self.config, "opportunity_bucket", None)
        if isinstance(bucket, str) and bucket:
            return bucket
        return os.getenv("GCS_BUCKET_NAME", "options-wheel-opportunities")


def _encode_entry(entry: Dict) -> Dict:
    """Serialize a cache entry for the blob (dates as ISO strings)."""
    earnings_date = entry.get("date")
    fetched_at = entry.get("fetched_at")
    return {
        "date": earnings_date.isoformat() if isinstance(earnings_date, date) else None,
        "hour": entry.get("hour"),
        "fetched_at": (
            fetched_at.isoformat() if isinstance(fetched_at, datetime) else None
        ),
    }


def _decode_entry(raw) -> Optional[Dict]:
    """Parse one blob entry back into cache shape, or None if unusable."""
    if not isinstance(raw, dict):
        return None
    try:
        fetched_at_raw = raw.get("fetched_at")
        if not fetched_at_raw:
            return None
        fetched_at = datetime.fromisoformat(fetched_at_raw)
        date_raw = raw.get("date")
        earnings_date = date.fromisoformat(date_raw) if date_raw else None
    except (TypeError, ValueError):
        return None
    return {"date": earnings_date, "hour": raw.get("hour"), "fetched_at": fetched_at}
