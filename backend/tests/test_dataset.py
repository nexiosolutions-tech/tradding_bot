from tradingbot.ingestion.schema import EventType, MarketEvent
from tradingbot.model.dataset import FEATURE_NAMES, TargetConfig, build_dataset

WARMUP_BARS = 30  # enough for RSI(14)/Bollinger(20)/MACD to leave warm-up
BAR_MS = 60_000


def _kline(symbol, close, high, ts, volume=100.0):
    return MarketEvent(
        symbol=symbol,
        event_type=EventType.KLINE,
        exchange_ts=ts,
        local_ts=ts,
        sequence_id=ts,
        payload={
            "open_time": ts - BAR_MS,
            "close_time": ts,
            "interval": "1m",
            "open": close,
            "high": high,
            "low": close,
            "close": close,
            "volume": volume,
            "is_closed": True,
        },
    )


def _warmup_events(symbol="BTCUSDT", base=100.0, amplitude=0.5, n=WARMUP_BARS):
    """Mild oscillation, not a flat line — a constant price gives Bollinger bands zero
    width, which makes percent_b permanently undefined (division by zero guard)."""
    events = []
    for i in range(n):
        price = base + amplitude * (1 if i % 2 == 0 else -1)
        ts = BAR_MS * (i + 1)
        events.append(_kline(symbol, price, price, ts))
    return events


def test_dataset_skips_indicator_warmup_period():
    events = _warmup_events()
    rows = build_dataset(events, TargetConfig(horizon_minutes=1, candle_minutes=1))
    assert 0 < len(rows) < len(events)
    for row in rows:
        assert set(row.features) == set(FEATURE_NAMES)


def test_label_is_one_when_future_high_exceeds_threshold():
    events = _warmup_events()
    entry_ts = BAR_MS * (WARMUP_BARS + 1)
    events.append(_kline("BTCUSDT", 100.0, 100.0, entry_ts))  # row under test
    events.append(_kline("BTCUSDT", 100.0, 100.0, BAR_MS * (WARMUP_BARS + 2)))
    events.append(_kline("BTCUSDT", 100.0, 105.0, BAR_MS * (WARMUP_BARS + 3)))  # +5% high

    target = TargetConfig(horizon_minutes=2, candle_minutes=1, move_threshold_pct=0.03)
    rows = build_dataset(events, target)

    row_at_entry = next(r for r in rows if r.knowledge_ts == entry_ts)
    assert row_at_entry.label == 1


def test_label_is_zero_when_future_move_stays_below_threshold():
    events = _warmup_events()
    entry_ts = BAR_MS * (WARMUP_BARS + 1)
    events.append(_kline("BTCUSDT", 100.0, 100.0, entry_ts))  # row under test
    events.append(_kline("BTCUSDT", 100.0, 100.5, BAR_MS * (WARMUP_BARS + 2)))
    events.append(_kline("BTCUSDT", 100.0, 100.5, BAR_MS * (WARMUP_BARS + 3)))

    target = TargetConfig(horizon_minutes=2, candle_minutes=1, move_threshold_pct=0.03)
    rows = build_dataset(events, target)

    row_at_entry = next(r for r in rows if r.knowledge_ts == entry_ts)
    assert row_at_entry.label == 0


def test_last_rows_without_full_future_horizon_are_excluded():
    events = _warmup_events(n=WARMUP_BARS + 10)
    target = TargetConfig(horizon_minutes=5, candle_minutes=1)
    rows = build_dataset(events, target)
    last_usable_ts = events[-1 - target.horizon_bars].exchange_ts
    assert rows  # sanity: the fixture must actually produce usable rows
    assert all(r.knowledge_ts <= last_usable_ts for r in rows)
