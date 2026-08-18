"""Unit tests for BinanceAggTradeStream's message handling — no network involved. Mirrors
test_binance_depth_ws.py's approach (fake websocket, no real connection)."""

from __future__ import annotations

import asyncio
import json

import pytest

from tradingbot.ingestion import binance_aggtrade_ws
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


def _valid_aggtrade_raw(symbol="btcusdt", agg_trade_id=42, trade_time=1_700_000_000_000, is_buyer_maker=True):
    return json.dumps(
        {
            "stream": f"{symbol}@aggTrade",
            "data": {
                "e": "aggTrade",
                "E": trade_time + 5,
                "s": symbol.upper(),
                "a": agg_trade_id,
                "p": "100.50",
                "q": "0.25",
                "f": 100,
                "l": 103,
                "T": trade_time,
                "m": is_buyer_maker,
                "M": True,
            },
        }
    )


@pytest.mark.asyncio
async def test_valid_message_yields_trade_event(monkeypatch):
    fake_ws = _FakeWebsocket([_valid_aggtrade_raw()])

    def fake_connect(url, **kwargs):
        return fake_ws

    monkeypatch.setattr(binance_aggtrade_ws.websockets, "connect", fake_connect)

    stream = binance_aggtrade_ws.BinanceAggTradeStream(symbols=["BTCUSDT"], testnet=True)
    agen = stream.__aiter__()
    event = await asyncio.wait_for(agen.__anext__(), timeout=5)
    await agen.aclose()

    assert event.event_type == EventType.TRADE
    assert event.symbol == "BTCUSDT"
    assert event.sequence_id == 42
    assert event.exchange_ts == 1_700_000_000_000
    assert event.payload["price"] == 100.50
    assert event.payload["quantity"] == 0.25
    assert event.payload["is_buyer_maker"] is True


@pytest.mark.asyncio
async def test_malformed_message_is_skipped_not_fatal(monkeypatch):
    fake_ws = _FakeWebsocket(["{not valid json", _valid_aggtrade_raw()])

    def fake_connect(url, **kwargs):
        return fake_ws

    monkeypatch.setattr(binance_aggtrade_ws.websockets, "connect", fake_connect)

    stream = binance_aggtrade_ws.BinanceAggTradeStream(symbols=["BTCUSDT"], testnet=True)
    agen = stream.__aiter__()
    event = await asyncio.wait_for(agen.__anext__(), timeout=5)
    await agen.aclose()

    assert event.event_type == EventType.TRADE


@pytest.mark.asyncio
async def test_message_missing_expected_fields_is_skipped_not_fatal(monkeypatch):
    malformed = json.dumps({"stream": "btcusdt@aggTrade", "data": {"a": 1}})
    fake_ws = _FakeWebsocket([malformed, _valid_aggtrade_raw()])

    def fake_connect(url, **kwargs):
        return fake_ws

    monkeypatch.setattr(binance_aggtrade_ws.websockets, "connect", fake_connect)

    stream = binance_aggtrade_ws.BinanceAggTradeStream(symbols=["BTCUSDT"], testnet=True)
    agen = stream.__aiter__()
    event = await asyncio.wait_for(agen.__anext__(), timeout=5)
    await agen.aclose()

    assert event.event_type == EventType.TRADE


def test_parse_aggtrade_message_extracts_symbol_from_stream_name():
    msg = json.loads(_valid_aggtrade_raw(symbol="ethusdt", agg_trade_id=7))
    symbol, payload = binance_aggtrade_ws._parse_aggtrade_message(msg)

    assert symbol == "ETHUSDT"
    assert payload.agg_trade_id == 7


def test_parse_aggtrade_message_returns_none_without_stream_or_data():
    assert binance_aggtrade_ws._parse_aggtrade_message({}) is None
    assert binance_aggtrade_ws._parse_aggtrade_message({"stream": "btcusdt@aggTrade"}) is None


def test_parse_aggtrade_message_decodes_aggressor_side():
    buy_msg = json.loads(_valid_aggtrade_raw(is_buyer_maker=False))
    sell_msg = json.loads(_valid_aggtrade_raw(is_buyer_maker=True))

    _, buy_payload = binance_aggtrade_ws._parse_aggtrade_message(buy_msg)
    _, sell_payload = binance_aggtrade_ws._parse_aggtrade_message(sell_msg)

    assert buy_payload.is_buyer_maker is False
    assert sell_payload.is_buyer_maker is True
