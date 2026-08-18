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


def test_trend_regime_pct_is_always_present_no_warmup():
    """Unlike RSI/Bollinger, EMA (and therefore trend_regime_pct) has no warm-up gate —
    it should be available from the very first candle."""
    engine = FeatureEngine()
    snapshot = engine.on_event(_kline_event("BTCUSDT", 100.0, 10.0, True, 60_000, 0))
    assert snapshot is not None
    assert "trend_regime_pct" in snapshot.features


def test_trend_regime_pct_is_positive_in_a_sustained_uptrend():
    engine = FeatureEngine()
    snapshot = None
    price = 100.0
    for i in range(300):  # well past the 240-candle trend EMA window
        price += 0.5  # steady climb
        snapshot = engine.on_event(_kline_event("BTCUSDT", price, 10.0, True, (i + 1) * 60_000, i))
    assert snapshot.features["trend_regime_pct"] > 0


def test_trend_regime_pct_is_negative_in_a_sustained_downtrend():
    engine = FeatureEngine()
    snapshot = None
    price = 200.0
    for i in range(300):
        price -= 0.5  # steady decline
        snapshot = engine.on_event(_kline_event("BTCUSDT", price, 10.0, True, (i + 1) * 60_000, i))
    assert snapshot.features["trend_regime_pct"] < 0


def test_rsi_and_bollinger_5m_absent_during_warmup_then_present():
    """rsi_5m needs 14 completed 5-minute candles (70 bars), bollinger_percent_b_5m needs
    20 (100 bars) — RSI warms up faster, so it's checked separately. Uses a non-periodic
    random walk (not a fixed-period oscillation) because a period that divides evenly into
    the bucket size makes every bucket close on the same phase, giving Bollinger bands zero
    width — percent_b would then stay undefined forever, masking the warm-up transition."""
    import random

    engine = FeatureEngine()
    rng = random.Random(42)
    price = 100.0
    snapshot = None
    for i in range(110):
        price += rng.uniform(-0.5, 0.5)
        snapshot = engine.on_event(_kline_event("BTCUSDT", price, 10.0, True, (i + 1) * 60_000, i))
        if i < 65:
            assert "rsi_5m" not in snapshot.features
        if i < 90:
            assert "bollinger_percent_b_5m" not in snapshot.features
    assert "rsi_5m" in snapshot.features
    assert "bollinger_percent_b_5m" in snapshot.features


def test_rsi_and_bollinger_15m_absent_during_warmup_then_present():
    """rsi_15m needs 14 completed 15-minute candles (210 bars), bollinger_percent_b_15m
    needs 20 (300 bars) — RSI warms up faster, so it's checked separately. Same non-periodic
    random walk as the 5m version, for the same reason (avoids bucket-phase aliasing)."""
    import random

    engine = FeatureEngine()
    rng = random.Random(42)
    price = 100.0
    snapshot = None
    for i in range(320):
        price += rng.uniform(-0.5, 0.5)
        snapshot = engine.on_event(_kline_event("BTCUSDT", price, 10.0, True, (i + 1) * 60_000, i))
        if i < 195:
            assert "rsi_15m" not in snapshot.features
        if i < 280:
            assert "bollinger_percent_b_15m" not in snapshot.features
    assert "rsi_15m" in snapshot.features
    assert "bollinger_percent_b_15m" in snapshot.features


