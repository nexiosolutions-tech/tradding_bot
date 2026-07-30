"""Live orchestrator — spec 01/06. Wires ingestion events through the same feature engine,
strategy, and risk rules used by backtesting, but places real orders through an
ExchangeClient and persists every step for audit. This is the only place allowed to call
the exchange to enter or exit a position.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum

from tradingbot.backtesting.strategy import Strategy
from tradingbot.execution.client import ExchangeClient, OrderResult
from tradingbot.execution.idempotency import make_client_order_id
from tradingbot.features.engine import FeatureEngine, FeatureSnapshot
from tradingbot.ingestion.schema import EventType, MarketEvent
from tradingbot.persistence import repository
from tradingbot.persistence.models import CircuitBreakerEvent, EngineEvent, OrderRecord, TradeRecord
from tradingbot.risk.manager import MissingStopLossError, RiskConfig, RiskManager

ACTIVITY_LOG_MAXLEN = 200


class EngineState(str, Enum):
    ANALISANDO = "ANALISANDO"
    POSICAO_ABERTA = "POSICAO_ABERTA"
    PAUSADO = "PAUSADO"
    PARADO_CIRCUIT_BREAKER = "PARADO_CIRCUIT_BREAKER"


@dataclass(frozen=True)
class ActivityLogEntry:
    """A 'proof of life' feed, separate from EngineEvent (spec 01's audit trail of state
    transitions). This exists purely so the dashboard's Live view can show the engine is
    still evaluating candles between trades — it is not persisted, not an audit record."""

    ts: int
    level: str  # "info" | "signal" | "trade" | "warning"
    message: str


@dataclass
class OpenPositionLive:
    entry_order_id: str
    stop_order_id: str
    entry_price: float
    size: float
    stop_loss_price: float
    entry_ts: int


class Orchestrator:
    def __init__(
        self,
        symbol: str,
        strategy: Strategy,
        risk_config: RiskConfig,
        exchange: ExchangeClient,
        session_factory,
        initial_equity: float,
        strategy_version: str,
        now_fn,
    ):
        self.symbol = symbol
        self.strategy = strategy
        self.risk = RiskManager(risk_config)
        self.exchange = exchange
        self.session_factory = session_factory
        self.feature_engine = FeatureEngine()
        self.equity = initial_equity
        self.strategy_version = strategy_version
        self._now = now_fn
        self.state = EngineState.PAUSADO  # boots paused — a human must explicitly resume
        self._position: OpenPositionLive | None = None
        self._sequence = 0
        self.started_at: int | None = None
        self.activity_log: deque[ActivityLogEntry] = deque(maxlen=ACTIVITY_LOG_MAXLEN)

    @property
    def open_position(self) -> OpenPositionLive | None:
        return self._position

    def _log_activity(self, level: str, message: str) -> None:
        self.activity_log.append(ActivityLogEntry(ts=self._now(), level=level, message=message))

    def recent_activity(self, limit: int = 50) -> list[ActivityLogEntry]:
        return list(self.activity_log)[-limit:]

    # -- operator commands -------------------------------------------------

    def resume(self, by: str) -> None:
        if self.state == EngineState.PARADO_CIRCUIT_BREAKER:
            raise RuntimeError("circuit breaker ativo — reconheça antes de retomar")
        if self.started_at is None:
            self.started_at = self._now()
        self._log_activity("info", f"Engine retomado por {by}")
        self._transition(EngineState.ANALISANDO, "retomado pelo operador", human=True)

    def pause(self, by: str) -> None:
        self._log_activity("info", f"Engine pausado por {by}")
        self._transition(EngineState.PAUSADO, "pausado pelo operador", human=True)

    def acknowledge_circuit_breaker(self, by: str) -> None:
        if self.state != EngineState.PARADO_CIRCUIT_BREAKER:
            raise RuntimeError("nenhum circuit breaker ativo para reconhecer")
        with self.session_factory() as session:
            event = repository.latest_unacknowledged_circuit_breaker(session)
            if event is not None:
                repository.acknowledge_circuit_breaker(session, event.id, ts=self._now(), acknowledged_by=by)
        self.risk.circuit_breaker_triggered = False  # the only path that clears it — always human
        self._log_activity("info", f"Circuit breaker reconhecido por {by}")
        self._transition(EngineState.ANALISANDO, "circuit breaker reconhecido", human=True)

    # -- event loop ----------------------------------------------------------

    async def on_event(self, event: MarketEvent) -> None:
        if event.event_type is EventType.GAP:
            await self._handle_gap()
            return

        snapshot = self.feature_engine.on_event(event)
        if snapshot is None:
            return

        if self.state in (EngineState.PAUSADO, EngineState.PARADO_CIRCUIT_BREAKER):
            return  # indicators keep warming up "a seco"; no decision is made

        if self._position is not None:
            self._log_activity("info", f"{self.symbol} @ {snapshot.close:.2f} — monitorando posição aberta")
            await self._check_exit(snapshot)
        elif self.risk.can_enter():
            signal = self.strategy.on_features(snapshot)
            if signal is not None:
                self._log_activity(
                    "signal", f"{self.symbol} @ {snapshot.close:.2f} — sinal detectado (confiança {signal.confidence:.0%})"
                )
                await self._try_enter(signal, snapshot)
            else:
                self._log_activity("info", f"{self.symbol} @ {snapshot.close:.2f} — analisando, sem sinal")

        self._maybe_trip_circuit_breaker(snapshot.knowledge_ts)

    async def _try_enter(self, signal, snapshot: FeatureSnapshot) -> None:
        try:
            size = self.risk.position_size(self.equity, snapshot.close, signal.stop_loss_pct)
        except MissingStopLossError:
            self._log_activity("warning", "Sinal rejeitado: sem stop-loss (estrutural, spec 05)")
            return  # structurally rejected — spec 05, never reaches the exchange

        size = self.risk.cap_to_max_exposure(size, snapshot.close, self.equity)

        self._sequence += 1
        entry_id = make_client_order_id(self.symbol, "entry", snapshot.knowledge_ts, self._sequence)
        entry_order = await self.exchange.place_market_order(self.symbol, "buy", size, entry_id)
        self._persist_order(entry_order, purpose="entry", requested_qty=size)

        if entry_order.status not in ("FILLED", "PARTIALLY_FILLED") or not entry_order.filled_qty:
            self._log_activity("warning", f"Ordem de entrada não executada (status={entry_order.status})")
            return  # rejected or unfilled — stay flat, nothing to protect with a stop

        stop_loss_price = entry_order.avg_fill_price * (1 - signal.stop_loss_pct)
        stop_id = make_client_order_id(self.symbol, "stop_loss", snapshot.knowledge_ts, self._sequence)
        stop_order = await self.exchange.place_stop_loss_order(
            self.symbol, "sell", entry_order.filled_qty, stop_loss_price, stop_id
        )
        self._persist_order(stop_order, purpose="stop_loss", requested_qty=entry_order.filled_qty)

        self._position = OpenPositionLive(
            entry_order_id=entry_id,
            stop_order_id=stop_id,
            entry_price=entry_order.avg_fill_price,
            size=entry_order.filled_qty,
            stop_loss_price=stop_loss_price,
            entry_ts=snapshot.knowledge_ts,
        )
        self._log_activity(
            "trade",
            f"Posição aberta @ {entry_order.avg_fill_price:.2f} — tamanho {entry_order.filled_qty:.6f} "
            f"— stop em {stop_loss_price:.2f}",
        )
        self._transition(EngineState.POSICAO_ABERTA, "entrada executada")

    async def _check_exit(self, snapshot: FeatureSnapshot) -> None:
        pos = self._position
        assert pos is not None

        stop_status = await self.exchange.get_order_status(self.symbol, pos.stop_order_id)
        if stop_status is not None and stop_status.status == "FILLED":
            await self._finalize_exit(snapshot.knowledge_ts, stop_status, reason="stop_loss")
            return

        if self.strategy.should_exit(snapshot):
            await self.exchange.cancel_order(self.symbol, pos.stop_order_id)
            self._sequence += 1
            exit_id = make_client_order_id(self.symbol, "exit", snapshot.knowledge_ts, self._sequence)
            exit_order = await self.exchange.place_market_order(self.symbol, "sell", pos.size, exit_id)
            self._persist_order(exit_order, purpose="exit", requested_qty=pos.size)
            if exit_order.status in ("FILLED", "PARTIALLY_FILLED") and exit_order.filled_qty:
                await self._finalize_exit(snapshot.knowledge_ts, exit_order, reason="signal_exit")

    async def _finalize_exit(self, exit_ts: int, exit_order: OrderResult, reason: str) -> None:
        pos = self._position
        assert pos is not None
        pnl = (exit_order.avg_fill_price - pos.entry_price) * pos.size
        self.equity += pnl
        with self.session_factory() as session:
            repository.record_trade(
                session,
                TradeRecord(
                    symbol=self.symbol,
                    entry_order_id=pos.entry_order_id,
                    exit_order_id=exit_order.client_order_id,
                    entry_ts=pos.entry_ts,
                    exit_ts=exit_ts,
                    entry_price=pos.entry_price,
                    exit_price=exit_order.avg_fill_price,
                    size=pos.size,
                    pnl=pnl,
                    # Binance spot deducts commission from the fill itself (visible per-fill,
                    # potentially in a different asset) — not converted/aggregated here yet.
                    # Flagged as a known gap rather than reporting a fabricated number.
                    fees_paid=0.0,
                    exit_reason=reason,
                    strategy_version=self.strategy_version,
                ),
            )
        self._position = None
        self._log_activity(
            "trade", f"Posição fechada ({reason}) @ {exit_order.avg_fill_price:.2f} — P&L {pnl:+.2f}"
        )
        self._transition(EngineState.ANALISANDO, f"posição fechada ({reason})")

    async def _handle_gap(self) -> None:
        """spec 02/06: on a reconnect gap, reconcile local state against the exchange —
        the source of truth — before resuming any decision."""
        if self._position is None:
            return
        pos = self._position
        stop_status = await self.exchange.get_order_status(self.symbol, pos.stop_order_id)
        if stop_status is not None and stop_status.status == "FILLED":
            await self._finalize_exit(self._now(), stop_status, reason="stop_loss")

    def _maybe_trip_circuit_breaker(self, ts: int) -> None:
        was_triggered = self.risk.circuit_breaker_triggered
        self.risk.record_equity(ts, self.equity)
        if self.risk.circuit_breaker_triggered and not was_triggered:
            peak = self.risk.peak_equity or self.equity
            with self.session_factory() as session:
                repository.record_circuit_breaker_event(
                    session,
                    CircuitBreakerEvent(
                        triggered_at=ts,
                        equity_at_trigger=self.equity,
                        peak_equity=peak,
                        drawdown_pct=(peak - self.equity) / peak if peak else 0.0,
                    ),
                )
            drawdown_pct = (peak - self.equity) / peak if peak else 0.0
            self._log_activity("warning", f"Circuit breaker acionado — drawdown de {drawdown_pct:.1%}")
            self._transition(EngineState.PARADO_CIRCUIT_BREAKER, "circuit breaker acionado")

    def _persist_order(self, order: OrderResult, purpose: str, requested_qty: float) -> None:
        now = str(self._now())
        with self.session_factory() as session:
            repository.upsert_order(
                session,
                OrderRecord(
                    client_order_id=order.client_order_id,
                    symbol=self.symbol,
                    side="buy" if purpose == "entry" else "sell",
                    purpose=purpose,
                    requested_qty=requested_qty,
                    requested_price=None,
                    status=order.status,
                    filled_qty=order.filled_qty,
                    avg_fill_price=order.avg_fill_price,
                    created_at=now,
                    updated_at=now,
                    raw_response=order.raw,
                ),
            )

    def _transition(self, to_state: EngineState, reason: str, human: bool = False) -> None:
        from_state = self.state
        self.state = to_state
        with self.session_factory() as session:
            repository.record_engine_event(
                session,
                EngineEvent(
                    ts=self._now(),
                    from_state=from_state.value,
                    to_state=to_state.value,
                    reason=reason,
                    triggered_by_human=human,
                ),
            )
