from tradingbot.ingestion.schema import EventType, MarketEvent
from tradingbot.model.dataset import FEATURE_NAMES, TargetConfig, build_dataset

WARMUP_BARS = 30  # enough for RSI(14)/Bollinger(20)/MACD to leave warm-up
BAR_MS = 60_000


def _kline(symbol, close, high, ts, low=None, volume=100.0):
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
            "low": close if low is None else low,
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


def test_label_is_zero_when_stop_loss_hit_before_take_profit():
    """The bug this closes: checking only future highs would label this row an
    'opportunity' (the target is eventually reached), even though the stop-loss (spec
    05/06's structural guarantee) would have closed the trade out first."""
    events = _warmup_events()
    entry_ts = BAR_MS * (WARMUP_BARS + 1)
    events.append(_kline("BTCUSDT", 100.0, 100.0, entry_ts))  # row under test
    # Candle 1: dips through the stop-loss (1.5%) first...
    events.append(_kline("BTCUSDT", 98.0, 100.0, BAR_MS * (WARMUP_BARS + 2), low=98.0))
    # ...candle 2: "eventually" reaches the take-profit target too, but too late.
    events.append(_kline("BTCUSDT", 100.0, 105.0, BAR_MS * (WARMUP_BARS + 3)))

    target = TargetConfig(horizon_minutes=2, candle_minutes=1, move_threshold_pct=0.03, stop_loss_pct=0.015)
    rows = build_dataset(events, target)

    row_at_entry = next(r for r in rows if r.knowledge_ts == entry_ts)
    assert row_at_entry.label == 0


def test_label_is_one_when_take_profit_hit_before_stop_loss():
    events = _warmup_events()
    entry_ts = BAR_MS * (WARMUP_BARS + 1)
    events.append(_kline("BTCUSDT", 100.0, 100.0, entry_ts))  # row under test
    # Candle 1: take-profit (3%) touched first...
    events.append(_kline("BTCUSDT", 100.0, 103.5, BAR_MS * (WARMUP_BARS + 2)))
    # ...candle 2: price later drops through what would've been the stop-loss, too late.
    events.append(_kline("BTCUSDT", 98.0, 100.0, BAR_MS * (WARMUP_BARS + 3), low=98.0))

    target = TargetConfig(horizon_minutes=2, candle_minutes=1, move_threshold_pct=0.03, stop_loss_pct=0.015)
    rows = build_dataset(events, target)

    row_at_entry = next(r for r in rows if r.knowledge_ts == entry_ts)
    assert row_at_entry.label == 1


def test_move_threshold_atr_multiple_defaults_to_none_preserving_fixed_threshold():
    assert TargetConfig().move_threshold_atr_multiple is None


def test_label_with_atr_scaled_threshold_uses_entry_atr_pct():
    """2026-08-02: take-profit distance becomes move_threshold_atr_multiple * atr_pct at
    the entry candle instead of a fixed move_threshold_pct. Reads the entry row's own
    atr_pct back from a probe build (rather than hardcoding the ATR formula's output) so
    this test doesn't couple to indicator internals — only to the scaling contract."""
    events = _warmup_events()
    entry_ts = BAR_MS * (WARMUP_BARS + 1)
    events.append(_kline("BTCUSDT", 100.0, 100.0, entry_ts))

    # atr_pct is causal (only depends on data up to and including the entry candle), so a
    # throwaway trailing event is enough to make build_dataset include the entry row here.
    probe_rows = build_dataset(
        events + [_kline("BTCUSDT", 100.0, 100.0, BAR_MS * (WARMUP_BARS + 2))],
        TargetConfig(horizon_minutes=1, candle_minutes=1),
    )
    entry_row = next(r for r in probe_rows if r.knowledge_ts == entry_ts)
    atr_pct = entry_row.features["atr_pct"]
    assert atr_pct > 0  # sanity: the oscillating fixture must produce real volatility

    multiple = 10.0
    threshold_price = 100.0 * (1 + multiple * atr_pct)
    target = TargetConfig(horizon_minutes=1, candle_minutes=1, move_threshold_atr_multiple=multiple)

    events_hit = events + [_kline("BTCUSDT", 100.0, threshold_price + 0.01, BAR_MS * (WARMUP_BARS + 2))]
    rows_hit = build_dataset(events_hit, target)
    assert next(r for r in rows_hit if r.knowledge_ts == entry_ts).label == 1

    events_miss = events + [_kline("BTCUSDT", 100.0, threshold_price - 0.01, BAR_MS * (WARMUP_BARS + 2))]
    rows_miss = build_dataset(events_miss, target)
    assert next(r for r in rows_miss if r.knowledge_ts == entry_ts).label == 0


def test_atr_scaled_threshold_ignores_fixed_move_threshold_pct():
    """When move_threshold_atr_multiple is set, the fixed move_threshold_pct must be fully
    ignored, not blended with it — otherwise the two configs silently interact."""
    events = _warmup_events()
    entry_ts = BAR_MS * (WARMUP_BARS + 1)
    events.append(_kline("BTCUSDT", 100.0, 100.0, entry_ts))

    probe_rows = build_dataset(
        events + [_kline("BTCUSDT", 100.0, 100.0, BAR_MS * (WARMUP_BARS + 2))],
        TargetConfig(horizon_minutes=1, candle_minutes=1),
    )
    atr_pct = next(r for r in probe_rows if r.knowledge_ts == entry_ts).features["atr_pct"]
    multiple = 10.0
    threshold_price = 100.0 * (1 + multiple * atr_pct)

    # A huge fixed move_threshold_pct (99%) would never be hit by this candle — if it were
    # still in play, the label would be 0 regardless of the ATR-scaled distance.
    target = TargetConfig(
        horizon_minutes=1, candle_minutes=1, move_threshold_pct=0.99, move_threshold_atr_multiple=multiple
    )
    events_hit = events + [_kline("BTCUSDT", 100.0, threshold_price + 0.01, BAR_MS * (WARMUP_BARS + 2))]
    rows_hit = build_dataset(events_hit, target)
    assert next(r for r in rows_hit if r.knowledge_ts == entry_ts).label == 1


def test_label_is_zero_when_both_barriers_touched_in_same_candle():
    """Can't tell which barrier came first within a single OHLC bar — must assume the
    worse case (stop-loss), never the optimistic one."""
    events = _warmup_events()
    entry_ts = BAR_MS * (WARMUP_BARS + 1)
    events.append(_kline("BTCUSDT", 100.0, 100.0, entry_ts))  # row under test
    events.append(_kline("BTCUSDT", 100.0, 105.0, BAR_MS * (WARMUP_BARS + 2), low=98.0))

    target = TargetConfig(horizon_minutes=1, candle_minutes=1, move_threshold_pct=0.03, stop_loss_pct=0.015)
    rows = build_dataset(events, target)

    row_at_entry = next(r for r in rows if r.knowledge_ts == entry_ts)
    assert row_at_entry.label == 0
