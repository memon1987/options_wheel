"""EarningsCalendarService — the tri-state surface, the constructor, the cache.

Plan: docs/plans/fc-013.md §1 (and the FC-007 test debt this finally pays).

The load-bearing case in this file is **clear vs unknown**. Rev 1 of FC-013
tried to make the existing boolean surface fail closed by flipping its error
paths to ``True``; that method's ``None`` branch conflates "Finnhub failed"
with "no earnings in the next 90 days", so the flip would have blocked every
known-clear symbol — an account-wide brick on a normal day. Every test below
that distinguishes the two is guarding that.
"""

from datetime import date, datetime, time, timedelta
from unittest.mock import Mock

import pytest

from src.api import earnings_calendar as ec_module
from src.api.earnings_calendar import (
    EARNINGS_CLEAR,
    EARNINGS_KNOWN,
    EARNINGS_UNKNOWN,
    EarningsCalendarService,
    clear_earnings_cache,
)
from src.utils import clock

# Captured at import, BEFORE the `_no_finnhub` fixture no-ops it, so the real
# GCS read can be exercised where that is the point.
_REAL_L2_READ = EarningsCalendarService.__dict__["_l2_read"]


def _config(**overrides):
    """A config stub with the earnings block populated."""
    cfg = Mock()
    cfg.finnhub_api_key = "test_finnhub_key"
    cfg.earnings_enabled = True
    cfg.earnings_cache_ttl_hours = 24
    cfg.earnings_lookahead_days = 90
    cfg.earnings_blackout_days = 2
    cfg.opportunity_bucket = "test-bucket"
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _entry(earnings_date, fetched_at=None, hour="amc"):
    return {
        "date": earnings_date,
        "hour": hour,
        "fetched_at": fetched_at or datetime.now(),
    }


class _FakeFinnhub:
    """Stands in for the finnhub client object; counts calls, never networks."""

    def __init__(self, payload=None, raises=None):
        self.payload = payload if payload is not None else {"earningsCalendar": []}
        self.raises = raises
        self.calls = 0

    def earnings_calendar(self, **kwargs):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.payload


# =========================================================================== #
# Test 12 — the tri-state contract
# =========================================================================== #

class TestNextEarningsInfoTristate:
    """Known / clear / unknown, and `earnings_within` derived from them."""

    def test_a_date_inside_the_lookahead_is_known(self, monkeypatch):
        svc = EarningsCalendarService(_config())
        monkeypatch.setattr(
            EarningsCalendarService, "_fetch_earnings",
            lambda self, symbol: _entry(date(2026, 8, 26)))

        assert svc.next_earnings_info("NVDA") == (EARNINGS_KNOWN, date(2026, 8, 26))

    def test_an_empty_calendar_fetch_is_CLEAR_not_unknown(self, monkeypatch):
        """The load-bearing distinction: a successful fetch that found nothing.

        This is the state rev 1's fail-closed flip would have turned into a
        block for every ETF and every symbol in a quiet window — i.e. almost
        the whole book on almost every day.
        """
        svc = EarningsCalendarService(_config())
        monkeypatch.setattr(
            EarningsCalendarService, "_fetch_earnings",
            lambda self, symbol: _entry(None, hour=None))

        assert svc.next_earnings_info("SPY") == (EARNINGS_CLEAR, None)
        assert svc.earnings_within("SPY", 2) is False

    def test_a_failed_fetch_is_UNKNOWN(self, monkeypatch):
        svc = EarningsCalendarService(_config())
        monkeypatch.setattr(
            EarningsCalendarService, "_fetch_earnings",
            lambda self, symbol: None)

        assert svc.next_earnings_info("AAPL") == (EARNINGS_UNKNOWN, None)
        assert svc.earnings_within("AAPL", 2) is None

    @pytest.mark.real_finnhub_fetch
    def test_the_failure_cache_window_also_reads_UNKNOWN(self):
        """A second lookup inside the 1h failure window must not fail open.

        `_fetch_earnings` short-circuits to None without calling Finnhub again;
        the tri-state must map that to unknown, not to clear.
        """
        svc = EarningsCalendarService(_config())
        svc._client = _FakeFinnhub(raises=RuntimeError("finnhub 503"))

        assert svc.next_earnings_info("AAPL") == (EARNINGS_UNKNOWN, None)
        assert svc._client.calls == 1
        # Second call is served by the failure cache, never reaching the API.
        assert svc.next_earnings_info("AAPL") == (EARNINGS_UNKNOWN, None)
        assert svc._client.calls == 1

    def test_no_client_is_UNKNOWN(self):
        svc = EarningsCalendarService(_config(finnhub_api_key=""))

        assert svc._client is None
        assert svc.next_earnings_info("AAPL") == (EARNINGS_UNKNOWN, None)
        assert svc.earnings_within("AAPL", 2) is None

    @pytest.mark.parametrize("days_out,expected", [(0, True), (2, True), (3, False)])
    def test_earnings_within_is_inclusive_at_both_ends(
            self, monkeypatch, days_out, expected):
        """0/N/N+1 -> True/True/False. The put leg's whole predicate."""
        today = date(2026, 8, 3)
        svc = EarningsCalendarService(_config())
        monkeypatch.setattr(
            EarningsCalendarService, "_fetch_earnings",
            lambda self, symbol: _entry(today + timedelta(days=days_out)))

        with clock.frozen(datetime.combine(today, time(12, 0))):
            assert svc.earnings_within("AMZN", 2) is expected


