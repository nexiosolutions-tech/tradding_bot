from sqlalchemy import select

from tradingbot.persistence.db import get_session_factory
from tradingbot.persistence.models import (
    AggTradeBucket,
    AggTradeRateSample,
    CircuitBreakerEvent,
    EngineEvent,
    OrderBookSnapshot,
    OrderRecord,
    TradeRecord,
)
from tradingbot.persistence.repository import (
    acknowledge_circuit_breaker,
    count_agg_trade_buckets_in_range,
    count_order_book_snapshots_in_range,
    get_order,
    latest_unacknowledged_circuit_breaker,
    record_circuit_breaker_event,
    record_engine_event,
    record_order_book_snapshot,
    record_trade,
    list_aggtrade_rate_samples,
    recent_engine_events,
    record_aggtrade_rate_sample,
    trades_in_range,
    upsert_agg_trade_bucket,
    upsert_order,
)


def _session(tmp_path):
    factory = get_session_factory(f"sqlite:///{tmp_path}/test.db")
    return factory()


def _order(client_order_id="co-1", status="NEW", filled_qty=0.0):
    return OrderRecord(
        client_order_id=client_order_id,
        symbol="BTCUSDT",
        side="buy",
        purpose="entry",
        requested_qty=1.0,
        requested_price=100.0,
        status=status,
        filled_qty=filled_qty,
        avg_fill_price=None,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        raw_response=None,
    )


def test_upsert_order_inserts_then_updates_same_row(tmp_path):
    session = _session(tmp_path)
    upsert_order(session, _order())
    upsert_order(session, _order(status="FILLED", filled_qty=1.0))

    stored = get_order(session, "co-1")
    assert stored.status == "FILLED"
    assert stored.filled_qty == 1.0


def test_trades_in_range_filters_by_exit_ts(tmp_path):
    session = _session(tmp_path)
    for i in range(5):
        record_trade(
            session,
            TradeRecord(
                symbol="BTCUSDT",
                entry_order_id=f"e{i}",
                exit_order_id=f"x{i}",
                entry_ts=i * 1000,
                exit_ts=i * 1000 + 500,
                entry_price=100.0,
                exit_price=101.0,
                size=1.0,
                pnl=1.0,
                fees_paid=0.1,
                exit_reason="signal_exit",
                strategy_version="v1",
            ),
        )

    result = trades_in_range(session, start_ts=1500, end_ts=3500)
    assert {t.exit_order_id for t in result} == {"x1", "x2", "x3"}


def test_circuit_breaker_ack_flow(tmp_path):
    session = _session(tmp_path)
    event = record_circuit_breaker_event(
        session,
        CircuitBreakerEvent(
            triggered_at=1000,
            equity_at_trigger=900.0,
            peak_equity=1000.0,
            drawdown_pct=0.10,
        ),
    )

    pending = latest_unacknowledged_circuit_breaker(session)
    assert pending is not None
    assert pending.id == event.id

    acknowledge_circuit_breaker(session, event.id, ts=2000, acknowledged_by="brian")
    assert latest_unacknowledged_circuit_breaker(session) is None


def test_engine_events_ordered_most_recent_first(tmp_path):
    session = _session(tmp_path)
    for i in range(3):
        record_engine_event(
            session,
            EngineEvent(ts=i, from_state="ANALISANDO", to_state="POSICAO_ABERTA", reason="signal"),
        )

    events = recent_engine_events(session, limit=2)
    assert [e.ts for e in events] == [2, 1]


def test_order_book_snapshot_round_trip(tmp_path):
    session = _session(tmp_path)
    record_order_book_snapshot(
        session,
        OrderBookSnapshot(
            symbol="BTCUSDT",
            ts=1_000,
            best_bid=100.0,
            best_ask=100.02,
            spread_pct=0.0002,
            bid_depth_top20=15.0,
            ask_depth_top20=12.0,
            imbalance=0.11,
            raw_bids=[[100.0, 1.5]],
            raw_asks=[[100.02, 1.0]],
        ),
    )

    stored = session.scalars(select(OrderBookSnapshot)).one()
    assert stored.symbol == "BTCUSDT"
    assert stored.ts == 1_000
    assert stored.raw_bids == [[100.0, 1.5]]


def _agg_bucket(symbol="BTCUSDT", ts=1_000, buy_volume=1.0, sell_volume=2.0, buy_count=1, sell_count=1, notional=300.0):
    total = buy_volume + sell_volume
    return AggTradeBucket(
        symbol=symbol,
        ts=ts,
        buy_volume=buy_volume,
        sell_volume=sell_volume,
        buy_count=buy_count,
        sell_count=sell_count,
        vwap=notional / total if total else 0.0,
        notional=notional,
    )


def test_upsert_agg_trade_bucket_inserts_when_new(tmp_path):
    session = _session(tmp_path)
    upsert_agg_trade_bucket(session, _agg_bucket())

    stored = session.scalars(select(AggTradeBucket)).one()
    assert stored.symbol == "BTCUSDT"
    assert stored.ts == 1_000
    assert stored.buy_volume == 1.0
    assert stored.sell_volume == 2.0


