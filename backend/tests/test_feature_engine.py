from tradingbot.features.engine import FeatureEngine
from tradingbot.ingestion.schema import EventType, MarketEvent


def _kline_event(symbol, close, volume, is_closed, ts, seq):
    return MarketEvent(
        symbol=symbol,
        event_type=EventType.KLINE,
        exchange_ts=ts,
        local_ts=ts,
        sequence_id=seq,
        payload={
            "open_time": ts - 60_000,
            "close_time": ts,
            "interval": "1m",
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": volume,
            "is_closed": is_closed,
        },
    )


def test_no_snapshot_emitted_for_open_candle():
    engine = FeatureEngine()
    event = _kline_event("BTCUSDT", 100.0, 10.0, is_closed=False, ts=1000, seq=1)
    assert engine.on_event(event) is None


def test_snapshot_emitted_only_on_close_with_matching_knowledge_ts():
    engine = FeatureEngine()
    event = _kline_event("BTCUSDT", 100.0, 10.0, is_closed=True, ts=60_000, seq=1)
    snapshot = engine.on_event(event)
    assert snapshot is not None
    assert snapshot.knowledge_ts == event.exchange_ts
    assert snapshot.close == 100.0


def test_feature_state_is_isolated_per_symbol():
    engine = FeatureEngine()
    for i in range(5):
        engine.on_event(_kline_event("BTCUSDT", 100.0 + i, 10.0, True, (i + 1) * 60_000, i))
    snapshot_eth = engine.on_event(_kline_event("ETHUSDT", 5000.0, 10.0, True, 60_000, 100))
    assert snapshot_eth.close == 5000.0
    assert "ema_fast" in snapshot_eth.features