# =========================================================================== #
# Test 12b — the cache stores the DATE, not a verdict
# =========================================================================== #

class TestCachedDatesAnswerCorrectlyAcrossDays:
    def test_one_cached_entry_answers_differently_on_two_days(self, monkeypatch):
        """Caching a computed `days_until` (or a verdict) would freeze the answer.

        Entry fetched on D with earnings at D+3, put window 2: on D the symbol
        is clear, on D+1 the SAME cached entry must block. And the span test
        against a candidate expiring D+4 must block on both days.
        """
        day_d = date(2026, 8, 3)
        earnings = date(2026, 8, 6)          # D+3
        candidate_expiry = date(2026, 8, 7)  # D+4, spans the event

        fetches = []

        def _fetch(self, symbol):
            fetches.append(symbol)
            entry = _entry(earnings)
            ec_module._EARNINGS_CACHE[symbol] = entry
            return entry

        monkeypatch.setattr(EarningsCalendarService, "_fetch_earnings", _fetch)
        svc = EarningsCalendarService(_config())

        with clock.frozen(datetime.combine(day_d, time(12, 0))):
            assert svc.earnings_within("AMZN", 2) is False
            status, earnings_date = svc.next_earnings_info("AMZN")
            assert (status, candidate_expiry >= earnings_date) == (EARNINGS_KNOWN, True)

        with clock.frozen(datetime.combine(day_d + timedelta(days=1), time(12, 0))):
            assert svc.earnings_within("AMZN", 2) is True
            status, earnings_date = svc.next_earnings_info("AMZN")
            assert (status, candidate_expiry >= earnings_date) == (EARNINGS_KNOWN, True)

        # One fetch total — the second day answered from cache.
        assert fetches == ["AMZN"]


# =========================================================================== #
# Test 13 / 13b — the two-layer cache
# =========================================================================== #

