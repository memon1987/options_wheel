"""Unit tests for the FC-032 backtest data layer (network-free).

Covers Black-Scholes greeks, point-in-time chain construction (no lookahead),
the spread model, the parquet chain store, and the coverage report, all against
an in-memory mock provider.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
from typing import Dict, List

import pytest

from src.backtesting.data import greeks
from src.backtesting.data.chain_builder import (
    ChainBuilder,
    STRIKE_WINDOW_PCT,
    strike_window,
)
from src.backtesting.data.chain_store import ChainStore
from src.backtesting.data.provider import OptionBar, OptionContract, StockBar
from src.backtesting.data.quality import evaluate_coverage
from src.backtesting.data.spread_model import SpreadModel


# --------------------------------------------------------------------------- #
# Greeks
# --------------------------------------------------------------------------- #
class TestGreeks:
    def test_atm_call_matches_textbook(self):
        # S=K=100, T=1, r=0, sigma=0.2, q=0 -> 7.9656 (standard reference value)
        assert greeks.bs_price(100, 100, 1, 0.0, 0.2, 0.0, "call") == pytest.approx(
            7.9656, abs=1e-3
        )

    def test_put_call_parity_at_zero_rates(self):
        c = greeks.bs_price(100, 100, 1, 0.0, 0.2, 0.0, "call")
        p = greeks.bs_price(100, 100, 1, 0.0, 0.2, 0.0, "put")
        assert c == pytest.approx(p, abs=1e-9)

    def test_delta_signs_and_sum(self):
        dc = greeks.bs_delta(100, 100, 1, 0.0, 0.2, 0.0, "call")
        dp = greeks.bs_delta(100, 100, 1, 0.0, 0.2, 0.0, "put")
        assert 0 < dc < 1
        assert -1 < dp < 0
        assert dc - dp == pytest.approx(1.0, abs=1e-9)  # call - put delta = e^{-qT} = 1

    def test_iv_round_trip(self):
        T = greeks.year_fraction(30)
        price = greeks.bs_price(100, 95, T, 0.04, 0.35, 0.01, "put")
        iv = greeks.implied_vol(price, 100, 95, T, 0.04, 0.01, "put")
        assert iv == pytest.approx(0.35, abs=1e-4)

    def test_iv_none_below_intrinsic(self):
        # A put priced below its discounted intrinsic has no real IV.
        T = greeks.year_fraction(7)
        assert greeks.implied_vol(0.001, 100, 130, T, 0.04, 0.0, "put") is None

    def test_expiration_intrinsic_and_delta(self):
        assert greeks.bs_price(105, 100, 0, 0.04, 0.3, 0, "call") == pytest.approx(5.0)
        assert greeks.bs_delta(105, 100, 0, 0.04, 0.3, 0, "call") == 1.0
        assert greeks.bs_delta(95, 100, 0, 0.04, 0.3, 0, "call") == 0.0


# --------------------------------------------------------------------------- #
# Spread model
# --------------------------------------------------------------------------- #
class TestSpreadModel:
    def test_abs_floor_enforced(self):
        m = SpreadModel(base_frac=0.05, abs_floor=0.02)
        # tiny mark -> percentage spread below floor -> floor wins
        assert m.half_spread(0.10, moneyness=0.0) == pytest.approx(
            max(0.02, 0.05 * 0.10 + 0.05 * 0.10)  # includes cheap widening
        )

    def test_otm_widens_spread(self):
        m = SpreadModel()
        atm = m.half_spread(2.0, moneyness=0.0)
        otm = m.half_spread(2.0, moneyness=0.15)
        assert otm > atm

    def test_bid_never_negative(self):
        m = SpreadModel(base_frac=0.5, abs_floor=0.5)
        bid, ask = m.bid_ask(0.10, moneyness=0.2)
        assert bid == 0.0
        assert ask > 0.10

    def test_calibrate_fits_or_defaults(self):
        # Too few samples -> defaults.
        assert SpreadModel.calibrate([]) == SpreadModel()
        # Enough samples on a clean line half_spread/mark = 0.03 + 0.2*moneyness.
        samples = [
            {"mark": 1.0, "moneyness": mny, "half_spread": (0.03 + 0.2 * mny)}
            for mny in [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5]
        ]
        fitted = SpreadModel.calibrate(samples)
        assert fitted.base_frac == pytest.approx(0.03, abs=1e-3)
        assert fitted.otm_widening == pytest.approx(0.2, abs=1e-3)


# --------------------------------------------------------------------------- #
# Mock provider
# --------------------------------------------------------------------------- #
class MockProvider:
    """In-memory provider with explicit control over contracts, bars, and prices.

    Crucially, ``get_option_bars`` returns a bar for a symbol ONLY on the exact
    dates listed in ``bar_dates[symbol]`` — so a contract that "trades only on a
    later date" genuinely has no bar on an earlier ``as_of``, which is how the
    no-lookahead test is enforced.
    """

    def __init__(self):
        self.contracts: List[OptionContract] = []
        self.bar_dates: Dict[str, List[date]] = {}
        self.bar_close: Dict[str, float] = {}
        self.stock: Dict[date, float] = {}
        # Call recorders: the cache tests assert on *calls made*, not on
        # elapsed time, so a cache that silently refetched would still fail.
        self.universe_calls: List[tuple] = []
        self.option_bar_calls: List[tuple] = []

    def add_contract(self, c: OptionContract, close: float, traded_on: List[date]):
        self.contracts.append(c)
        self.bar_close[c.symbol] = close
        self.bar_dates[c.symbol] = traded_on

    def get_contract_universe(
        self, underlying, as_of, max_dte, *, strike_gte=None, strike_lte=None
    ):
        hi = as_of + timedelta(days=max_dte)
        self.universe_calls.append((underlying, as_of, max_dte, strike_gte, strike_lte))
        out = [
            c
            for c in self.contracts
            if c.underlying == underlying and as_of <= c.expiration <= hi
        ]
        if strike_gte is not None:
            out = [c for c in out if strike_gte <= c.strike <= strike_lte]
        return out

    def get_option_bars(self, symbols, start, end):
        self.option_bar_calls.append((tuple(symbols), start, end))
        out: Dict[str, List[OptionBar]] = {}
        for s in symbols:
            days = [d for d in self.bar_dates.get(s, []) if start <= d <= end]
            if not days:
                continue
            close = self.bar_close[s]
            out[s] = [
                OptionBar(s, d, close, close, close, close, volume=100, trade_count=5)
                for d in days
            ]
        return out

    def get_stock_bars(self, symbol, start, end):
        return [
            StockBar(symbol, d, px, px, px, px, volume=1_000_000)
            for d, px in sorted(self.stock.items())
            if start <= d <= end
        ]


def _occ(underlying, exp, opt, strike):
    cp = "P" if opt == "put" else "C"
    return f"{underlying}{exp:%y%m%d}{cp}{int(strike * 1000):08d}"


# --------------------------------------------------------------------------- #
# Chain builder — including the no-lookahead guarantee
# --------------------------------------------------------------------------- #
class TestChainBuilder:
    def _provider_with_chain(self):
        p = MockProvider()
        as_of = date(2025, 1, 6)  # a Monday
        exp = date(2025, 1, 10)  # that Friday, 4 DTE
        p.stock = {as_of: 100.0}
        # A ladder of puts around spot, all traded on as_of.
        for strike in [85, 90, 95, 98, 100]:
            sym = _occ("XYZ", exp, "put", strike)
            p.add_contract(
                OptionContract(sym, "XYZ", exp, float(strike), "put"),
                close=max(0.05, (100 - strike) * 0.02 + 0.30),
                traded_on=[as_of],
            )
        return p, as_of, exp

    def test_builds_priced_chain_with_greeks(self):
        p, as_of, exp = self._provider_with_chain()
        b = ChainBuilder(p, risk_free_rate=0.04)
        snap = b.build("XYZ", as_of, max_dte=7)
        assert snap is not None
        assert snap.underlying_price == 100.0
        assert len(snap.puts) == 5
        for q in snap.puts:
            assert q.dte == 4
            assert q.bid <= q.mark <= q.ask
            assert q.modeled_spread and q.modeled_greeks
            if q.implied_volatility is not None:
                assert -1.0 <= q.delta <= 0.0

    def test_no_lookahead_contract_listed_later_excluded(self):
        """A contract that only trades AFTER as_of must not appear in the chain."""
        p, as_of, exp = self._provider_with_chain()
        future = as_of + timedelta(days=1)
        later_exp = date(2025, 1, 17)
        sym = _occ("XYZ", later_exp, "put", 92)
        # Listed with a bar only on a future date, not on as_of.
        p.add_contract(
            OptionContract(sym, "XYZ", later_exp, 92.0, "put"),
            close=1.20,
            traded_on=[future],
        )
        b = ChainBuilder(p)
        snap = b.build("XYZ", as_of, max_dte=14)
        symbols = {q.symbol for q in snap.puts}
        assert sym not in symbols  # no bar on as_of -> excluded

    def test_universe_includes_the_extra_day_live_dte_flooring_reaches(self):
        """Live floors DTE, so an 8-calendar-day contract is a valid DTE-7 candidate.

        market_data does ``dte = (expiration_midnight - now_intraday).days``, which
        floors. Filtering the chain by calendar days would hide those contracts,
        and 21% of real put fills were exactly them.
        """
        p = MockProvider()
        as_of = date(2025, 1, 6)
        p.stock[as_of] = 100.0
        eight_days_out = as_of + timedelta(days=8)
        sym = _occ("XYZ", eight_days_out, "put", 93)
        p.add_contract(
            OptionContract(sym, "XYZ", eight_days_out, 93.0, "put"),
            close=0.80,
            traded_on=[as_of],
        )

        b = ChainBuilder(p, risk_free_rate=0.04)
        snap = b.build("XYZ", as_of, 7)  # strategy window is 7
        assert snap is not None
        assert [q.symbol for q in snap.puts] == [sym], (
            "the 8-calendar-day contract must be in the chain; live can select it"
        )

        # And live's own filter, with its flooring, accepts it as DTE 7.
        from datetime import datetime as _dt
        floored = (_dt.combine(eight_days_out, time.min)
                   - _dt.combine(as_of, time(16, 0))).days
        assert floored == 7

    def test_universe_buffer_is_exactly_one_day(self):
        """A 9-calendar-day contract floors to DTE 8 and live rejects it."""
        from datetime import datetime as _dt

        from src.backtesting.data.chain_builder import UNIVERSE_DTE_BUFFER

        assert UNIVERSE_DTE_BUFFER == 1
        as_of = date(2025, 1, 6)
        nine_days_out = as_of + timedelta(days=9)
        floored = (_dt.combine(nine_days_out, time.min)
                   - _dt.combine(as_of, time(16, 0))).days
        assert floored == 8, "a 9-day contract must floor to 8 and be filtered out by live"

    def test_expired_contract_excluded(self):
        """A contract expiring before as_of is outside the window."""
        p, as_of, exp = self._provider_with_chain()
        past_exp = as_of - timedelta(days=3)
        sym = _occ("XYZ", past_exp, "put", 95)
        p.add_contract(
            OptionContract(sym, "XYZ", past_exp, 95.0, "put"),
            close=0.50,
            traded_on=[as_of],  # even with an as_of bar, it's expired
        )
        b = ChainBuilder(p)
        snap = b.build("XYZ", as_of, max_dte=7)
        assert sym not in {q.symbol for q in snap.puts}

    def test_none_when_no_underlying_price(self):
        p, as_of, exp = self._provider_with_chain()
        b = ChainBuilder(p)
        assert b.build("XYZ", date(2025, 1, 7), max_dte=7) is None  # no stock bar


# --------------------------------------------------------------------------- #
# Chain store round-trip
# --------------------------------------------------------------------------- #
class TestChainStore:
    def test_round_trip(self, tmp_path):
        p = MockProvider()
        as_of = date(2025, 1, 6)
        exp = date(2025, 1, 10)
        p.stock = {as_of: 100.0}
        for strike in [90, 95, 100]:
            sym = _occ("XYZ", exp, "put", strike)
            p.add_contract(
                OptionContract(sym, "XYZ", exp, float(strike), "put"),
                close=1.0,
                traded_on=[as_of],
            )
        snap = ChainBuilder(p).build("XYZ", as_of, max_dte=7)
        store = ChainStore(str(tmp_path))
        assert not store.has("XYZ", as_of)
        store.put(snap)
        assert store.has("XYZ", as_of)
        loaded = store.get("XYZ", as_of)
        assert loaded.underlying_price == 100.0
        assert len(loaded.puts) == 3
        assert {q.strike for q in loaded.puts} == {90.0, 95.0, 100.0}

    def test_empty_chain_round_trip(self, tmp_path):
        # An empty chain (price known, no contracts) must survive round-trip and
        # not be confused with a cache miss.
        from src.backtesting.data.chain_builder import ChainSnapshot

        store = ChainStore(str(tmp_path))
        snap = ChainSnapshot("XYZ", date(2025, 1, 6), 100.0, [], [])
        store.put(snap)
        assert store.has("XYZ", date(2025, 1, 6))
        loaded = store.get("XYZ", date(2025, 1, 6))
        assert loaded is not None
        assert loaded.underlying_price == 100.0
        assert loaded.puts == [] and loaded.calls == []


# --------------------------------------------------------------------------- #
# Coverage report
# --------------------------------------------------------------------------- #
class TestCoverage:
    def test_usable_fraction_and_verdict(self):
        p = MockProvider()
        # Ten trading days; put a usable in-band put on each.
        base = date(2025, 1, 6)
        days = [base + timedelta(days=i) for i in range(10)]
        for d in days:
            p.stock[d] = 100.0
        # For each day, add a ~15-delta put expiring ~7 days out with premium>0.50.
        for d in days:
            exp = d + timedelta(days=7)
            # strike chosen to land near 0.15 delta; premium set above floor.
            sym = _occ("XYZ", exp, "put", 93)
            p.add_contract(
                OptionContract(sym, "XYZ", exp, 93.0, "put"),
                close=0.80,
                traded_on=[d],
            )
        b = ChainBuilder(p, risk_free_rate=0.04)
        report = evaluate_coverage(
            p, b, "XYZ", days[0], days[-1], max_dte=7, sample_every_trading_days=1
        )
        assert report.decision_days == 10
        assert report.days_with_underlying == 10
        # Delta of a 7% OTM 7DTE put depends on implied vol from premium; just
        # assert the plumbing produced candidates and a verdict string.
        assert report.usable_fraction >= 0.0
        assert report.verdict() in {"good", "marginal", "poor"}
        assert "usable_fraction" in report.summary()

    def test_does_not_refetch_the_underlying_per_decision_day(self):
        """Coverage already holds the window's closes; the builder must reuse them.

        A per-day underlying refetch is one wasted request per decision day, on a
        200 req/min tier that already bounds the run's wall time.
        """
        p = MockProvider()
        base = date(2025, 1, 6)
        days = [base + timedelta(days=i) for i in range(10)]
        for d in days:
            p.stock[d] = 100.0

        calls = {"n": 0}
        original = p.get_stock_bars

        def counting_get_stock_bars(symbol, start, end):
            calls["n"] += 1
            return original(symbol, start, end)

        p.get_stock_bars = counting_get_stock_bars

        b = ChainBuilder(p, risk_free_rate=0.04)
        evaluate_coverage(p, b, "XYZ", days[0], days[-1], max_dte=7, sample_every_trading_days=1)

        assert calls["n"] == 1, (
            f"expected a single windowed stock-bars fetch, got {calls['n']} "
            "(the builder is refetching the underlying per decision day)"
        )

    def _coverage(self, spot: float, strike: float, premium: float):
        """Coverage over 10 days whose only put is (strike, premium) at 7 DTE.

        The (spot, strike, premium) triples used below were solved against
        greeks.implied_vol/bs_delta so the contract lands inside the 0.10-0.20
        delta band — delta is derived from the premium, so the two cannot be
        chosen independently.
        """
        p = MockProvider()
        base = date(2025, 1, 6)
        days = [base + timedelta(days=i) for i in range(10)]
        for d in days:
            p.stock[d] = spot
            exp = d + timedelta(days=7)
            p.add_contract(
                OptionContract(_occ("XYZ", exp, "put", int(strike)), "XYZ", exp, strike, "put"),
                close=premium,
                traded_on=[d],
            )
        b = ChainBuilder(p, risk_free_rate=0.04)
        return evaluate_coverage(
            p, b, "XYZ", days[0], days[-1], max_dte=7,
            min_put_premium=0.50, sample_every_trading_days=1,
        )

    def test_premium_shortfall_is_not_a_data_problem(self):
        """A priced in-band put that underpays the floor must not read as missing data.

        This is the distinction the vendor decision rests on: ThetaData supplies
        quotes, not premium. If the chain has the contract and it simply pays
        too little, buying data changes nothing.
        """
        # |delta| = 0.144, premium $0.30 -> in band, under the $0.50 floor.
        report = self._coverage(spot=100.0, strike=96.0, premium=0.30)

        # The data was there every single day...
        assert report.days_with_bar == report.decision_days
        assert report.days_with_in_band_put == report.decision_days
        assert report.in_band_fraction == 1.0
        # ...but no day was usable, and the reason is premium, not data.
        assert report.days_with_usable_put == 0
        assert report.premium_shortfall_days == report.decision_days
        assert report.limiting_factor() == "premium"
        # And the richest in-band premium is recorded even though it lost.
        assert report.per_day[0].best_in_band_premium == pytest.approx(0.30)
        assert report.per_day[0].best_put_premium is None

    def test_data_gap_is_reported_as_data_limited(self):
        """No priced put in the band at all => a vendor genuinely could help."""
        p = MockProvider()
        base = date(2025, 1, 6)
        days = [base + timedelta(days=i) for i in range(10)]
        for d in days:
            p.stock[d] = 100.0  # underlying only; no option contracts anywhere
        b = ChainBuilder(p, risk_free_rate=0.04)
        report = evaluate_coverage(
            p, b, "XYZ", days[0], days[-1], max_dte=7, sample_every_trading_days=1
        )
        assert report.decision_days == 10
        assert report.days_with_in_band_put == 0
        assert report.premium_shortfall_days == 0
        assert report.limiting_factor() == "data"

    def test_limiting_factor_none_when_fully_usable(self):
        # |delta| = 0.167, premium $0.80 -> in band, clears the $0.50 floor.
        report = self._coverage(spot=200.0, strike=192.0, premium=0.80)
        assert report.days_with_usable_put == report.decision_days
        assert report.usable_fraction == 1.0
        assert report.verdict() == "good"
        assert report.premium_shortfall_days == 0
        assert report.limiting_factor() == "none"

    def test_zero_decision_days_is_no_data_not_poor(self):
        """A symbol with no bars must not read as 'poor' coverage.

        'poor' is the verdict that argues for paying a data vendor; an empty API
        response or a bad ticker is not evidence about coverage at all.
        """
        p = MockProvider()  # no stock bars at all
        b = ChainBuilder(p, risk_free_rate=0.04)
        report = evaluate_coverage(
            p, b, "NOSUCH", date(2025, 1, 6), date(2025, 1, 16), max_dte=7
        )
        assert report.decision_days == 0
        assert report.usable_fraction == 0.0
        assert report.verdict() == "no-data"
        assert report.summary()["verdict"] == "no-data"


# --------------------------------------------------------------------------- #
# Alpaca provider: real-time entitlement clamp
# --------------------------------------------------------------------------- #
class TestRealtimeClamp:
    """Alpaca 403s any request reaching into the undelayed window.

    Regression guard for the Phase 1 gate failing on all 14 symbols with
    "subscription does not permit querying recent SIP data" (stocks) and
    "OPRA agreement is not signed" (options) whenever --end was today.
    """

    def test_delayed_end_clamps_today_out_of_realtime_window(self):
        from src.backtesting.data.alpaca_provider import (
            REALTIME_DELAY_MINUTES,
            _delayed_end,
        )

        delay = timedelta(minutes=REALTIME_DELAY_MINUTES)
        before = datetime.now()
        got = _delayed_end(date.today())
        after = datetime.now()
        # Bracket the call rather than comparing to a single sampled clock read,
        # which races the microseconds elapsed inside _delayed_end.
        assert before - delay <= got <= after - delay

    def test_delayed_end_leaves_past_windows_untouched(self):
        from src.backtesting.data.alpaca_provider import _delayed_end

        past = date.today() - timedelta(days=30)
        assert _delayed_end(past) == datetime.combine(past, time.max)

    def test_current_session_bar_is_not_settled(self):
        from src.backtesting.data.alpaca_provider import _is_settled

        assert not _is_settled(date.today())
        assert _is_settled(date.today() - timedelta(days=1))

    def test_adjusted_contracts_are_not_standard_occ(self):
        """Real symbols Alpaca's contracts endpoint returned and its bars endpoint rejected."""
        from src.backtesting.data.alpaca_provider import is_standard_occ

        assert is_standard_occ("AAPL240429P00170000")
        assert is_standard_occ("NVDA260601C00152500")
        assert is_standard_occ("F240419P00012000")
        # Adjusted / non-standard deliverable — must never enter a wheel backtest.
        assert not is_standard_occ("1AAPL240429P00170000")
        assert not is_standard_occ("1MSFT240621C00241000")
        assert not is_standard_occ("")
        assert not is_standard_occ("AAPL240429X00170000")  # bad option type

    def test_universe_excludes_adjusted_contracts(self):
        from alpaca.trading.enums import ContractType

        from src.backtesting.data.alpaca_provider import AlpacaDataProvider

        provider = AlpacaDataProvider(api_key="k", secret_key="s", paper=True)

        class _C:
            def __init__(self, symbol):
                self.symbol = symbol
                self.expiration_date = date(2024, 4, 29)
                self.strike_price = 170.0
                self.type = ContractType.PUT

        class _Resp:
            next_page_token = None
            option_contracts = [
                _C("AAPL240429P00170000"),
                _C("1AAPL240429P00170000"),  # adjusted
            ]

        provider._trading.get_option_contracts = lambda req: _Resp()

        universe = provider.get_contract_universe("AAPL", date(2024, 4, 24), 7)
        symbols = [c.symbol for c in universe]
        assert symbols == ["AAPL240429P00170000"]

    def test_option_bars_screens_nonstandard_symbols(self):
        """One bad symbol 400s the whole chunk; the provider must not send it."""
        from src.backtesting.data.alpaca_provider import AlpacaDataProvider

        provider = AlpacaDataProvider(api_key="k", secret_key="s", paper=True)
        seen = {}

        class _Bars:
            data = {}

        def _stub(req):
            seen["symbols"] = list(req.symbol_or_symbols)
            return _Bars()

        provider._option_data.get_option_bars = _stub

        past = date.today() - timedelta(days=30)
        provider.get_option_bars(
            ["AAPL240429P00170000", "1AAPL240429P00170000"], past, past
        )
        assert seen["symbols"] == ["AAPL240429P00170000"]

        # All-nonstandard input must short-circuit without an API call at all.
        seen.clear()
        out = provider.get_option_bars(["1AAPL240429P00170000"], past, past)
        assert out == {} and "symbols" not in seen

    def test_contract_universe_is_memoized_per_process(self):
        """The chain builder and the coverage report ask for the same universe.

        Contract discovery paginates two statuses, so an unmemoized second call
        doubles the request count of every run against a 200 req/min limit.
        """
        from src.backtesting.data.alpaca_provider import AlpacaDataProvider

        provider = AlpacaDataProvider(api_key="k", secret_key="s", paper=True)

        calls = []

        class _StubResp:
            option_contracts = []
            next_page_token = None

        def _stub_get_option_contracts(req):
            calls.append(req)
            return _StubResp()

        provider._trading.get_option_contracts = _stub_get_option_contracts

        as_of = date(2025, 3, 4)
        first = provider.get_contract_universe("XYZ", as_of, 7)
        n_after_first = len(calls)
        second = provider.get_contract_universe("XYZ", as_of, 7)

        assert n_after_first > 0
        assert len(calls) == n_after_first, "second identical call must hit the memo"
        assert first == second

        # A different key still goes to the API.
        provider.get_contract_universe("XYZ", as_of, 14)
        assert len(calls) > n_after_first

        # Callers must not be able to corrupt the memo by mutating the result.
        first.append("junk")
        assert provider.get_contract_universe("XYZ", as_of, 7) == second

    def test_settlement_ignores_a_frozen_simulated_clock(self):
        """Entitlement is a wall-clock question, not a simulated-time one.

        If _is_settled honored the freeze, replaying June 2024 would classify
        every subsequent bar as unsettled and the provider would fetch nothing.
        """
        from src.backtesting.data.alpaca_provider import _delayed_end, _is_settled
        from src.utils import clock

        past = datetime(2024, 6, 3, 16, 0)
        with clock.frozen(past):
            assert clock.now() == past  # the freeze is genuinely in effect
            # A bar well after the frozen instant is still a settled session.
            assert _is_settled(date.today() - timedelta(days=1))
            # And the request cutoff still tracks real time, not 2024.
            assert _delayed_end(date.today()).year == date.today().year


