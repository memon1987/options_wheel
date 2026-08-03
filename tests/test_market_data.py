"""`find_suitable_calls` — the FC-013 earnings SPAN criterion.

Plan: docs/plans/fc-013.md DD-3 / §3.

The predicate under test is `expiration_date >= next_earnings_date`, applied
per candidate, last in the criteria chain. Three properties matter and each has
a test that fails if it is lost:

1. A candidate that expires INTO the event is rejected and counted.
2. A candidate that expires BEFORE the event is allowed — at any DTE. This is
   what makes span DTE-invariant, and it is the property a hardcoded N or a
   derive-N-from-DTE implementation destroys.
3. `>=` is inclusive: expiry-day-equals-event-day still carries the gap.
"""

from datetime import date, timedelta
from unittest.mock import Mock

import pytest

from src.api.market_data import MarketDataManager
from src.utils.config import Config


TODAY = date(2026, 8, 3)
EARNINGS = TODAY + timedelta(days=5)  # D+5


def _call(option_symbol, expiry, strike=200.0, delta=0.17, mid=1.50, dte=7):
    return {
        'symbol': option_symbol,
        'underlying_symbol': 'NVDA',
        'option_type': 'call',
        'strike_price': strike,
        'expiration_date': expiry.isoformat(),
        'dte': dte,
        'delta': delta,
        'mid_price': mid,
        'bid': mid - 0.05,
        'ask': mid + 0.05,
        'last_price': mid,
        'volume': 500,
        'open_interest': 2000,
        'implied_volatility': 0.42,
    }


class _SpanFixture:
    def setup_method(self):
        self.config = Mock(spec=Config)
        self.config.call_target_dte = 45
        self.config.call_delta_range = [0.10, 0.25]
        self.config.min_call_premium = 0.30
        self.market_data = MarketDataManager(Mock(), self.config)

    def _chain(self, calls):
        self.market_data.get_option_chain_with_analysis = Mock(
            return_value={'puts': [], 'calls': calls})

    def _stats(self, symbol='NVDA'):
        return self.market_data.last_call_rejection_stats[symbol]


class TestCallSpanFilter(_SpanFixture):
    """Tests 3, 4, 5, 8 of the plan's named list (chain-level half)."""

    def test_call_candidate_spanning_earnings_is_rejected(self):
        """Test 3. D+7 expiry against a D+5 event: rejected and counted.

        MUTATION CHECK: reverting span to a days-until window (e.g. block only
        when `days_until <= 2`) lets the D+7 candidate through, because
        days_until here is 5. This test then FAILS.
        """
        spanning = _call('NVDA260810C00200000', TODAY + timedelta(days=7))
        early = _call('NVDA260806C00200000', TODAY + timedelta(days=3), strike=205.0)
        self._chain([spanning, early])

        results = self.market_data.find_suitable_calls(
            'NVDA', min_strike_price=100.0, exclude_expiry_on_or_after=EARNINGS)

        assert [c['symbol'] for c in results] == ['NVDA260806C00200000']
        assert self._stats()['expires_into_earnings'] == 1

    def test_call_candidate_expiring_before_earnings_is_allowed(self):
        """Test 4 — the DTE-extension pin.

        MUTATION CHECK, two of them, and BOTH must be caught:
          (a) a hardcoded N=7 window blocks the symbol entirely at
              days_until = 5, so this candidate disappears;
          (b) deriving N from DTE (N = 7 here) does the same.
        Either mutation makes this test FAIL. That is the operator's explicit
        rejection of both, made executable: a candidate that expires before the
        event must stay legal at any DTE.
        """
        early = _call('NVDA260806C00200000', TODAY + timedelta(days=3))
        self._chain([early])

        results = self.market_data.find_suitable_calls(
            'NVDA', min_strike_price=100.0, exclude_expiry_on_or_after=EARNINGS)

        assert [c['symbol'] for c in results] == ['NVDA260806C00200000']
        assert self._stats()['expires_into_earnings'] == 0

    def test_a_long_dated_candidate_expiring_before_earnings_is_still_allowed(self):
        """The same pin at the far end of the DTE range, where derive-N hurts most.

        Earnings 40 days out, a 30-DTE call expiring before it. Under N=DTE
        this would be blocked (days_until 40 > 30 — allowed, actually) — but
        under any *fixed* window scaled to DTE the trade becomes progressively
        harder to justify. Span answers the only question that matters: does
        the contract's life cover the report? Here it does not.
        """
        far_earnings = TODAY + timedelta(days=40)
        candidate = _call('NVDA260902C00200000', TODAY + timedelta(days=30), dte=30)
        self._chain([candidate])

        results = self.market_data.find_suitable_calls(
            'NVDA', min_strike_price=100.0, exclude_expiry_on_or_after=far_earnings)

        assert len(results) == 1

    def test_span_boundary_expiry_on_earnings_day_is_blocked(self):
        """Test 5. `>=` not `>`: assignment resolves after the report."""
        on_the_day = _call('NVDA260808C00200000', EARNINGS)
        day_before = _call('NVDA260807C00200000', EARNINGS - timedelta(days=1),
                           strike=205.0)
        self._chain([on_the_day, day_before])

        results = self.market_data.find_suitable_calls(
            'NVDA', min_strike_price=100.0, exclude_expiry_on_or_after=EARNINGS)

        assert [c['symbol'] for c in results] == ['NVDA260807C00200000']
        assert self._stats()['expires_into_earnings'] == 1

    def test_clear_symbol_candidates_unconstrained(self):
        """Test 8. `None` is byte-identical to pre-FC-013 behaviour."""
        calls = [
            _call('NVDA260810C00200000', TODAY + timedelta(days=7)),
            _call('NVDA260806C00200000', TODAY + timedelta(days=3), strike=205.0),
        ]
        self._chain(calls)
        with_gate = self.market_data.find_suitable_calls(
            'NVDA', min_strike_price=100.0, exclude_expiry_on_or_after=None)
        gated_stats = dict(self._stats())

        self._chain(calls)
        without_param = self.market_data.find_suitable_calls(
            'NVDA', min_strike_price=100.0)

        assert [c['symbol'] for c in with_gate] == [c['symbol'] for c in without_param]
        assert len(with_gate) == 2
        assert gated_stats['expires_into_earnings'] == 0
        assert gated_stats == self._stats()

    def test_every_candidate_spanning_empties_the_result(self):
        """The shape OptionsScanner reads to write a `blocked{earnings_blackout}` row."""
        self._chain([
            _call('NVDA260810C00200000', TODAY + timedelta(days=7)),
            _call('NVDA260814C00205000', TODAY + timedelta(days=11), strike=205.0),
        ])

        results = self.market_data.find_suitable_calls(
            'NVDA', min_strike_price=100.0, exclude_expiry_on_or_after=EARNINGS)

        assert results == []
        assert self._stats()['expires_into_earnings'] == 2


