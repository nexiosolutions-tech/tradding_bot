"""Persistence schema — spec 06/09. SQLite for local/dev; the same models run unmodified
against Postgres once the Railway addon is provisioned (spec 10) — only DATABASE_URL changes.
"""

from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OrderRecord(Base):
    """Every state an order passes through — spec 06: 'todo evento de ciclo de vida da
    ordem é persistido, não só o resultado final'."""

    __tablename__ = "orders"

    client_order_id: Mapped[str] = mapped_column(String, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)  # "buy" | "sell"
    purpose: Mapped[str] = mapped_column(String)  # "entry" | "stop_loss" | "exit"
    requested_qty: Mapped[float] = mapped_column(Float)
    requested_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String)  # NEW/SENT/PARTIALLY_FILLED/FILLED/CANCELED/REJECTED
    filled_qty: Mapped[float] = mapped_column(Float, default=0.0)
    avg_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[str] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String)
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class TradeRecord(Base):
    """A closed round-trip — mirrors backtesting.engine.ClosedTrade, but for real fills."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    entry_order_id: Mapped[str] = mapped_column(String)
    exit_order_id: Mapped[str] = mapped_column(String)
    # Millisecond epoch timestamps (~1.7e12 today) already exceed a 32-bit INTEGER's
    # ~2.1e9 range — BigInteger, not Integer. SQLite's dynamic INTEGER never caught this
    # in local dev; only surfaced against real Postgres (2026-08-01, first real
    # engine_events insert in production hit the same bug on the `ts` column below).
    entry_ts: Mapped[int] = mapped_column(BigInteger)
    exit_ts: Mapped[int] = mapped_column(BigInteger)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float] = mapped_column(Float)
    size: Mapped[float] = mapped_column(Float)
    pnl: Mapped[float] = mapped_column(Float)
    fees_paid: Mapped[float] = mapped_column(Float)
    exit_reason: Mapped[str] = mapped_column(String)
    strategy_version: Mapped[str] = mapped_column(String)


class CircuitBreakerEvent(Base):
    """Spec 05: circuit breaker trips are audited events, not silent state flips."""

    __tablename__ = "circuit_breaker_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    triggered_at: Mapped[int] = mapped_column(BigInteger)
    equity_at_trigger: Mapped[float] = mapped_column(Float)
    peak_equity: Mapped[float] = mapped_column(Float)
    drawdown_pct: Mapped[float] = mapped_column(Float)
    acknowledged_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String, nullable=True)


class EngineEvent(Base):
    """State-machine transitions (spec 01) — the audit trail behind the dashboard's Live view."""

    __tablename__ = "engine_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[int] = mapped_column(BigInteger)
    from_state: Mapped[str] = mapped_column(String)
    to_state: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    triggered_by_human: Mapped[bool] = mapped_column(Boolean, default=False)
