import random

from tradingbot.ingestion.schema import EventType, MarketEvent
from tradingbot.model.evaluation import evaluate_config


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
        price += rng.uniform(-0.3, 0.35)  # slight upward drift with noise
        high = price + abs(rng.uniform(0, 0.2))
        low = price - abs(rng.uniform(0, 0.2))
        events.append(_closed_kline("BTCUSDT", price, (i + 1) * 60_000, high=high, low=low))
    return events


def test_evaluate_config_returns_one_fold_summary_per_split_at_most():
    events = _synthetic_events(n=900)
    result = evaluate_config(
        events, horizon_minutes=5, entry_percentile=80.0, move_threshold_pct=0.002, n_splits=2, min_trades=1
    )
    assert result.horizon_minutes == 5
    assert result.entry_percentile == 80.0
    assert 1 <= result.folds_total <= 2
    assert 0.0 <= result.label_rate <= 1.0
    assert result.folds_won <= result.folds_total
    assert result.mean_profit_factor >= 0.0


def test_evaluate_config_without_regime_filter_still_produces_folds():
    events = _synthetic_events(n=900, seed=1)
    result = evaluate_config(
        events,
        horizon_minutes=5,
        entry_percentile=80.0,
        move_threshold_pct=0.002,
        n_splits=2,
        min_trades=1,
        use_regime_filter=False,
    )
    assert result.use_regime_filter is False
    assert result.folds_total >= 1
