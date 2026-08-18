"""Tests for the additive-only schema patch (persistence/db.py) that backfills the
`environment` column onto order_book_snapshots/agg_trade_buckets — the one case in this
project where a column was added after the table already held real production rows, and
there's no migration framework (Alembic or otherwise) to lean on."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, select, text

from tradingbot.persistence.db import _ensure_capture_environment_column, get_session_factory
from tradingbot.persistence.models import AggTradeBucket, OrderBookSnapshot


def test_get_session_factory_defaults_environment_to_testnet(tmp_path):
    factory = get_session_factory(f"sqlite:///{tmp_path}/test.db")
    session = factory()
    session.add(
        OrderBookSnapshot(
            symbol="BTCUSDT",
            ts=1_000,
            best_bid=100.0,
            best_ask=100.02,
            spread_pct=0.0002,
            bid_depth_top20=1.0,
            ask_depth_top20=1.0,
            imbalance=0.0,
            raw_bids=[],
            raw_asks=[],
        )
    )
    session.commit()

    stored = session.scalars(select(OrderBookSnapshot)).one()
    assert stored.environment == "testnet"


def test_ensure_capture_environment_column_backfills_existing_rows_without_it(tmp_path):
    # Simulate the real pre-migration production schema: create the table by hand, without
    # the `environment` column, and insert a row the way the old code would have.
    db_path = tmp_path / "pre-migration.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE order_book_snapshots ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, symbol VARCHAR, ts BIGINT, "
                "best_bid FLOAT, best_ask FLOAT, spread_pct FLOAT, bid_depth_top20 FLOAT, "
                "ask_depth_top20 FLOAT, imbalance FLOAT, raw_bids JSON, raw_asks JSON)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO order_book_snapshots "
                "(symbol, ts, best_bid, best_ask, spread_pct, bid_depth_top20, ask_depth_top20, "
                "imbalance, raw_bids, raw_asks) VALUES "
                "('BTCUSDT', 500, 100.0, 100.02, 0.0002, 1.0, 1.0, 0.0, '[]', '[]')"
            )
        )
    engine.dispose()

    factory = get_session_factory(f"sqlite:///{db_path}")
    session = factory()
    pre_existing = session.scalars(select(OrderBookSnapshot).where(OrderBookSnapshot.ts == 500)).one()

    assert pre_existing.environment == "testnet"


def test_ensure_capture_environment_column_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    from tradingbot.persistence.models import Base

    Base.metadata.create_all(engine)

    _ensure_capture_environment_column(engine)
    _ensure_capture_environment_column(engine)  # must not raise (duplicate column)


def test_ensure_capture_environment_column_skips_tables_that_dont_exist_yet(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/empty.db")
    _ensure_capture_environment_column(engine)  # must not raise on a database with no tables


def test_agg_trade_bucket_defaults_environment_to_testnet(tmp_path):
    factory = get_session_factory(f"sqlite:///{tmp_path}/test.db")
    session = factory()
    session.add(
        AggTradeBucket(
            symbol="BTCUSDT",
            ts=1_000,
            buy_volume=1.0,
            sell_volume=1.0,
            buy_count=1,
            sell_count=1,
            vwap=100.0,
            notional=200.0,
        )
    )
    session.commit()

    stored = session.scalars(select(AggTradeBucket)).one()
    assert stored.environment == "testnet"


def test_ensure_capture_environment_column_swallows_race_when_column_already_landed(tmp_path, monkeypatch):
    """Two services can call get_session_factory within seconds of each other on a shared
    redeploy — simulates the losing side of that race: its ALTER fails because a
    concurrent process's ALTER already landed the column."""
    from sqlalchemy import create_engine
    from sqlalchemy.engine.base import Connection
    from sqlalchemy.exc import OperationalError

    engine = create_engine(f"sqlite:///{tmp_path}/race.db")
    from tradingbot.persistence.models import Base

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE order_book_snapshots DROP COLUMN environment"))
        conn.execute(text("ALTER TABLE agg_trade_buckets DROP COLUMN environment"))

    original_execute = Connection.execute
    call_count = {"n": 0}

    def _racy_execute(self, statement, *args, **kwargs):
        if "ALTER TABLE" in str(statement) and "ADD COLUMN" in str(statement):
            call_count["n"] += 1
            # Someone else's ALTER "wins" the race and lands first.
            with engine.connect() as other_conn:
                original_execute(other_conn, text(str(statement)))
                other_conn.commit()
            raise OperationalError(str(statement), {}, Exception("duplicate column name: environment"))
        return original_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(Connection, "execute", _racy_execute)

    _ensure_capture_environment_column(engine)  # must not raise

    assert call_count["n"] >= 1
    inspector = inspect(engine)
    assert "environment" in {c["name"] for c in inspector.get_columns("order_book_snapshots")}


def test_ensure_capture_environment_column_reraises_genuine_errors(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.engine.base import Connection
    from sqlalchemy.exc import OperationalError

    engine = create_engine(f"sqlite:///{tmp_path}/genuine-error.db")
    from tradingbot.persistence.models import Base

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE order_book_snapshots DROP COLUMN environment"))

    def _always_fail(self, statement, *args, **kwargs):
        raise OperationalError(str(statement), {}, Exception("disk I/O error"))

    monkeypatch.setattr(Connection, "execute", _always_fail)

    try:
        _ensure_capture_environment_column(engine)
        assert False, "expected OperationalError to propagate"
    except OperationalError:
        pass
