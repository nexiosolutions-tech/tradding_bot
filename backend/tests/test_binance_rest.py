"""Unit tests for BinanceRestClient.fetch_agg_trades — no real network, httpx.Client is
monkeypatched to return canned, paginated responses. Mirrors
test_binance_rest_discovery.py's approach."""

from __future__ import annotations

import httpx

from tradingbot.ingestion import binance_rest


class _FakePaginatedClient:
    """Returns one page of `pages` per call, keyed by call order — mirrors how the real
    Binance API would respond to successive fromId-cursored requests."""

    def __init__(self, pages: list[list[dict]]):
        self._pages = pages
        self._call_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def get(self, url, **kwargs):
        page = self._pages[self._call_count] if self._call_count < len(self._pages) else []
        self._call_count += 1
        return httpx.Response(200, json=page, request=httpx.Request("GET", url))


def _row(agg_trade_id, trade_time=1_700_000_000_000, price="100.0", qty="1.0", is_buyer_maker=False):
    return {
        "a": agg_trade_id,
        "p": price,
        "q": qty,
        "f": agg_trade_id,
        "l": agg_trade_id,
        "T": trade_time,
        "m": is_buyer_maker,
        "M": True,
    }


def test_fetch_agg_trades_single_page_stops_when_short_of_limit(monkeypatch):
    page = [_row(1), _row(2), _row(3)]
    monkeypatch.setattr(binance_rest.httpx, "Client", lambda **kwargs: _FakePaginatedClient([page]))

    client = binance_rest.BinanceRestClient()
    events = client.fetch_agg_trades("BTCUSDT", from_id=1, limit=1000)

    assert [e.sequence_id for e in events] == [1, 2, 3]


def test_fetch_agg_trades_paginates_across_multiple_pages(monkeypatch):
    page1 = [_row(i) for i in range(1, 4)]  # ids 1..3, full page of 3 (limit=3)
    page2 = [_row(4), _row(5)]  # short page -> stop
    monkeypatch.setattr(binance_rest.httpx, "Client", lambda **kwargs: _FakePaginatedClient([page1, page2]))

    client = binance_rest.BinanceRestClient()
    events = client.fetch_agg_trades("BTCUSDT", from_id=1, limit=3)

    assert [e.sequence_id for e in events] == [1, 2, 3, 4, 5]


def test_fetch_agg_trades_stops_at_to_id_even_mid_page(monkeypatch):
    page = [_row(1), _row(2), _row(3), _row(4), _row(5)]
    monkeypatch.setattr(binance_rest.httpx, "Client", lambda **kwargs: _FakePaginatedClient([page]))

    client = binance_rest.BinanceRestClient()
    events = client.fetch_agg_trades("BTCUSDT", from_id=1, to_id=3, limit=1000)

    assert [e.sequence_id for e in events] == [1, 2, 3]


def test_fetch_agg_trades_returns_empty_list_when_no_rows(monkeypatch):
    monkeypatch.setattr(binance_rest.httpx, "Client", lambda **kwargs: _FakePaginatedClient([[]]))

    client = binance_rest.BinanceRestClient()
    events = client.fetch_agg_trades("BTCUSDT", from_id=1)

    assert events == []


def test_fetch_agg_trades_decodes_aggressor_side_and_exchange_ts(monkeypatch):
    page = [_row(1, trade_time=1_755_000_000_000, is_buyer_maker=True)]
    monkeypatch.setattr(binance_rest.httpx, "Client", lambda **kwargs: _FakePaginatedClient([page]))

    client = binance_rest.BinanceRestClient()
    events = client.fetch_agg_trades("BTCUSDT", from_id=1)

    assert events[0].exchange_ts == 1_755_000_000_000
    assert events[0].payload["is_buyer_maker"] is True


def test_fetch_depth_parses_bids_and_asks(monkeypatch):
    payload = {
        "lastUpdateId": 12345,
        "bids": [["100.00", "1.5"], ["99.99", "2.0"]],
        "asks": [["100.01", "1.0"], ["100.02", "3.0"]],
    }

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def get(self, url, **kwargs):
            assert kwargs["params"] == {"symbol": "BTCUSDT", "limit": 20}
            return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(binance_rest.httpx, "Client", lambda **kwargs: _FakeClient())

    client = binance_rest.BinanceRestClient()
    depth = client.fetch_depth("BTCUSDT", limit=20)

    assert depth.last_update_id == 12345
    assert depth.bids == [(100.0, 1.5), (99.99, 2.0)]
    assert depth.asks == [(100.01, 1.0), (100.02, 3.0)]


def test_mainnet_base_url_is_data_api_vision_not_api_binance_com():
    """api.binance.com is geoblocked from this project's Railway region (2026-08-18,
    changes/2026-08-18-captura-aggtrade-fluxo-ordens.md); data-api.binance.vision mirrors
    the same public routes and is not."""
    client = binance_rest.BinanceRestClient(testnet=False)
    assert client._base_url == "https://data-api.binance.vision"


def test_testnet_base_url_is_unchanged():
    client = binance_rest.BinanceRestClient(testnet=True)
    assert client._base_url == "https://testnet.binance.vision"
