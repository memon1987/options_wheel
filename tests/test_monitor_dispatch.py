"""FC-045: /monitor must DISPATCH a call to the call seller, not just parse it.

The first version of these tests exercised `strict_option_type` in isolation
plus a source-text grep. A reviewer then swapped the dispatch outright —
`is_put = opt_type == 'call'`, which would run every put through call logic —
and the entire suite stayed green. Parser coverage is not dispatch coverage.

This drives the real Flask route with mocked brokerage/sellers and asserts the
*routing outcome*, so a swapped or reverted dispatch fails here.
"""

import importlib
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

flask = pytest.importorskip("flask")


@pytest.fixture
def server():
    """The Cloud Run app module (imports Flask + the strategy stack)."""
    return importlib.import_module("deploy.cloud_run_server")


def _option(symbol):
    return {
        "symbol": symbol, "asset_class": "us_option", "qty": "-1",
        "market_value": "-150.00", "unrealized_pl": "50.00",
        "avg_entry_price": "2.00", "current_price": "1.50",
    }


def _dispatch(server, symbol):
    """POST /monitor with one option position; return (put_seller, call_seller)."""
    put_seller, call_seller = Mock(), Mock()
    put_seller.should_close_put_early.return_value = False
    call_seller.should_close_call_early.return_value = False

    alpaca = Mock()
    alpaca.get_positions.return_value = [_option(symbol)]

    with patch("src.api.alpaca_client.AlpacaClient", return_value=alpaca), \
         patch("src.api.market_data.MarketDataManager", return_value=Mock()), \
         patch("src.strategy.put_seller.PutSeller", return_value=put_seller), \
         patch("src.strategy.call_seller.CallSeller", return_value=call_seller), \
         patch.object(server, "_is_market_open", return_value=True):
        client = server.app.test_client()
        resp = client.post("/monitor")

    assert resp.status_code == 200, resp.data
    return put_seller, call_seller


class TestMonitorDispatch:
    """A P-containing ticker is the whole point: AAPL/SPY/PFE."""

    def test_an_aapl_call_reaches_the_call_seller(self, server):
        """THE FC-045 REGRESSION. 'P' in 'AAPL...' sent this to the put path."""
        put_seller, call_seller = _dispatch(server, "AAPL260814C00190000")

        call_seller.should_close_call_early.assert_called_once()
        put_seller.should_close_put_early.assert_not_called()

    def test_an_aapl_put_still_reaches_the_put_seller(self, server):
        """The fix must not swap the dispatch."""
        put_seller, call_seller = _dispatch(server, "AAPL260814P00170000")

        put_seller.should_close_put_early.assert_called_once()
        call_seller.should_close_call_early.assert_not_called()

    def test_an_spy_call_reaches_the_call_seller(self, server):
        put_seller, call_seller = _dispatch(server, "SPY260814C00600000")

        call_seller.should_close_call_early.assert_called_once()
        put_seller.should_close_put_early.assert_not_called()

    def test_a_non_contract_is_dispatched_to_neither_seller(self, server):
        """Skipped, not guessed. Pre-fix a bare ticker took the put branch."""
        put_seller, call_seller = _dispatch(server, "AAPL")

        put_seller.should_close_put_early.assert_not_called()
        call_seller.should_close_call_early.assert_not_called()