class TestTheCacheIsSharedAndDurable:
    @pytest.mark.real_finnhub_fetch
    def test_l1_is_shared_across_instances(self):
        """`/scan` builds a fresh scanner (and service) per request.

        With an instance-scoped cache, `earnings.cache_ttl_hours` governed
        nothing at all: every request refetched. Module scope is what makes the
        knob real.
        """
        client = _FakeFinnhub({"earningsCalendar": [{"date": "2026-08-26", "hour": "amc"}]})

        first = EarningsCalendarService(_config())
        first._client = client
        assert first.next_earnings_info("NVDA") == (EARNINGS_KNOWN, date(2026, 8, 26))
        assert client.calls == 1

        second = EarningsCalendarService(_config())
        second._client = client
        assert second.next_earnings_info("NVDA") == (EARNINGS_KNOWN, date(2026, 8, 26))
        assert client.calls == 1, "second instance should have answered from L1"

    @pytest.mark.real_finnhub_fetch
    def test_an_expired_entry_refetches(self):
        client = _FakeFinnhub({"earningsCalendar": [{"date": "2026-08-26", "hour": "amc"}]})
        svc = EarningsCalendarService(_config(earnings_cache_ttl_hours=1))
        svc._client = client

        ec_module._EARNINGS_CACHE["NVDA"] = _entry(
            date(2026, 5, 1), fetched_at=datetime.now() - timedelta(hours=5))

        assert svc.next_earnings_info("NVDA") == (EARNINGS_KNOWN, date(2026, 8, 26))
        assert client.calls == 1

    def test_l2_blob_survives_a_cold_start(self, monkeypatch):
        """min-instances=0 means L1 is cold nearly every scan.

        A fresh process with a populated blob must answer with ZERO Finnhub
        calls; otherwise the gate costs ~84 fetches/day and every scan pays
        2-6s of sequential lookups.
        """
        clear_earnings_cache()  # simulate instance death

        def _never(self, symbol):
            raise AssertionError("Finnhub must not be consulted on an L2 hit")

        monkeypatch.setattr(EarningsCalendarService, "_fetch_earnings", _never)
        monkeypatch.setattr(
            EarningsCalendarService, "_l2_read",
            lambda self: {"NVDA": {"date": "2026-08-26", "hour": "amc",
                                   "fetched_at": datetime.now().isoformat()}})

        svc = EarningsCalendarService(_config())
        assert svc.next_earnings_info("NVDA") == (EARNINGS_KNOWN, date(2026, 8, 26))

    def test_a_broken_gcs_client_is_a_cache_miss_not_an_error(self, monkeypatch):
        """The REAL `_l2_read`, against a storage client that raises.

        Exercised with the genuine implementation (the conftest no-op is
        swapped back out), because the swallow is the whole contract: GCS
        trouble must degrade to a miss, never propagate.
        """
        monkeypatch.setattr(EarningsCalendarService, "_l2_read", _REAL_L2_READ)

        class _BrokenStorage:
            def Client(self, *a, **kw):
                raise RuntimeError("GCS 403: no credentials")

        monkeypatch.setitem(
            __import__("sys").modules, "google.cloud.storage", _BrokenStorage())

        svc = EarningsCalendarService(_config())
        assert svc._l2_read() is None

    def test_an_l2_miss_falls_through_to_finnhub_and_never_blocks(self, monkeypatch):
        """The blob can never block a trade by itself — only Finnhub's answer,
        or its absence, decides gate state."""
        clear_earnings_cache()
        monkeypatch.setattr(EarningsCalendarService, "_l2_read", lambda self: None)
        monkeypatch.setattr(
            EarningsCalendarService, "_fetch_earnings",
            lambda self, symbol: _entry(date(2026, 8, 26)))

        svc = EarningsCalendarService(_config())
        assert svc.next_earnings_info("NVDA") == (EARNINGS_KNOWN, date(2026, 8, 26))

    def test_l2_is_read_once_per_process_not_once_per_symbol(self, monkeypatch):
        clear_earnings_cache()
        reads = []

        monkeypatch.setattr(
            EarningsCalendarService, "_l2_read",
            lambda self: reads.append(1) or {})
        monkeypatch.setattr(
            EarningsCalendarService, "_fetch_earnings",
            lambda self, symbol: _entry(None))

        svc = EarningsCalendarService(_config())
        for symbol in ("AAPL", "AMZN", "GOOGL", "NVDA"):
            svc.next_earnings_info(symbol)

        assert len(reads) == 1

    def test_a_stale_l2_entry_is_not_hydrated(self, monkeypatch):
        clear_earnings_cache()
        monkeypatch.setattr(
            EarningsCalendarService, "_l2_read",
            lambda self: {"NVDA": {
                "date": "2026-05-01", "hour": "amc",
                "fetched_at": (datetime.now() - timedelta(hours=48)).isoformat()}})
        monkeypatch.setattr(
            EarningsCalendarService, "_fetch_earnings",
            lambda self, symbol: _entry(date(2026, 8, 26)))

        svc = EarningsCalendarService(_config())
        assert svc.next_earnings_info("NVDA") == (EARNINGS_KNOWN, date(2026, 8, 26))

    def test_eviction_uses_pop_so_a_racing_reader_cannot_keyerror(self, monkeypatch):
        """Cheap hardening; the real safety is /scan's strategy_lock."""
        monkeypatch.setattr(
            EarningsCalendarService, "_fetch_earnings",
            lambda self, symbol: None)
        svc = EarningsCalendarService(_config(earnings_cache_ttl_hours=1))
        ec_module._EARNINGS_CACHE["NVDA"] = _entry(
            date(2026, 5, 1), fetched_at=datetime.now() - timedelta(hours=5))

        assert svc._get_cached("NVDA") is None
        # Second eviction of the same (already-gone) symbol must be a no-op.
        assert svc._get_cached("NVDA") is None


