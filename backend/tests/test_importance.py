import random

from tradingbot.ingestion.schema import EventType, MarketEvent
from tradingbot.model.dataset import MODEL_FEATURE_NAMES
from tradingbot.model.importance import compute_feature_importance


def _closed_kline(symbol, close, ts, high=None, low=None):
    return MarketEvent(
        symbol=symbol,
        event_type=EventType.KLINE,
        exchange_ts=ts,
        local_ts=ts,
        sequence_id=ts,
        payload={
            "open_time": ts - 60_000,
            "close_time": ts,
            "interval": "1m",
            "open": close,
            "high": close if high is None else high,
            "low": close if low is None else low,
            "close": close,
            "volume": 100.0,
            "is_closed": True,
        },
    )


def _synthetic_events(n=900, seed=0):
    rng = random.Random(seed)
    events = []
    price = 100.0
    for i in range(n):
        price += rng.uniform(-0.3, 0.35)
        high = price + abs(rng.uniform(0, 0.2))
        low = price - abs(rng.uniform(0, 0.2))
        events.append(_closed_kline("BTCUSDT", price, (i + 1) * 60_000, high=high, low=low))
    return events


def test_compute_feature_importance_covers_every_model_feature_sorted_descending():
    events = _synthetic_events(n=900)
    importances = compute_feature_importance(events, horizon_minutes=5, move_threshold_pct=0.002, n_splits=2)

    assert {imp.name for imp in importances} == set(MODEL_FEATURE_NAMES)
    values = [imp.mean_abs_shap for imp in importances]
    assert values == sorted(values, reverse=True)
    for imp in importances:
        assert imp.mean_abs_shap >= 0.0
        assert -1.0 <= imp.direction_corr <= 1.0