def test_multi_timeframe_5m_feature_is_constant_within_a_bucket():
    """Anti-leakage invariant (spec 03): a still-forming 5-minute bucket must never leak
    into the features exposed mid-bucket — the value can only reflect the last fully
    closed bucket, so every one-minute candle inside the same 5-minute bucket must report
    the same reading, changing only once the bucket rolls over."""
    import random

    engine = FeatureEngine()
    rng = random.Random(42)
    price = 100.0
    snapshots = []
    for i in range(150):  # comfortably past bollinger_percent_b_5m's 100-bar warm-up
        price += rng.uniform(-0.5, 0.5)  # non-periodic, so buckets don't coincidentally repeat
        snapshots.append(engine.on_event(_kline_event("BTCUSDT", price, 10.0, True, (i + 1) * 60_000, i)))

    # snapshots[i] has ts=(i+1)*60_000; the 5-minute bucket boundaries fall where (i+1) is a
    # multiple of 5, so indices 119..123 (ts 7,200,000..7,440,000) are the 5 candles of one
    # clean, fully-contained bucket.
    bucket_values = [s.features["bollinger_percent_b_5m"] for s in snapshots[119:124]]
    assert len(set(bucket_values)) == 1, "value must not change within the same 5-minute bucket"

    later_bucket_values = {snapshots[i].features["bollinger_percent_b_5m"] for i in (105, 115, 125, 135, 145)}
    assert len(later_bucket_values) > 1, "the feature must actually update across buckets, not just once"


def test_reference_symbol_events_never_produce_their_own_snapshot():
    engine = FeatureEngine(reference_symbol="ETHUSDT")
    snapshot = engine.on_event(_kline_event("ETHUSDT", 3000.0, 10.0, True, 60_000, 0))
    assert snapshot is None


def test_cross_asset_feature_absent_without_reference_symbol_configured():
    """Default behavior (no reference_symbol) must stay exactly as before — the vast
    majority of callers (train_model.py, sweep_thresholds.py, coin discovery, risk
    profiles) never configure one."""
    engine = FeatureEngine()
    snapshot = None
    for i in range(20):
        snapshot = engine.on_event(_kline_event("BTCUSDT", 100.0 + i, 10.0, True, (i + 1) * 60_000, i))
    assert "eth_relative_strength_pct" not in snapshot.features


def test_cross_asset_feature_absent_until_both_symbols_warmed_up():
    engine = FeatureEngine(reference_symbol="ETHUSDT")
    snapshot = None
    # 15 candles of BTC alone -- own_return warms up, but reference_return_value is still
    # None (no ETHUSDT event has arrived yet), so the feature must not appear.
    for i in range(16):
        snapshot = engine.on_event(_kline_event("BTCUSDT", 100.0 + i, 10.0, True, (i + 1) * 60_000, i))
    assert "eth_relative_strength_pct" not in snapshot.features


def test_cross_asset_feature_appears_once_both_returns_are_warmed_up():
    engine = FeatureEngine(reference_symbol="ETHUSDT")
    ts = 0
    snapshot = None
    for i in range(16):
        ts += 60_000
        engine.on_event(_kline_event("ETHUSDT", 3000.0 + i, 10.0, True, ts, i))
        ts += 60_000
        snapshot = engine.on_event(_kline_event("BTCUSDT", 100.0 + i, 10.0, True, ts, i))
    assert "eth_relative_strength_pct" in snapshot.features


def test_cross_asset_feature_value_is_btc_return_minus_eth_return():
    engine = FeatureEngine(reference_symbol="ETHUSDT")
    ts = 0
    # 15 flat candles for both -- warms up both windows at zero return each.
    for i in range(15):
        ts += 60_000
        engine.on_event(_kline_event("ETHUSDT", 3000.0, 10.0, True, ts, i))
        ts += 60_000
        engine.on_event(_kline_event("BTCUSDT", 100.0, 10.0, True, ts, i))

    # 16th round: BTC +10% from 100, ETH +2% from 3000.
    ts += 60_000
    engine.on_event(_kline_event("ETHUSDT", 3060.0, 10.0, True, ts, 15))
    ts += 60_000
    snapshot = engine.on_event(_kline_event("BTCUSDT", 110.0, 10.0, True, ts, 15))

    btc_return = (110.0 - 100.0) / 100.0
    eth_return = (3060.0 - 3000.0) / 3000.0
    assert snapshot.features["eth_relative_strength_pct"] == pytest.approx(btc_return - eth_return)
