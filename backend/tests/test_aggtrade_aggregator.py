from __future__ import annotations

from tradingbot.ingestion.aggtrade_aggregator import AggTradeAggregator
from tradingbot.ingestion.schema import EventType, MarketEvent


def _trade_event(ts: int, price=100.0, quantity=1.0, is_buyer_maker=False, symbol="BTCUSDT", seq=1):
    return MarketEvent(
        symbol=symbol,
        event_type=EventType.TRADE,
        exchange_ts=ts,
        local_ts=ts,
        sequence_id=seq,
        payload={
            "agg_trade_id": seq,
            "price": price,
            "quantity": quantity,
            "first_trade_id": seq,
            "last_trade_id": seq,
            "trade_time": ts,
            "is_buyer_maker": is_buyer_maker,
        },
    )


def test_first_trade_in_a_bucket_does_not_emit_yet():
    aggregator = AggTradeAggregator(bucket_interval_ms=60_000)
    assert aggregator.add(_trade_event(ts=1_000)) is None


def test_trades_within_the_same_minute_accumulate_without_emitting():
    aggregator = AggTradeAggregator(bucket_interval_ms=60_000)
    aggregator.add(_trade_event(ts=1_000, quantity=1.0, is_buyer_maker=False))
    assert aggregator.add(_trade_event(ts=30_000, quantity=2.0, is_buyer_maker=True)) is None
    assert aggregator.add(_trade_event(ts=59_999, quantity=3.0, is_buyer_maker=False)) is None


def test_bucket_emitted_only_once_the_minute_rolls_over_with_correct_totals():
    aggregator = AggTradeAggregator(bucket_interval_ms=60_000)
    aggregator.add(_trade_event(ts=1_000, price=100.0, quantity=1.0, is_buyer_maker=False))  # buy
    aggregator.add(_trade_event(ts=2_000, price=100.0, quantity=2.0, is_buyer_maker=True))  # sell
    aggregator.add(_trade_event(ts=3_000, price=100.0, quantity=1.5, is_buyer_maker=False))  # buy

    bucket = aggregator.add(_trade_event(ts=60_500, quantity=1.0, is_buyer_maker=False))

    assert bucket is not None
    assert bucket.ts == 0
    assert bucket.buy_volume == 1.0 + 1.5
    assert bucket.sell_volume == 2.0
    assert bucket.buy_count == 2
    assert bucket.sell_count == 1


def test_vwap_is_notional_weighted_across_the_bucket():
    aggregator = AggTradeAggregator(bucket_interval_ms=60_000)
    aggregator.add(_trade_event(ts=1_000, price=100.0, quantity=1.0, is_buyer_maker=False))
    aggregator.add(_trade_event(ts=2_000, price=200.0, quantity=1.0, is_buyer_maker=True))

    bucket = aggregator.add(_trade_event(ts=60_500, quantity=1.0, is_buyer_maker=False))

    assert bucket.vwap == (100.0 * 1.0 + 200.0 * 1.0) / 2.0


def test_bucket_ts_is_the_bucket_start_not_the_last_trade_ts():
    aggregator = AggTradeAggregator(bucket_interval_ms=60_000)
    aggregator.add(_trade_event(ts=65_000, is_buyer_maker=False))
    bucket = aggregator.add(_trade_event(ts=125_000, is_buyer_maker=False))

    assert bucket.ts == 60_000


def test_symbols_are_tracked_independently():
    aggregator = AggTradeAggregator(bucket_interval_ms=60_000)
    aggregator.add(_trade_event(ts=1_000, symbol="BTCUSDT", quantity=1.0, is_buyer_maker=False))
    aggregator.add(_trade_event(ts=1_000, symbol="ETHUSDT", quantity=5.0, is_buyer_maker=False))

    btc_bucket = aggregator.add(_trade_event(ts=60_500, symbol="BTCUSDT", quantity=1.0, is_buyer_maker=False))
    eth_bucket = aggregator.add(_trade_event(ts=60_500, symbol="ETHUSDT", quantity=1.0, is_buyer_maker=False))

    assert btc_bucket.symbol == "BTCUSDT"
    assert btc_bucket.buy_volume == 1.0
    assert eth_bucket.symbol == "ETHUSDT"
    assert eth_bucket.buy_volume == 5.0
