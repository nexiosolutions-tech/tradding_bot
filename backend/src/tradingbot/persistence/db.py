"""Database wiring — spec 10. Defaults to a local SQLite file; set DATABASE_URL to a
Postgres connection string (Railway addon) in any environment past local dev without
changing a single model or query.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from tradingbot.persistence.models import Base

DEFAULT_SQLITE_PATH = Path(__file__).resolve().parents[4] / "results" / "tradingbot.db"


def _default_database_url() -> str:
    DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DEFAULT_SQLITE_PATH}"


def get_engine(database_url: str | None = None):
    url = database_url or os.environ.get("DATABASE_URL") or _default_database_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def _ensure_capture_environment_column(engine) -> None:
    """Base.metadata.create_all only creates missing tables, it never alters existing
    ones, and this project has no migration framework — order_book_snapshots (real rows
    since 2026-08-15) and agg_trade_buckets need their new `environment` column added by
    hand (2026-08-18, changes/2026-08-18-captura-aggtrade-fluxo-ordens.md). `ADD COLUMN
    ... DEFAULT 'testnet'` backfills existing rows with that default in the same
    statement (both SQLite and Postgres) — correct here, since every row persisted
    before this column existed really was captured from testnet.

    Every service on this project (tradding_bot, depth-capture, aggtrade-capture,
    learning-daily-cron) calls get_session_factory at startup and they redeploy together
    within seconds of each other (observed directly this session) — two of them can race
    to add the same column. Check-then-add isn't atomic across processes, so a losing
    process's ALTER can fail with "column already exists"; that specific failure is
    swallowed after re-checking the column really is there now (someone else's ALTER
    landed), any other error still propagates."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table in ("order_book_snapshots", "agg_trade_buckets"):
        if table not in existing_tables:
            continue  # brand-new DB: create_all already created it with the column.
        existing_columns = {c["name"] for c in inspector.get_columns(table)}
        if "environment" in existing_columns:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN environment VARCHAR DEFAULT 'testnet'"))
        except DBAPIError:
            if "environment" not in {c["name"] for c in inspect(engine).get_columns(table)}:
                raise


def get_session_factory(database_url: str | None = None) -> sessionmaker:
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    _ensure_capture_environment_column(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


_default_session_factory: sessionmaker | None = None


def get_session() -> Session:
    global _default_session_factory
    if _default_session_factory is None:
        _default_session_factory = get_session_factory()
    return _default_session_factory()
