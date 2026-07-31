import pytest

from tradingbot.features.engine import FeatureEngine
from tradingbot.ingestion.schema import EventType, MarketEvent


def _kline_event(symbol, close, volume, is_closed, ts, seq, high=None, low=None):
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
            "high": close if high is None else high,
            "low": close if low is None else low,
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
    assert "ema_fast_dist_pct" in snapshot_eth.features


def _price_walk_features(symbol, prices, scale=1.0):
    engine = FeatureEngine()
    snapshot = None
    for i, price in enumerate(prices):
        snapshot = engine.on_event(_kline_event(symbol, price * scale, 10.0, True, (i + 1) * 60_000, i))
    return snapshot


def test_price_level_features_are_normalized_not_raw_scale():
    """The bug this prevents: ema_fast/macd/bollinger_mid used to be exposed in raw price
    units, so a model trained mostly on one price regime (e.g. BTC ~$60k) would anchor on
    absolute levels that don't transfer to a very different regime (~$20k or ~$100k+)."""
    prices = [100.0 + (i % 5) - 2 for i in range(40)]  # mild oscillation, non-flat
    snapshot_1x = _price_walk_features("BTCUSDT", prices, scale=1.0)
    snapshot_100x = _price_walk_features("BTCUSDT", prices, scale=100.0)  # same relative walk, 100x the price

    assert snapshot_1x is not None and snapshot_100x is not None
    for name in ("ema_fast_dist_pct", "ema_slow_dist_pct", "ema_cross_pct", "macd_pct", "macd_signal_pct", "macd_hist_pct"):
        assert snapshot_1x.features[name] == pytest.approx(snapshot_100x.features[name], abs=1e-9), name

    # No raw-price-scale feature keys should remain.
    for stale_name in ("ema_fast", "ema_slow", "macd", "macd_signal", "macd_hist", "bollinger_mid", "bollinger_upper", "bollinger_lower"):
        assert stale_name not in snapshot_1x.features


def test_atr_pct_absent_during_warmup_then_present_and_normalized():
    engine = FeatureEngine()
    snapshot = None
    for i in range(20):
        # real intrabar range so ATR has something to see, not a flat high=low=close
        snapshot = engine.on_event(
            _kline_event("BTCUSDT", 100.0, 10.0, True, (i + 1) * 60_000, i, high=101.0, low=99.0)
        )
        if i < 13:
            assert "atr_pct" not in snapshot.features
    assert snapshot is not None
    assert "atr_pct" in snapshot.features
    assert snapshot.features["atr_pct"] > 0


def test_cyclical_time_features_are_always_present_and_bounded():
    engine = FeatureEngine()
    # 1970-01-01 06:00:00 UTC (a Thursday) — 6 hours after epoch, no warm-up needed.
    ts = 6 * 3_600_000
    snapshot = engine.on_event(_kline_event("BTCUSDT", 100.0, 10.0, True, ts, 0))
    assert snapshot is not None
    for name in ("hour_sin", "hour_cos", "dow_sin", "dow_cos"):
        assert -1.0 <= snapshot.features[name] <= 1.0
    assert snapshot.features["hour_sin"] == pytest.approx(1.0, abs=1e-9)  # 06:00 = quarter cycle
    assert snapshot.features["hour_cos"] == pytest.approx(0.0, abs=1e-9)


def test_cyclical_time_features_wrap_around_midnight_continuously():
    """23:00 and 01:00 should be close in feature space (2h apart on the clock), not far
    apart the way a raw hour-of-day integer (23 vs 1) would suggest."""
    engine = FeatureEngine()
    late_ts = 23 * 3_600_000
    early_ts = (24 + 1) * 3_600_000
    late = engine.on_event(_kline_event("BTCUSDT", 100.0, 10.0, True, late_ts, 0))
    early = engine.on_event(_kline_event("BTCUSDT", 100.0, 10.0, True, early_ts, 1))
    assert late is not None and early is not None

    import math

    def _dist(a, b):
        return math.hypot(a.features["hour_sin"] - b.features["hour_sin"], a.features["hour_cos"] - b.features["hour_cos"])

    assert _dist(late, early) < 1.0  # close on the cycle, not the ~22h a raw integer implies
