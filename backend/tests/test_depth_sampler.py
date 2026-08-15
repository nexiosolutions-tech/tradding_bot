from __future__ import annotations

from tradingbot.ingestion.depth_sampler import DepthSampler, compute_snapshot_fields
from tradingbot.ingestion.schema import EventType, MarketEvent


def _depth_event(ts: int, best_bid=100.0, best_ask=100.02, seq=1):
    return MarketEvent(
        symbol="BTCUSDT",
        event_type=EventType.DEPTH,
        exchange_ts=ts,
        local_ts=ts,
        sequence_id=seq,
        payload={
            "last_update_id": seq,
            "bids": [[best_bid, 1.5], [best_bid - 0.01, 2.0]],
            "asks": [[best_ask, 1.0], [best_ask + 0.01, 3.0]],
        },
    )


def test_sampler_emits_first_event_in_a_new_bucket():
    sampler = DepthSampler(sample_interval_ms=60_000)
    event = _depth_event(ts=1_000)
    assert sampler.sample(event) is event


def test_sampler_drops_subsequent_events_within_the_same_minute():
    sampler = DepthSampler(sample_interval_ms=60_000)
    sampler.sample(_depth_event(ts=1_000))
    assert sampler.sample(_depth_event(ts=30_000)) is None
    assert sampler.sample(_depth_event(ts=59_999)) is None


def test_sampler_emits_again_once_the_minute_rolls_over():
    sampler = DepthSampler(sample_interval_ms=60_000)
    sampler.sample(_depth_event(ts=1_000))
    second = _depth_event(ts=60_500)
    assert sampler.sample(second) is second


def test_compute_snapshot_fields_derives_spread_and_depth():
    event = _depth_event(ts=1_000, best_bid=100.0, best_ask=100.02)
    fields = compute_snapshot_fields(event)

    assert fields.symbol == "BTCUSDT"
    assert fields.ts == 1_000
    assert fields.best_bid == 100.0
    assert fields.best_ask == 100.02
    assert fields.spread_pct == (100.02 - 100.0) / 100.0
    assert fields.bid_depth_top20 == 1.5 + 2.0
    assert fields.ask_depth_top20 == 1.0 + 3.0


def test_compute_snapshot_fields_imbalance_positive_when_bids_deeper():
    event = MarketEvent(
        symbol="BTCUSDT",
        event_type=EventType.DEPTH,
        exchange_ts=1_000,
        local_ts=1_000,
        sequence_id=1,
        payload={
            "last_update_id": 1,
            "bids": [[100.0, 10.0]],
            "asks": [[100.02, 1.0]],
        },
    )
    fields = compute_snapshot_fields(event)

    assert fields.imbalance > 0
    assert fields.imbalance == (10.0 - 1.0) / (10.0 + 1.0)
