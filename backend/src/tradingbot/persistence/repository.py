"""Repository functions — thin, explicit queries. No ORM leaking into callers beyond the
dataclass-like records defined in models.py.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.persistence.models import CircuitBreakerEvent, EngineEvent, OrderRecord, TradeRecord


def upsert_order(session: Session, order: OrderRecord) -> None:
    existing = session.get(OrderRecord, order.client_order_id)
    if existing is None:
        session.add(order)
    else:
        existing.status = order.status
        existing.filled_qty = order.filled_qty
        existing.avg_fill_price = order.avg_fill_price
        existing.updated_at = order.updated_at
        existing.raw_response = order.raw_response
    session.commit()


def get_order(session: Session, client_order_id: str) -> OrderRecord | None:
    return session.get(OrderRecord, client_order_id)


def record_trade(session: Session, trade: TradeRecord) -> None:
    session.add(trade)
    session.commit()


def trades_in_range(session: Session, start_ts: int, end_ts: int) -> list[TradeRecord]:
    stmt = select(TradeRecord).where(TradeRecord.exit_ts >= start_ts, TradeRecord.exit_ts <= end_ts)
    return list(session.scalars(stmt))


def sum_realized_pnl(session: Session, symbol: str) -> float:
    """Total P&L across every closed trade ever recorded for this symbol — used to
    reconstruct equity on startup instead of always resetting to INITIAL_EQUITY (spec 05:
    a restart must never silently forget real P&L already booked)."""
    stmt = select(TradeRecord.pnl).where(TradeRecord.symbol == symbol)
    return float(sum(session.scalars(stmt)))


def latest_unclosed_entry(session: Session, symbol: str) -> OrderRecord | None:
    """Most recent filled entry order with no matching TradeRecord yet — a candidate for a
    position that was still open when the process last stopped. created_at is a
    string-encoded ms-epoch timestamp (same digit count for the foreseeable future, so
    string ordering matches chronological ordering)."""
    closed_entry_ids = set(session.scalars(select(TradeRecord.entry_order_id).where(TradeRecord.symbol == symbol)))
    stmt = (
        select(OrderRecord)
        .where(
            OrderRecord.symbol == symbol,
            OrderRecord.purpose == "entry",
            OrderRecord.status.in_(("FILLED", "PARTIALLY_FILLED")),
            OrderRecord.avg_fill_price.is_not(None),
            OrderRecord.filled_qty > 0,
        )
        .order_by(OrderRecord.created_at.desc())
    )
    for order in session.scalars(stmt):
        if order.client_order_id not in closed_entry_ids:
            return order
    return None


def latest_stop_loss_after(session: Session, symbol: str, after_created_at: str) -> OrderRecord | None:
    stmt = (
        select(OrderRecord)
        .where(
            OrderRecord.symbol == symbol,
            OrderRecord.purpose == "stop_loss",
            OrderRecord.created_at >= after_created_at,
        )
        .order_by(OrderRecord.created_at.desc())
    )
    return session.scalars(stmt).first()


def record_circuit_breaker_event(session: Session, event: CircuitBreakerEvent) -> CircuitBreakerEvent:
    session.add(event)
    session.commit()
    return event


def latest_unacknowledged_circuit_breaker(session: Session) -> CircuitBreakerEvent | None:
    stmt = (
        select(CircuitBreakerEvent)
        .where(CircuitBreakerEvent.acknowledged_at.is_(None))
        .order_by(CircuitBreakerEvent.triggered_at.desc())
    )
    return session.scalars(stmt).first()


def acknowledge_circuit_breaker(session: Session, event_id: int, ts: int, acknowledged_by: str) -> None:
    event = session.get(CircuitBreakerEvent, event_id)
    if event is None:
        raise ValueError(f"no circuit breaker event with id {event_id}")
    event.acknowledged_at = ts
    event.acknowledged_by = acknowledged_by
    session.commit()


def record_engine_event(session: Session, event: EngineEvent) -> None:
    session.add(event)
    session.commit()


def recent_engine_events(session: Session, limit: int = 50) -> list[EngineEvent]:
    stmt = select(EngineEvent).order_by(EngineEvent.ts.desc()).limit(limit)
    return list(session.scalars(stmt))