# --------------------------------------------------------------------------- #
# FC-042 A2 — the strike window
# --------------------------------------------------------------------------- #
class TestStrikeWindow:
    def test_symmetric_around_spot_when_no_shares_are_held(self):
        lo, hi = strike_window(200.0)
        assert lo == pytest.approx(150.0)
        assert hi == pytest.approx(250.0)

    def test_cost_basis_below_spot_does_not_shrink_the_window(self):
        """A profitable position must not narrow the ladder."""
        assert strike_window(200.0, cost_basis=120.0) == strike_window(200.0)

    def test_cost_basis_above_spot_extends_the_upper_bound_only(self):
        """The underwater case the window exists to protect."""
        lo, hi = strike_window(100.0, cost_basis=180.0)
        assert lo == pytest.approx(75.0), "lower bound still anchored to spot"
        assert hi == pytest.approx(225.0), "upper bound must clear cost basis"
        assert hi > 180.0, "a call at cost basis has to be inside the window"

    def test_an_underwater_covered_call_stays_reachable(self):
        """The regression this parameter exists for.

        Shares bought at 180 with spot now 100: every *eligible* covered call
        (struck at or above cost basis) sits 80%+ above spot. A spot-centred
        window stops at 125 and the call ladder comes back empty — the replay
        would show the position never rolling, which is a strategy conclusion
        drawn from a data-fetch bug.
        """
        spot, basis = 100.0, 180.0
        _, spot_only_hi = strike_window(spot)
        assert spot_only_hi < basis, "precondition: spot window excludes cost basis"

        lo, hi = strike_window(spot, cost_basis=basis)
        eligible = [s for s in (180.0, 185.0, 190.0, 200.0) if lo <= s <= hi]
        assert eligible == [180.0, 185.0, 190.0, 200.0]

    def test_window_is_wide_enough_for_the_measured_delta_band(self):
        """Guards the constant against being 'optimised' into wrongness.

        Measured on NVDA over five sessions (2025-10-06 .. 2026-03-09), the
        0.10-0.20 delta band spanned 0.917x-1.054x spot. The window must keep
        clearing that with room to spare, or the filter starts changing which
        strike the strategy picks instead of just how fast it gets there.
        """
        worst_low, worst_high = 0.917, 1.054
        assert 1.0 - STRIKE_WINDOW_PCT < worst_low - 0.05
        assert 1.0 + STRIKE_WINDOW_PCT > worst_high + 0.05

    def test_bounds_are_forwarded_to_the_provider(self):
        p = MockProvider()
        as_of, exp = date(2025, 1, 6), date(2025, 1, 10)
        p.stock = {as_of: 100.0}
        p.add_contract(
            OptionContract(_occ("XYZ", exp, "put", 95), "XYZ", exp, 95.0, "put"),
            close=0.5, traded_on=[as_of],
        )
        ChainBuilder(p).build("XYZ", as_of, max_dte=7)

        _, _, _, gte, lte = p.universe_calls[-1]
        assert gte == pytest.approx(75.0)
        assert lte == pytest.approx(125.0)

    def test_builder_narrows_a_provider_that_ignores_the_bounds(self):
        """The Protocol lets a provider return a superset; the chain may not.

        Without local narrowing, the same request would yield a wider chain
        from a lax provider than from the cache, and a cached run would
        silently disagree with a fresh one.
        """
        p = MockProvider()
        as_of, exp = date(2025, 1, 6), date(2025, 1, 10)
        p.stock = {as_of: 100.0}
        for strike in (50.0, 95.0, 400.0):  # 50 and 400 are far outside +/-25%
            p.add_contract(
                OptionContract(_occ("XYZ", exp, "put", strike), "XYZ", exp, strike, "put"),
                close=0.5, traded_on=[as_of],
            )
        # Force the lax-provider case: strip the mock's own strike filtering.
        p.get_contract_universe = lambda u, a, m, **kw: [
            c for c in p.contracts if a <= c.expiration <= a + timedelta(days=m)
        ]

        snap = ChainBuilder(p).build("XYZ", as_of, max_dte=7)
        assert [q.strike for q in snap.puts] == [95.0]