class TestSpanCounterAttribution(_SpanFixture):
    """The counter must mean "a QUALIFYING strike was taken by the event"."""

    def test_a_candidate_that_would_have_failed_delta_is_not_counted_as_span(self):
        """Otherwise a symbol with no tradeable strikes at all reads as
        span-emptied, and the scanner writes `blocked{earnings_blackout}` for a
        symbol earnings had nothing to do with."""
        self._chain([
            _call('NVDA260810C00200000', TODAY + timedelta(days=7), delta=0.85),
        ])

        results = self.market_data.find_suitable_calls(
            'NVDA', min_strike_price=100.0, exclude_expiry_on_or_after=EARNINGS)

        assert results == []
        assert self._stats()['expires_into_earnings'] == 0
        assert self._stats()['delta_out_of_range'] == 1

    def test_a_candidate_below_the_cost_basis_floor_is_not_counted_as_span(self):
        self._chain([
            _call('NVDA260810C00200000', TODAY + timedelta(days=7), strike=90.0),
        ])

        self.market_data.find_suitable_calls(
            'NVDA', min_strike_price=100.0, exclude_expiry_on_or_after=EARNINGS)

        assert self._stats()['expires_into_earnings'] == 0
        assert self._stats()['below_cost_basis'] == 1

    def test_span_rejections_are_included_in_total_rejected(self):
        self._chain([
            _call('NVDA260810C00200000', TODAY + timedelta(days=7)),
        ])

        self.market_data.find_suitable_calls(
            'NVDA', min_strike_price=100.0, exclude_expiry_on_or_after=EARNINGS)

        assert self._stats()['total_rejected'] == 1


class TestExpiryCoercion(_SpanFixture):
    """The chain carries expiries as ISO strings live and in replay, but the
    parser tolerates datetimes and fixtures pass dates. One coercion, so the
    comparison can never silently compare a str to a date."""

    @pytest.mark.parametrize("expiry_value", [
        "2026-08-10",
        "2026-08-10T00:00:00",
        date(2026, 8, 10),
    ])
    def test_every_expiry_shape_is_compared_correctly(self, expiry_value):
        candidate = _call('NVDA260810C00200000', TODAY + timedelta(days=7))
        candidate['expiration_date'] = expiry_value
        self._chain([candidate])

        results = self.market_data.find_suitable_calls(
            'NVDA', min_strike_price=100.0, exclude_expiry_on_or_after=EARNINGS)

        assert results == []
        assert self._stats()['expires_into_earnings'] == 1

    def test_an_unparseable_expiry_is_rejected_not_waved_through(self):
        """A risk control must not have one path where "could not tell" means
        "sell it". Structurally unreachable today, which is exactly why."""
        candidate = _call('NVDA260810C00200000', TODAY + timedelta(days=7))
        candidate['expiration_date'] = 'not-a-date'
        self._chain([candidate])

        results = self.market_data.find_suitable_calls(
            'NVDA', min_strike_price=100.0, exclude_expiry_on_or_after=EARNINGS)

        assert results == []
        assert self._stats()['expires_into_earnings'] == 1

    def test_an_unparseable_expiry_is_untouched_when_the_gate_is_off(self):
        """No span floor, no span opinion — the default path stays inert."""
        candidate = _call('NVDA260810C00200000', TODAY + timedelta(days=7))
        candidate['expiration_date'] = 'not-a-date'
        self._chain([candidate])

        results = self.market_data.find_suitable_calls('NVDA', min_strike_price=100.0)

        assert len(results) == 1
