"""BacktestAlpacaClient (FC-032 Phase 3).

The adapter is where a replay can silently lie: serve tomorrow's price, quietly
reach for production, or present a chain more permissive than the live one. Each
of those gets a test here.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from src.backtesting.data.chain_builder import ChainQuote, ChainSnapshot
from src.backtesting.data.provider import StockBar
from src.backtesting.engine.alpaca_adapter import (
    BacktestAlpacaClient,
    UnsupportedBacktestCall,
)
from src.backtesting.engine.broker import BacktestBroker
from src.utils import clock

D1 = date(2024, 6, 3)
D2 = date(2024, 6, 4)
EXP = date(2024, 6, 7)
PUT = "XYZ240607P00090000"
CALL = "XYZ240607C00110000"


def _quote(symbol, opt_type, strike, *, as_of, mark, bid, ask, delta, spot=100.0, vol=25):
    return ChainQuote(
        symbol=symbol, underlying="XYZ", as_of=as_of, expiration=EXP, strike=strike,
        option_type=opt_type, dte=(EXP - as_of).days, underlying_price=spot,
        mark=mark, bid=bid, ask=ask, implied_volatility=0.30, delta=delta, volume=vol,
    )


def _snapshot(as_of, spot=100.0, *, puts=None, calls=None):
    return ChainSnapshot("XYZ", as_of, spot, puts or [], calls or [])


def _bars(*specs):
    return [
        StockBar(symbol="XYZ", bar_date=d, open=c, high=c, low=c, close=c, volume=1_000_000)
        for d, c in specs
    ]


@pytest.fixture
def setup():
    broker = BacktestBroker(starting_cash=50_000.0)
    put_q = _quote(PUT, "put", 90.0, as_of=D1, mark=1.00, bid=0.90, ask=1.10, delta=-0.15)
    call_q = _quote(CALL, "call", 110.0, as_of=D1, mark=0.80, bid=0.70, ask=0.90, delta=0.18)
    chains = {"XYZ": {
        D1: _snapshot(D1, 100.0, puts=[put_q], calls=[call_q]),
        D2: _snapshot(D2, 104.0,
                      puts=[_quote(PUT, "put", 90.0, as_of=D2, mark=0.40, bid=0.35, ask=0.45,
                                   delta=-0.08, spot=104.0)]),
    }}
    stock = {"XYZ": _bars((D1, 100.0), (D2, 104.0), (date(2024, 6, 5), 108.0))}
    client = BacktestAlpacaClient(broker, chains=chains, stock_bars=stock)
    return broker, client


def _at(day: date):
    return clock.frozen(datetime.combine(day, time(16, 0)))


class TestNoLookahead:
    def test_stock_bars_never_return_a_future_bar(self, setup):
        _, client = setup
        with _at(D1):
            df = client.get_stock_bars("XYZ", days=30)
        assert list(df.index.date) == [D1]
        assert df["close"].iloc[-1] == 100.0

    def test_stock_bars_grow_as_the_simulation_advances(self, setup):
        _, client = setup
        with _at(D1):
            assert len(client.get_stock_bars("XYZ", days=30)) == 1
        with _at(D2):
            df = client.get_stock_bars("XYZ", days=30)
        assert list(df.index.date) == [D1, D2]

    def test_stock_bars_index_is_tz_aware_utc_like_live(self, setup):
        """GapDetector does df[df.index < utc_now]; a naive index raises and it

        swallows the error into "no previous close", silently blocking every
        trade. Live returns datetime64[ns, UTC] stamped 04:00.
        """
        import pandas as pd

        _, client = setup
        with _at(D2):
            df = client.get_stock_bars("XYZ", days=30)
        assert str(df.index.dtype) == "datetime64[ns, UTC]"
        assert df.index[0].hour == 4
        # The comparison GapDetector actually performs must not raise.
        utc_now = pd.Timestamp(datetime.combine(D2, time(16, 0)), tz="UTC")
        assert len(df[df.index < utc_now]) == 2

    def test_quote_is_the_simulated_days_close(self, setup):
        _, client = setup
        with _at(D1):
            assert client.get_stock_quote("XYZ")["bid"] == 100.0
        with _at(D2):
            assert client.get_stock_quote("XYZ")["bid"] == 104.0

    def test_chain_is_the_simulated_days_chain(self, setup):
        _, client = setup
        with _at(D1):
            syms = {o["symbol"] for o in client.get_options_chain("XYZ")}
        assert syms == {PUT, CALL}
        with _at(D2):
            day2 = client.get_options_chain("XYZ")
        assert {o["symbol"] for o in day2} == {PUT}  # the call did not trade on D2
        assert day2[0]["last_price"] == 0.40


class TestFailsLoud:
    def test_unimplemented_attribute_raises(self, setup):
        _, client = setup
        with pytest.raises(UnsupportedBacktestCall, match="cancel_order"):
            client.cancel_order

    def test_raw_trading_client_reachthrough_raises(self, setup):
        """wheel_engine.py reaches for .trading_client; it must not silently work."""
        _, client = setup
        with pytest.raises(UnsupportedBacktestCall, match="trading_client"):
            client.trading_client

    def test_using_the_adapter_without_a_frozen_clock_raises(self, setup):
        _, client = setup
        assert not clock.is_frozen()
        with pytest.raises(UnsupportedBacktestCall, match="frozen clock"):
            client.get_stock_quote("XYZ")


class TestMirrorsLiveChainShape:
    def test_open_interest_is_zero_like_live(self, setup):
        """Live hardcodes 0, making its liquidity gate 'volume must be non-zero'.

        Fabricating OI would make the backtest more permissive than production.
        """
        _, client = setup
        with _at(D1):
            chain = client.get_options_chain("XYZ")
        assert all(o["open_interest"] == 0 for o in chain)
        assert all(o["volume"] > 0 for o in chain)

    def test_contracts_with_unsolved_iv_are_dropped_not_passed_as_none(self, setup):
        """Live does abs(opt.get('delta', 0)); a None delta would TypeError."""
        broker = BacktestBroker(starting_cash=50_000.0)
        bad = _quote(PUT, "put", 90.0, as_of=D1, mark=1.0, bid=0.9, ask=1.1, delta=None)
        client = BacktestAlpacaClient(
            broker, chains={"XYZ": {D1: _snapshot(D1, puts=[bad])}},
            stock_bars={"XYZ": _bars((D1, 100.0))},
        )
        with _at(D1):
            chain = client.get_options_chain("XYZ")
        assert chain == []
        # And the value live would have crashed on is never produced.
        assert all(o["delta"] is not None for o in chain)

    def test_greeks_live_code_ignores_are_zero(self, setup):
        _, client = setup
        with _at(D1):
            o = client.get_options_chain("XYZ")[0]
        assert (o["gamma"], o["theta"], o["vega"]) == (0.0, 0.0, 0.0)
        assert o["delta"] != 0.0  # the one greek that is actually consumed


class TestOrdersMoveTheBroker:
    def test_sell_put_reserves_collateral_and_credits_premium(self, setup):
        broker, client = setup
        with _at(D1):
            res = client.place_option_order(PUT, 1, "sell", limit_price=1.00)
        assert res["success"] is True
        # mark 1.00, bid 0.90, haircut 0.25 -> 1.00 - 0.25*0.10 = 0.975
        assert broker.options[PUT].entry_price == pytest.approx(0.975)
        assert broker.reserved_collateral == pytest.approx(9_000.0)
        assert broker.available_cash == pytest.approx(50_000 + 97.5 - 0.04 - 9_000)

    def test_sell_put_rejected_when_collateral_unavailable(self):
        broker = BacktestBroker(starting_cash=1_000.0)
        q = _quote(PUT, "put", 90.0, as_of=D1, mark=1.0, bid=0.9, ask=1.1, delta=-0.15)
        client = BacktestAlpacaClient(
            broker, chains={"XYZ": {D1: _snapshot(D1, puts=[q])}},
            stock_bars={"XYZ": _bars((D1, 100.0))},
        )
        with _at(D1):
            res = client.place_option_order(PUT, 1, "sell", limit_price=1.0)
        assert res["success"] is False
        assert res["error_type"] == "insufficient_collateral"
        assert broker.options == {}

    def test_order_for_a_contract_that_did_not_trade_is_rejected(self, setup):
        _, client = setup
        with _at(D2):  # the call has no D2 bar
            res = client.place_option_order(CALL, 1, "sell", limit_price=0.8)
        assert res["success"] is False and res["error_type"] == "no_quote"

    def test_filled_order_is_retrievable(self, setup):
        _, client = setup
        with _at(D1):
            res = client.place_option_order(PUT, 1, "sell", limit_price=1.0)
            got = client.get_order_by_id(res["order_id"])
            assert got["status"] == "filled"
            assert got["filled_avg_price"] == pytest.approx(0.975)
            assert len(client.get_orders(status="filled")) == 1


class TestPositionsAndAccount:
    def test_short_put_reports_negative_qty_and_us_option_class(self, setup):
        _, client = setup
        with _at(D1):
            client.place_option_order(PUT, 1, "sell", limit_price=1.0)
            positions = client.get_positions()
        opt = [p for p in positions if p["asset_class"] == "us_option"][0]
        assert opt["qty"] == -1.0 and opt["side"] == "short"
        assert opt["market_value"] == pytest.approx(-100.0)  # mark 1.00 * 100

    def test_short_put_gains_as_premium_decays(self, setup):
        _, client = setup
        with _at(D1):
            client.place_option_order(PUT, 1, "sell", limit_price=1.0)
        with _at(D2):  # mark falls 0.975 -> 0.40
            opt = [p for p in client.get_positions() if p["asset_class"] == "us_option"][0]
        assert opt["unrealized_pl"] == pytest.approx((0.975 - 0.40) * 100)

    def test_buying_power_excludes_reserved_collateral_no_margin(self, setup):
        broker, client = setup
        with _at(D1):
            client.place_option_order(PUT, 1, "sell", limit_price=1.0)
            acct = client.get_account()
        assert acct["buying_power"] == pytest.approx(broker.available_cash)
        assert acct["buying_power"] < acct["cash"]  # collateral is locked away

    def test_assigned_shares_appear_as_long_equity(self, setup):
        broker, client = setup
        with _at(D1):
            client.place_option_order(PUT, 1, "sell", limit_price=1.0)
        # Underlying closes below the strike at expiry -> assigned.
        broker.settle_expirations(EXP, {"XYZ": 85.0})
        with _at(EXP):
            stock = [p for p in client.get_positions() if p["asset_class"] == "us_equity"]
        assert len(stock) == 1
        assert stock[0]["symbol"] == "XYZ" and stock[0]["qty"] == 100.0


class TestActivities:
    def test_assignment_surfaces_as_an_opasn_activity(self, setup):
        broker, client = setup
        with _at(D1):
            client.place_option_order(PUT, 1, "sell", limit_price=1.0)
        broker.settle_expirations(EXP, {"XYZ": 85.0})
        with _at(EXP):
            acts = client.get_account_activities("OPASN,OPEXP", after="2024-06-01")
        assert len(acts) == 1
        assert acts[0]["activity_type"] == "OPASN"
        assert acts[0]["symbol"] == PUT

    def test_worthless_expiry_surfaces_as_opexp(self, setup):
        broker, client = setup
        with _at(D1):
            client.place_option_order(PUT, 1, "sell", limit_price=1.0)
        broker.settle_expirations(EXP, {"XYZ": 120.0})  # far OTM -> expires
        with _at(EXP):
            acts = client.get_account_activities("OPASN,OPEXP", after="2024-06-01")
        assert [a["activity_type"] for a in acts] == ["OPEXP"]

    def test_activity_ids_are_stable_across_calls(self, setup):
        """wheel_engine dedupes by id; unstable ids would double-count assignments."""
        broker, client = setup
        with _at(D1):
            client.place_option_order(PUT, 1, "sell", limit_price=1.0)
        broker.settle_expirations(EXP, {"XYZ": 85.0})
        with _at(EXP):
            first = client.get_account_activities("OPASN", after="2024-06-01")
            second = client.get_account_activities("OPASN", after="2024-06-01")
        assert [a["id"] for a in first] == [a["id"] for a in second]

    def test_activities_filter_by_type_and_after_date(self, setup):
        broker, client = setup
        with _at(D1):
            client.place_option_order(PUT, 1, "sell", limit_price=1.0)
        broker.settle_expirations(EXP, {"XYZ": 85.0})
        with _at(EXP):
            assert client.get_account_activities("OPEXP", after="2024-06-01") == []
            after_cutoff = client.get_account_activities(
                "OPASN", after=(EXP + timedelta(days=1)).isoformat()
            )
        assert after_cutoff == []

    def test_ledger_events_after_the_simulated_date_are_not_visible(self, setup):
        """Even our own ledger must not leak the future into a decision."""
        broker, client = setup
        with _at(D1):
            client.place_option_order(PUT, 1, "sell", limit_price=1.0)
        broker.settle_expirations(EXP, {"XYZ": 85.0})
        with _at(D2):  # D2 < EXP: the assignment has not happened yet, in sim time
            assert client.get_account_activities("OPASN", after="2024-06-01") == []