# =========================================================================== #
# Test 10 — enabled but unusable degrades LOUDLY, never crashes
# =========================================================================== #

class TestEnabledWithNoKeyDegradesLoudly:
    def test_construction_succeeds_and_every_attribute_is_set(self):
        """The pre-FC-013 constructor returned before assigning three attributes.

        Every later method call then raised AttributeError, which the scanner's
        broad `except` misfiled as `scan_failure` — zero opportunities AND zero
        gate telemetry, indistinguishable from a broken scanner.
        """
        svc = EarningsCalendarService(_config(finnhub_api_key=""))

        assert svc._client is None
        assert svc._cache_ttl_hours == 24
        assert svc._lookahead_days == 90
        assert svc._enabled is True

    def test_every_public_method_answers_rather_than_raising(self):
        svc = EarningsCalendarService(_config(finnhub_api_key=""))

        assert svc.next_earnings_info("AAPL") == (EARNINGS_UNKNOWN, None)
        assert svc.earnings_within("AAPL", 2) is None
        assert svc.is_earnings_within_n_days("AAPL", 2) is False
        assert svc.get_next_earnings_date("AAPL") is None
        assert svc.get_earnings_proximity("AAPL") == {
            "next_earnings_date": None, "days_until": None, "earnings_hour": None}

    def test_it_logs_the_alerted_error_event(self, monkeypatch):
        """`earnings_gate_unusable` is one of the three strings the DD-6 policy
        matches. If this event stops being emitted the alert goes silent while
        the book stops trading — the worst combination available."""
        events = []
        monkeypatch.setattr(
            "src.utils.logging_events.log_error_event",
            lambda logger, **kw: events.append(kw))

        EarningsCalendarService(_config(finnhub_api_key=""))

        assert [e["error_type"] for e in events] == ["earnings_gate_unusable"]
        assert events[0]["recoverable"] is True

    def test_disabled_and_unusable_is_a_warning_not_an_alerted_error(self, monkeypatch):
        """Disabled and broken are different states with different behaviour.

        With the gate off, an absent key blocks nothing, so paging the operator
        would be noise.
        """
        events = []
        monkeypatch.setattr(
            "src.utils.logging_events.log_error_event",
            lambda logger, **kw: events.append(kw))

        EarningsCalendarService(_config(finnhub_api_key="", earnings_enabled=False))

        assert events == []

    def test_an_unimportable_client_degrades_the_same_way(self, monkeypatch):
        monkeypatch.setattr(
            EarningsCalendarService, "_build_client",
            staticmethod(lambda api_key: (_ for _ in ()).throw(
                ImportError("no finnhub"))))

        svc = EarningsCalendarService(_config())

        assert svc._client is None
        assert svc.next_earnings_info("AAPL") == (EARNINGS_UNKNOWN, None)


# =========================================================================== #
# The roller's contract is untouched (operator decision, FC-069 item 4)
# =========================================================================== #

