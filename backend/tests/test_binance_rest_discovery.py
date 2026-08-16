"""Unit tests for BinanceRestClient.fetch_exchange_info/fetch_24h_tickers (spec 12) — no
real network, httpx.Client is monkeypatched to return canned responses."""

from __future__ import annotations

import httpx

from tradingbot.ingestion import binance_rest


class _FakeClient:
    def __init__(self, response_json):
        self._response_json = response_json

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def get(self, url, **kwargs):
        return httpx.Response(200, json=self._response_json, request=httpx.Request("GET", url))


def test_fetch_exchange_info_parses_symbols(monkeypatch):
    payload = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "baseAsset": "BTC",
                "quoteAsset": "USDT",
                "status": "TRADING",
                "isSpotTradingAllowed": True,
            },
            {
                "symbol": "BTCUPUSDT",
                "baseAsset": "BTCUP",
                "quoteAsset": "USDT",
                "status": "TRADING",
                "isSpotTradingAllowed": True,
            },
        ]
    }
    monkeypatch.setattr(binance_rest.httpx, "Client", lambda **kwargs: _FakeClient(payload))

    client = binance_rest.BinanceRestClient()
    symbols = client.fetch_exchange_info()

    assert len(symbols) == 2
    assert symbols[0].symbol == "BTCUSDT"
    assert symbols[0].quote_asset == "USDT"
    assert symbols[0].is_spot_trading_allowed is True


def test_fetch_24h_tickers_parses_volume_and_price(monkeypatch):
    payload = [
        {"symbol": "BTCUSDT", "quoteVolume": "312381234.95", "lastPrice": "63066.94"},
        {"symbol": "ETHUSDT", "quoteVolume": "50000000.12", "lastPrice": "3000.50"},
    ]
    monkeypatch.setattr(binance_rest.httpx, "Client", lambda **kwargs: _FakeClient(payload))

    client = binance_rest.BinanceRestClient()
    tickers = client.fetch_24h_tickers()

    assert len(tickers) == 2
    assert tickers[0].symbol == "BTCUSDT"
    assert tickers[0].quote_volume == 312381234.95
    assert tickers[1].last_price == 3000.50
