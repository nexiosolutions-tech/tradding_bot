"""Unit tests for BinanceKlineStream's message handling — no network involved (that's
test_binance_ws_live.py's job). Exercises the per-message try/except added so a malformed
payload costs one message, not the whole connection."""

from __future__ import annotations

import asyncio

import pytest

from tradingbot.ingestion import binance_ws
from tradingbot.ingestion.schema import EventType


class _FakeWebsocket:
    def __init__(self, raw_messages):
        self._raw_messages = raw_messages

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for raw in self._raw_messages:
            yield raw

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def _valid_kline_raw(symbol="BTCUSDT", close=100.0, ts=60_000):
    import json

    return json.dumps(
        {
            "data": {
                "e": "kline",
                "k": {
                    "t": ts - 60_000,
                    "T": ts,
                    "s": symbol,
                    "i": "1m",
                    "o": close,
                    "h": close,
                    "l": close,
                    "c": close,
                    "v": 10.0,
                    "x": True,
                },
            }
        }
    )


@pytest.mark.asyncio
async def test_malformed_message_is_skipped_not_fatal(monkeypatch):
    fake_ws = _FakeWebsocket(["{not valid json", _valid_kline_raw()])

    def fake_connect(url, **kwargs):
        return fake_ws

    monkeypatch.setattr(binance_ws.websockets, "connect", fake_connect)

    stream = binance_ws.BinanceKlineStream(symbols=["BTCUSDT"], interval="1m", testnet=True)
    agen = stream.__aiter__()
    event = await asyncio.wait_for(agen.__anext__(), timeout=5)
    await agen.aclose()

    assert event.event_type == EventType.KLINE
    assert event.symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_message_missing_expected_fields_is_skipped_not_fatal(monkeypatch):
    import json

    malformed = json.dumps({"data": {"e": "kline", "k": {"t": 0}}})  # missing required keys
    fake_ws = _FakeWebsocket([malformed, _valid_kline_raw()])

    def fake_connect(url, **kwargs):
        return fake_ws

    monkeypatch.setattr(binance_ws.websockets, "connect", fake_connect)

    stream = binance_ws.BinanceKlineStream(symbols=["BTCUSDT"], interval="1m", testnet=True)
    agen = stream.__aiter__()
    event = await asyncio.wait_for(agen.__anext__(), timeout=5)
    await agen.aclose()

    assert event.event_type == EventType.KLINE