def test_upsert_agg_trade_bucket_merges_into_existing_symbol_and_ts(tmp_path):
    session = _session(tmp_path)
    upsert_agg_trade_bucket(session, _agg_bucket(buy_volume=1.0, sell_volume=2.0, notional=300.0))
    upsert_agg_trade_bucket(session, _agg_bucket(buy_volume=0.5, sell_volume=0.0, buy_count=1, sell_count=0, notional=51.0))

    rows = session.scalars(select(AggTradeBucket)).all()
    assert len(rows) == 1
    merged = rows[0]
    assert merged.buy_volume == 1.5
    assert merged.sell_volume == 2.0
    assert merged.buy_count == 2
    assert merged.sell_count == 1
    assert merged.notional == 351.0
    assert merged.vwap == 351.0 / 3.5


def test_upsert_agg_trade_bucket_keeps_different_ts_or_symbol_separate(tmp_path):
    session = _session(tmp_path)
    upsert_agg_trade_bucket(session, _agg_bucket(symbol="BTCUSDT", ts=1_000))
    upsert_agg_trade_bucket(session, _agg_bucket(symbol="BTCUSDT", ts=2_000))
    upsert_agg_trade_bucket(session, _agg_bucket(symbol="ETHUSDT", ts=1_000))

    rows = session.scalars(select(AggTradeBucket)).all()
    assert len(rows) == 3


def test_count_order_book_snapshots_in_range(tmp_path):
    session = _session(tmp_path)
    for ts in (900, 1_000, 1_500, 2_100):
        record_order_book_snapshot(
            session,
            OrderBookSnapshot(
                symbol="BTCUSDT",
                ts=ts,
                environment="mainnet",
                best_bid=100.0,
                best_ask=100.02,
                spread_pct=0.0002,
                bid_depth_top20=1.0,
                ask_depth_top20=1.0,
                imbalance=0.0,
                raw_bids=[],
                raw_asks=[],
            ),
        )

    assert count_order_book_snapshots_in_range(session, 1_000, 2_000, environment="mainnet") == 2
    assert count_order_book_snapshots_in_range(session, 1_000, 2_000, environment="testnet") == 0


def test_count_agg_trade_buckets_in_range(tmp_path):
    session = _session(tmp_path)
    for ts in (900, 1_000, 1_500, 2_100):
        upsert_agg_trade_bucket(session, _agg_bucket(ts=ts))

    assert count_agg_trade_buckets_in_range(session, 1_000, 2_000, environment="testnet") == 2
    assert count_agg_trade_buckets_in_range(session, 1_000, 2_000, environment="mainnet") == 0


def test_upsert_agg_trade_bucket_recovers_from_concurrent_insert_race(tmp_path, monkeypatch):
    """Reproduces the production incident of 2026-08-18: a Railway redeploy briefly runs
    the old and new instance of the same capture service side by side, and both raced to
    insert the same (symbol, ts) bucket -- the loser's plain INSERT crashed on an
    uncaught IntegrityError. Simulates the race by landing a conflicting row, from a
    second session, in the middle of the first upsert's own commit."""
    from tradingbot.persistence.repository import upsert_agg_trade_bucket as _upsert

    session = _session(tmp_path)
    db_url = session.get_bind().url

    from sqlalchemy.orm import Session as _Session

    original_commit = _Session.commit
    call_count = {"n": 0}

    def _racy_commit(self, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # A concurrent instance's upsert lands first, from an entirely separate session.
            from tradingbot.persistence.db import get_session_factory

            other_session = get_session_factory(str(db_url))()
            other_session.add(_agg_bucket(buy_volume=10.0, sell_volume=0.0, notional=1000.0))
            original_commit(other_session)
            other_session.close()
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(_Session, "commit", _racy_commit)

    _upsert(session, _agg_bucket(buy_volume=1.0, sell_volume=2.0, notional=300.0))  # must not raise

    rows = session.scalars(select(AggTradeBucket)).all()
    assert len(rows) == 1
    assert rows[0].buy_volume == 11.0  # 10.0 (raced-in winner) + 1.0 (merged after recovery)
    assert rows[0].sell_volume == 2.0
    assert rows[0].notional == 1300.0


def test_record_and_list_aggtrade_rate_samples(tmp_path):
    session = _session(tmp_path)
    record_aggtrade_rate_sample(
        session,
        AggTradeRateSample(symbol="BTCUSDT", ts=1_000, trades_per_second=12.5, span_ms=80_000, latency_ms=210.0, used_weight_1m=4),
    )
    record_aggtrade_rate_sample(
        session,
        AggTradeRateSample(symbol="BTCUSDT", ts=2_000, trades_per_second=30.0, span_ms=33_333, latency_ms=190.0, used_weight_1m=8),
    )
    record_aggtrade_rate_sample(
        session,
        AggTradeRateSample(symbol="ETHUSDT", ts=1_500, trades_per_second=5.0, span_ms=200_000, latency_ms=200.0, used_weight_1m=6),
    )

    samples = list_aggtrade_rate_samples(session, symbol="BTCUSDT")

    assert [s.ts for s in samples] == [1_000, 2_000]
    assert samples[1].trades_per_second == 30.0
    assert samples[1].used_weight_1m == 8