# --------------------------------------------------------------------------- #
# FC-042 A1 — the chain cache
# --------------------------------------------------------------------------- #
class _CacheFixture:
    """A three-strike chain plus a store, for the cache tests."""

    def __init__(self, tmp_path, strikes=(85.0, 95.0, 100.0), spot=100.0):
        self.provider = MockProvider()
        self.as_of = date(2025, 1, 6)
        self.exp = date(2025, 1, 10)
        self.provider.stock = {self.as_of: spot}
        for strike in strikes:
            self.provider.add_contract(
                OptionContract(
                    _occ("XYZ", self.exp, "put", strike), "XYZ", self.exp, strike, "put"
                ),
                close=max(0.05, (spot - strike) * 0.02 + 0.30),
                traded_on=[self.as_of],
            )
        self.store = ChainStore(str(tmp_path))

    def builder(self):
        return ChainBuilder(self.provider, risk_free_rate=0.04, store=self.store)

    def calls(self):
        return len(self.provider.universe_calls), len(self.provider.option_bar_calls)


class TestChainCache:
    def test_second_build_makes_zero_provider_calls(self, tmp_path):
        """A1's acceptance criterion, at unit scale: calls, not wall-clock."""
        f = _CacheFixture(tmp_path)
        f.builder().build("XYZ", f.as_of, max_dte=7)
        cold = f.calls()
        assert cold[0] > 0 and cold[1] > 0, "cold run must actually fetch"

        f.builder().build("XYZ", f.as_of, max_dte=7)
        assert f.calls() == cold, "warm run must make no provider calls at all"

    def test_warm_chain_is_identical_to_cold(self, tmp_path):
        """The cache must be invisible to results, not merely fast."""
        f = _CacheFixture(tmp_path)
        cold = f.builder().build("XYZ", f.as_of, max_dte=7)
        warm = f.builder().build("XYZ", f.as_of, max_dte=7)

        assert warm.underlying_price == cold.underlying_price
        assert len(warm.puts) == len(cold.puts) and len(warm.calls) == len(cold.calls)
        for a, b in zip(cold.all_quotes(), warm.all_quotes()):
            assert a == b, "round-trip changed a quote"

    def test_a_narrower_cached_window_is_a_miss(self, tmp_path):
        """Fail closed: a file that cannot be proven to cover must refetch.

        This is the covered-call case in cache form — the first run held no
        shares and cached a spot-centred window; the second run is underwater
        and needs strikes above cost basis. Serving the narrow file would hide
        every eligible call and look exactly like a day they did not trade.
        """
        f = _CacheFixture(tmp_path)
        f.builder().build("XYZ", f.as_of, max_dte=7)
        after_cold = f.calls()

        f.builder().build("XYZ", f.as_of, max_dte=7, cost_basis=180.0)
        assert f.calls() != after_cold, "wider request must go back to the provider"

    def test_a_wider_cached_window_is_a_hit_and_is_narrowed(self, tmp_path):
        f = _CacheFixture(tmp_path, strikes=(85.0, 95.0, 100.0, 200.0), spot=100.0)
        # Cache a wide window (cost basis 180 -> upper bound 225).
        wide = f.builder().build("XYZ", f.as_of, max_dte=7, cost_basis=180.0)
        assert 200.0 in [q.strike for q in wide.puts]
        after_cold = f.calls()

        narrow = f.builder().build("XYZ", f.as_of, max_dte=7)
        assert f.calls() == after_cold, "narrower request is covered: no refetch"
        assert 200.0 not in [q.strike for q in narrow.puts], "must narrow on read"
        assert [q.strike for q in narrow.puts] == [85.0, 95.0, 100.0]

    def test_a_shorter_cached_dte_reach_is_a_miss(self, tmp_path):
        f = _CacheFixture(tmp_path)
        f.builder().build("XYZ", f.as_of, max_dte=3)
        after_cold = f.calls()
        f.builder().build("XYZ", f.as_of, max_dte=14)
        assert f.calls() != after_cold

    def test_a_longer_cached_dte_reach_is_narrowed_on_read(self, tmp_path):
        """A 14-DTE file must not smuggle a 10-DTE contract into a 7-DTE run."""
        p = MockProvider()
        as_of = date(2025, 1, 6)
        p.stock = {as_of: 100.0}
        for exp in (date(2025, 1, 10), date(2025, 1, 17)):  # 4 and 11 DTE
            p.add_contract(
                OptionContract(_occ("XYZ", exp, "put", 95), "XYZ", exp, 95.0, "put"),
                close=0.5, traded_on=[as_of],
            )
        store = ChainStore(str(tmp_path))

        wide = ChainBuilder(p, store=store).build("XYZ", as_of, max_dte=14)
        assert sorted(q.dte for q in wide.puts) == [4, 11]

        narrow = ChainBuilder(p, store=store).build("XYZ", as_of, max_dte=7)
        assert sorted(q.dte for q in narrow.puts) == [4]

    def test_a_different_underlying_close_is_a_miss(self, tmp_path):
        """Every delta in the file was computed against the cached close."""
        f = _CacheFixture(tmp_path)
        f.builder().build("XYZ", f.as_of, max_dte=7, underlying_price=100.0)
        after_cold = f.calls()
        f.builder().build("XYZ", f.as_of, max_dte=7, underlying_price=101.0)
        assert f.calls() != after_cold

    def test_todays_chain_is_never_persisted(self, tmp_path):
        """Today's session is still forming — caching it freezes a partial day.

        Exercised through the bypass that makes it reachable at all: supplying
        underlying_price skips the stock-bar fetch that would otherwise return
        nothing for today.
        """
        f = _CacheFixture(tmp_path)
        today = date.today()
        f.builder().build("XYZ", today, max_dte=7, underlying_price=100.0)
        assert f.store.get("XYZ", today) is None
        assert not f.store.has("XYZ", today)

        # A settled past session, by contrast, is cached.
        f.builder().build("XYZ", f.as_of, max_dte=7, underlying_price=100.0)
        assert f.store.has("XYZ", f.as_of)

    def test_an_empty_chain_is_cached_rather_than_refetched_forever(self, tmp_path):
        """A genuinely empty day must not look like a cache miss every run."""
        p = MockProvider()
        as_of = date(2025, 1, 6)
        p.stock = {as_of: 100.0}
        store = ChainStore(str(tmp_path))

        first = ChainBuilder(p, store=store).build("XYZ", as_of, max_dte=7)
        assert first is not None and first.all_quotes() == []
        after_cold = (len(p.universe_calls), len(p.option_bar_calls))

        second = ChainBuilder(p, store=store).build("XYZ", as_of, max_dte=7)
        assert second is not None and second.all_quotes() == []
        assert (len(p.universe_calls), len(p.option_bar_calls)) == after_cold

    def test_a_file_without_provenance_cannot_satisfy_a_bounded_request(self, tmp_path):
        """Legacy/undeclared files fail closed rather than being assumed wide."""
        f = _CacheFixture(tmp_path)
        snap = ChainBuilder(f.provider).build("XYZ", f.as_of, max_dte=7)
        f.store.put(snap)  # no provenance declared

        assert f.store.get("XYZ", f.as_of) is not None, "unbounded read still works"
        assert f.store.get(
            "XYZ", f.as_of, universe_dte=8, strike_gte=75.0, strike_lte=125.0
        ) is None

    def test_caching_is_off_unless_a_store_is_supplied(self, tmp_path):
        """Default-off keeps one unit test from reading another's chain."""
        f = _CacheFixture(tmp_path)
        ChainBuilder(f.provider).build("XYZ", f.as_of, max_dte=7)
        assert not f.store.has("XYZ", f.as_of)


