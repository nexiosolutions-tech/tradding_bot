"""Unit tests for BinanceDepthStream's message handling — no network involved. Mirrors
test_binance_ws.py's approach (fake websocket, no real connection)."""

from __future__ import annotations

import asyncio
import json

import pytest

from tradingbot.ingestion import binance_depth_ws
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


def _valid_depth_raw(symbol="btcusdt", last_update_id=42):
    return json.dumps(
        {
            "stream": f"{symbol}@depth20@1000ms",
            "data": {
                "lastUpdateId": last_update_id,
                "bids": [["100.00", "1.5"], ["99.99", "2.0"]],
                "asks": [["100.01", "1.0"], ["100.02", "3.0"]],
            },
        }
    )


@pytest.mark.asyncio
async def test_valid_message_yields_depth_event(monkeypatch):
    fake_ws = _FakeWebsocket([_valid_depth_raw()])

    def fake_connect(url, **kwargs):
        return fake_ws

    monkeypatch.setattr(binance_depth_ws.websockets, "connect", fake_connect)

    stream = binance_depth_ws.BinanceDepthStream(symbols=["BTCUSDT"], testnet=True)
    agen = stream.__aiter__()
    event = await asyncio.wait_for(agen.__anext__(), timeout=5)
    await agen.aclose()

    assert event.event_type == EventType.DEPTH
    assert event.symbol == "BTCUSDT"
    assert event.sequence_id == 42
    assert event.payload["bids"] == [[100.0, 1.5], [99.99, 2.0]]
    assert event.payload["asks"] == [[100.01, 1.0], [100.02, 3.0]]


@pytest.mark.asyncio
async def test_malformed_message_is_skipped_not_fatal(monkeypatch):
    fake_ws = _FakeWebsocket(["{not valid json", _valid_depth_raw()])

    def fake_connect(url, **kwargs):
        return fake_ws

    monkeypatch.setattr(binance_depth_ws.websockets, "connect", fake_connect)

    stream = binance_depth_ws.BinanceDepthStream(symbols=["BTCUSDT"], testnet=True)
    agen = stream.__aiter__()
    event = await asyncio.wait_for(agen.__anext__(), timeout=5)
    await agen.aclose()

    assert event.event_type == EventType.DEPTH


@pytest.mark.asyncio
async def test_message_missing_expected_fields_is_skipped_not_fatal(monkeypatch):
    malformed = json.dumps({"stream": "btcusdt@depth20@1000ms", "data": {"lastUpdateId": 1}})
    fake_ws = _FakeWebsocket([malformed, _valid_depth_raw()])

    def fake_connect(url, **kwargs):
        return fake_ws

    monkeypatch.setattr(binance_depth_ws.websockets, "connect", fake_connect)

    stream = binance_depth_ws.BinanceDepthStream(symbols=["BTCUSDT"], testnet=True)
    agen = stream.__aiter__()
    event = await asyncio.wait_for(agen.__anext__(), timeout=5)
    await agen.aclose()

    assert event.event_type == EventType.DEPTH


def test_parse_depth_message_extracts_symbol_from_stream_name():
    msg = json.loads(_valid_depth_raw(symbol="ethusdt", last_update_id=7))
    symbol, payload = binance_depth_ws._parse_depth_message(msg)

    assert symbol == "ETHUSDT"
    assert payload.last_update_id == 7


def test_parse_depth_message_returns_none_without_stream_or_data():
    assert binance_depth_ws._parse_depth_message({}) is None
    assert binance_depth_ws._parse_depth_message({"stream": "btcusdt@depth20@1000ms"}) is None