class TestRollerFacingMethodsStillFailOpen:
    def test_is_earnings_within_n_days_still_fails_open_on_a_failed_fetch(
            self, monkeypatch):
        monkeypatch.setattr(
            EarningsCalendarService, "_fetch_earnings",
            lambda self, symbol: None)
        svc = EarningsCalendarService(_config())

        # FC-013's surface says "unknown"; the roller's says "allow". Both, on
        # the same object, deliberately.
        assert svc.next_earnings_info("AAPL") == (EARNINGS_UNKNOWN, None)
        assert svc.is_earnings_within_n_days("AAPL", 2) is False

    def test_get_earnings_proximity_keys_are_unchanged(self, monkeypatch):
        monkeypatch.setattr(
            EarningsCalendarService, "_fetch_earnings",
            lambda self, symbol: _entry(date.today() + timedelta(days=3)))
        svc = EarningsCalendarService(_config())

        proximity = svc.get_earnings_proximity("AAPL")
        assert set(proximity) == {"next_earnings_date", "days_until", "earnings_hour"}
        assert proximity["days_until"] == 3


# =========================================================================== #
# Test 19 — hermeticity
# =========================================================================== #

class TestHermeticity:
    def test_the_env_key_is_pinned_to_a_fake_value(self):
        """A real key in the developer's .env must be invisible to every test.

        `Config.finnhub_api_key` reads os.getenv directly and `Config.__init__`
        calls load_dotenv(), so without the unconditional pin the suite behaves
        differently on a developer machine than in CI — the ambient-environment
        defect this suite has been bitten by three separate times.
        """
        import os
        assert os.getenv("FINNHUB_API_KEY") == "test_finnhub_key"

    def test_a_default_constructed_service_answers_clear_with_no_network(self):
        """No marker, no mocking: the chokepoint alone must make this safe."""
        svc = EarningsCalendarService(_config())
        assert svc.next_earnings_info("ANYTHING") == (EARNINGS_CLEAR, None)

    def test_the_module_cache_does_not_leak_between_tests(self):
        """Paired with the test below; either order, both must pass."""
        assert ec_module._EARNINGS_CACHE == {}
        ec_module._EARNINGS_CACHE["LEAK"] = _entry(date(2026, 8, 26))

    def test_the_module_cache_does_not_leak_between_tests_2(self):
        assert ec_module._EARNINGS_CACHE == {}

    def test_the_l2_helpers_are_no_ops(self):
        svc = EarningsCalendarService(_config())
        assert svc._l2_read() is None
        assert svc._store_to_l2() is None


# =========================================================================== #
# `_fetch_earnings` itself (marker-gated: the real method, a mocked client)
# =========================================================================== #

class TestFetchEarnings:
    @pytest.mark.real_finnhub_fetch
    def test_it_picks_the_earliest_date_in_the_window(self):
        svc = EarningsCalendarService(_config())
        svc._client = _FakeFinnhub({"earningsCalendar": [
            {"date": "2026-11-20", "hour": "amc"},
            {"date": "2026-08-26", "hour": "bmo"},
        ]})

        assert svc.next_earnings_info("NVDA") == (EARNINGS_KNOWN, date(2026, 8, 26))

    @pytest.mark.real_finnhub_fetch
    def test_an_empty_200_is_cached_as_clear(self):
        """Correct for ETFs and quiet windows; an accepted fail-open if Finnhub's
        coverage ever regresses for a symbol. The audit script is the
        retrospective detector (independent yfinance table)."""
        svc = EarningsCalendarService(_config())
        svc._client = _FakeFinnhub({"earningsCalendar": []})

        assert svc.next_earnings_info("SPY") == (EARNINGS_CLEAR, None)
        assert svc.next_earnings_info("SPY") == (EARNINGS_CLEAR, None)
        assert svc._client.calls == 1, "the clear answer must be cached"

    @pytest.mark.real_finnhub_fetch
    def test_a_raising_client_logs_earnings_fetch_failed_and_returns_none(
            self, monkeypatch):
        events = []
        monkeypatch.setattr(
            "src.utils.logging_events.log_error_event",
            lambda logger, **kw: events.append(kw))
        svc = EarningsCalendarService(_config())
        svc._client = _FakeFinnhub(raises=RuntimeError("boom"))

        assert svc._fetch_earnings("AAPL") is None
        assert [e["error_type"] for e in events] == ["earnings_fetch_failed"]