class TestProviderStrikeBounds:
    """The provider half of A2, against a stubbed Alpaca client."""

    def _provider_capturing_requests(self):
        from src.backtesting.data.alpaca_provider import AlpacaDataProvider

        provider = AlpacaDataProvider(api_key="k", secret_key="s", paper=True)
        seen = []

        class _Resp:
            next_page_token = None
            option_contracts = []

        def _stub(req):
            seen.append(req)
            return _Resp()

        provider._trading.get_option_contracts = _stub
        return provider, seen

    def test_bounds_are_sent_as_strings_not_floats(self):
        """The SDK types strike_price_gte/lte as Optional[str].

        Passing a float fails pydantic validation and 500s every contract-
        discovery call — which would surface as 'no contracts' on every day of
        every backtest, i.e. a silent zero-trade run rather than a crash.
        """
        provider, seen = self._provider_capturing_requests()
        provider.get_contract_universe(
            "NVDA", date(2025, 10, 6), 8, strike_gte=139.155, strike_lte=231.925
        )
        assert seen, "no request was issued"
        for req in seen:
            assert isinstance(req.strike_price_gte, str)
            assert isinstance(req.strike_price_lte, str)
            assert req.strike_price_gte == "139.16"
            assert req.strike_price_lte == "231.93"

    def test_unbounded_request_sends_no_strike_filter(self):
        """Existing callers must keep the full ladder."""
        provider, seen = self._provider_capturing_requests()
        provider.get_contract_universe("NVDA", date(2025, 10, 6), 8)
        for req in seen:
            assert req.strike_price_gte is None
            assert req.strike_price_lte is None

    def test_memo_is_keyed_by_the_strike_window(self):
        """Otherwise a narrow first call would poison every later wide one."""
        provider, seen = self._provider_capturing_requests()
        as_of = date(2025, 10, 6)
        provider.get_contract_universe("NVDA", as_of, 8, strike_gte=100.0, strike_lte=200.0)
        n_after_first = len(seen)
        provider.get_contract_universe("NVDA", as_of, 8, strike_gte=100.0, strike_lte=200.0)
        assert len(seen) == n_after_first, "identical window must hit the memo"

        provider.get_contract_universe("NVDA", as_of, 8, strike_gte=50.0, strike_lte=300.0)
        assert len(seen) > n_after_first, "different window must not reuse the memo"
