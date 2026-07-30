"""Database wiring — spec 10. Defaults to a local SQLite file; set DATABASE_URL to a
Postgres connection string (Railway addon) in any environment past local dev without
changing a single model or query.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
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


def get_session_factory(database_url: str | None = None) -> sessionmaker:
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


_default_session_factory: sessionmaker | None = None


def get_session() -> Session:
    global _default_session_factory
    if _default_session_factory is None:
        _default_session_factory = get_session_factory()
    return _default_session_factory()
