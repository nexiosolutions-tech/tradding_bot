"""Live orchestrator — spec 01/06. Wires ingestion events through the same feature engine,
strategy, and risk rules used by backtesting, but places real orders through an
ExchangeClient and persists every step for audit. This is the only place allowed to call
the exchange to enter or exit a position.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from tradingbot.backtesting.strategy import Strategy
from tradingbot.execution.client import ExchangeClient, OrderResult, SymbolFilters
from tradingbot.execution.idempotency import make_client_order_id
from tradingbot.execution.rounding import meets_min_notional, round_down_to_step, round_to_tick
from tradingbot.features.engine import FeatureEngine, FeatureSnapshot
from tradingbot.features.indicators import EMA, RSI, BollingerBands
from tradingbot.ingestion.schema import EventType, MarketEvent
from tradingbot.persistence import repository
from tradingbot.persistence.models import CircuitBreakerEvent, EngineEvent, OrderRecord, TradeRecord
from tradingbot.risk.manager import MissingStopLossError, RiskConfig, RiskManager

ACTIVITY_LOG_MAXLEN = 200
CANDLE_HISTORY_MAXLEN = 500


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


@dataclass(frozen=True)
class CandleSnapshot:
    """OHLC + indicators in absolute price terms, kept only for the dashboard's price
    chart — deliberately separate from FeatureEngine's normalized (scale-invariant)
    feature vector fed to the model (spec 03/04). A human looking at a candlestick chart
    expects an EMA line in the same price units as the candles, not a percentage."""

    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    ema_fast: float | None
    ema_slow: float | None
    bollinger_mid: float | None
    bollinger_upper: float | None
    bollinger_lower: float | None
    rsi: float | None


def _extract_stop_price(order: OrderRecord) -> float | None:
    """OrderRecord.requested_price is never populated (see _persist_order) — the stop
    price lives inside the raw exchange response instead. Covers both the real Binance
    field name ("stopPrice") and the fake test client's ("stop_price")."""
    raw = order.raw_response or {}
    value = raw.get("stopPrice", raw.get("stop_price"))
    return float(value) if value is not None else None


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
        self._symbol_filters: SymbolFilters | None = None

        # Chart-only indicator state (spec 08) — same periods as FeatureEngine, but never
        # feeds the model, only the dashboard's price chart. See CandleSnapshot.
        self.candle_history: deque[CandleSnapshot] = deque(maxlen=CANDLE_HISTORY_MAXLEN)
        self._chart_ema_fast = EMA(12)
        self._chart_ema_slow = EMA(26)
        self._chart_bollinger = BollingerBands()
        self._chart_rsi = RSI(14)

    @property
    def open_position(self) -> OpenPositionLive | None:
        return self._position

    async def _get_symbol_filters(self) -> SymbolFilters:
        if self._symbol_filters is None:
            self._symbol_filters = await self.exchange.get_symbol_filters(self.symbol)
        return self._symbol_filters

    def _log_activity(self, level: str, message: str) -> None:
        self.activity_log.append(ActivityLogEntry(ts=self._now(), level=level, message=message))

    def recent_activity(self, limit: int = 50) -> list[ActivityLogEntry]:
        return list(self.activity_log)[-limit:]

    def recent_candles(self, limit: int = 200) -> list[CandleSnapshot]:
        return list(self.candle_history)[-limit:]

    async def reconcile_position_on_startup(self) -> None:
        """Called once, right after construction, before the event stream starts. A
        restart (local reload, redeploy, crash) must never silently forget a real open
        position — self._position always starts as None otherwise, so the engine would
        think it's flat even if a real, unprotected-or-protected position sits on the
        exchange. Reconstructs from persisted order records, then confirms the stop
        order's current status against the exchange (the source of truth) before
        resuming any decision — same reconciliation philosophy as _handle_gap, just
        triggered by process startup instead of a WebSocket gap."""
        with self.session_factory() as session:
            entry = repository.latest_unclosed_entry(session, self.symbol)
            if entry is None:
                return  # no dangling entry in our own records — genuinely flat
            stop = repository.latest_stop_loss_after(session, self.symbol, entry.created_at)

        if stop is None:
            self._log_activity(
                "warning",
                f"ALERTA CRÍTICO: entrada {entry.client_order_id} sem stop-loss encontrado nos "
                "registros ao reiniciar — posição pode estar desprotegida. Intervenção humana necessária.",
            )
            self._transition(EngineState.PAUSADO, "reconciliação de startup: entrada sem stop-loss registrado")
            return

        stop_price = _extract_stop_price(stop)
        if stop_price is None:
            self._log_activity(
                "warning",
                f"ALERTA CRÍTICO: não foi possível recuperar o preço do stop-loss {stop.client_order_id} "
                "ao reiniciar — intervenção humana necessária.",
            )
            self._transition(EngineState.PAUSADO, "reconciliação de startup: preço de stop-loss desconhecido")
            return

        reconciled_position = OpenPositionLive(
            entry_order_id=entry.client_order_id,
            stop_order_id=stop.client_order_id,
            entry_price=entry.avg_fill_price,
            size=entry.filled_qty,
            stop_loss_price=stop_price,
            entry_ts=int(entry.created_at),
        )

        stop_status = await self.exchange.get_order_status(self.symbol, stop.client_order_id)
        if stop_status is not None and stop_status.status == "FILLED":
            # The stop already triggered while the process was down — finalize it now so
            # equity and trade history reflect reality, instead of staying silently stale.
            self._position = reconciled_position
            await self._finalize_exit(self._now(), stop_status, reason="stop_loss")
            self._log_activity(
                "info", "Reconciliação de startup: stop-loss já havia disparado enquanto o engine estava fora do ar"
            )
            return

        self._position = reconciled_position
        self._log_activity(
            "warning",
            f"Reconciliação de startup: posição aberta reencontrada ({self.symbol} @ {entry.avg_fill_price:.2f})",
        )
        self._transition(EngineState.POSICAO_ABERTA, "reconciliação de startup: posição aberta reencontrada")

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
        self.risk.reset_session_peak(self.equity)
        self._log_activity("info", f"Circuit breaker reconhecido por {by}")
        self._transition(EngineState.ANALISANDO, "circuit breaker reconhecido", human=True)

    # -- event loop ----------------------------------------------------------

    async def on_event(self, event: MarketEvent) -> None:
        """Public entrypoint: never lets an exception escape. A background task driving
        this from a WebSocket stream would otherwise die silently on the first unexpected
        error, leaving the engine frozen with no operator-visible signal."""
        try:
            await self._handle_event(event)
        except Exception as exc:  # noqa: BLE001 — deliberately broad, see docstring
            self._log_activity("warning", f"Erro inesperado processando evento: {exc}")

    async def _handle_event(self, event: MarketEvent) -> None:
        if event.event_type is EventType.GAP:
            await self._handle_gap()
            return

        snapshot = self.feature_engine.on_event(event)
        if snapshot is None:
            return

        self._record_candle(event, snapshot)

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

    def _record_candle(self, event: MarketEvent, snapshot: FeatureSnapshot) -> None:
        payload = event.payload
        mid, upper, lower = self._chart_bollinger.update(snapshot.close)
        self.candle_history.append(
            CandleSnapshot(
                ts=snapshot.knowledge_ts,
                open=float(payload["open"]),
                high=float(payload["high"]),
                low=float(payload["low"]),
                close=snapshot.close,
                volume=float(payload["volume"]),
                ema_fast=self._chart_ema_fast.update(snapshot.close),
                ema_slow=self._chart_ema_slow.update(snapshot.close),
                bollinger_mid=mid,
                bollinger_upper=upper,
                bollinger_lower=lower,
                rsi=self._chart_rsi.update(snapshot.close),
            )
        )

    async def _try_enter(self, signal, snapshot: FeatureSnapshot) -> None:
        try:
            size = self.risk.position_size(self.equity, snapshot.close, signal.stop_loss_pct)
        except MissingStopLossError:
            self._log_activity("warning", "Sinal rejeitado: sem stop-loss (estrutural, spec 05)")
            return  # structurally rejected — spec 05, never reaches the exchange

        size = self.risk.cap_to_max_exposure(size, snapshot.close, self.equity)

        filters = await self._get_symbol_filters()
        size = round_down_to_step(size, filters.step_size)
        if size <= 0 or not meets_min_notional(size, snapshot.close, filters.min_notional):
            self._log_activity(
                "warning",
                f"Sinal rejeitado: notional abaixo do mínimo da exchange após arredondar ao lote "
                f"({size:.8f} @ {snapshot.close:.2f})",
            )
            return  # would be hard-rejected by the exchange (LOT_SIZE/MIN_NOTIONAL) — don't even try

        self._sequence += 1
        entry_id = make_client_order_id(self.symbol, "entry", snapshot.knowledge_ts, self._sequence)
        entry_order = await self.exchange.place_market_order(self.symbol, "buy", size, entry_id)
        self._persist_order(entry_order, purpose="entry", requested_qty=size)

        if (
            entry_order.status not in ("FILLED", "PARTIALLY_FILLED")
            or not entry_order.filled_qty
            or entry_order.avg_fill_price is None
        ):
            self._log_activity("warning", f"Ordem de entrada não executada (status={entry_order.status})")
            return  # rejected, unfilled, or malformed fill — stay flat, nothing to protect with a stop

        stop_loss_price = round_to_tick(
            entry_order.avg_fill_price * (1 - signal.stop_loss_pct), filters.tick_size
        )
        stop_id = make_client_order_id(self.symbol, "stop_loss", snapshot.knowledge_ts, self._sequence)
        stop_order = await self._place_stop_loss_with_retry(
            entry_order, stop_id, stop_loss_price, snapshot.knowledge_ts, filters.tick_size
        )
        if stop_order is None:
            return  # entry is open on the exchange but unprotected — handled emergency path already ran

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

    async def _place_stop_loss_with_retry(
        self,
        entry_order: OrderResult,
        stop_id: str,
        stop_loss_price: float,
        ts: int,
        tick_size: Decimal,
        attempts: int = 3,
    ) -> OrderResult | None:
        """CLAUDE.md regra 2 is structural: an entry may never be left open without a
        stop-loss. If placing it keeps failing (network, exchange 5xx), the entry is
        already filled and real — the only safe move is to retry, then close the position
        back out at market if every retry fails."""
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                stop_order = await self.exchange.place_stop_loss_order(
                    self.symbol, "sell", entry_order.filled_qty, stop_loss_price, stop_id, tick_size
                )
                self._persist_order(stop_order, purpose="stop_loss", requested_qty=entry_order.filled_qty)
                return stop_order
            except Exception as exc:  # noqa: BLE001 — any exchange/network failure, see docstring
                last_error = exc
                self._log_activity(
                    "warning", f"Falha ao colocar stop-loss (tentativa {attempt}/{attempts}): {exc}"
                )

        await self._emergency_close_unprotected(entry_order, stop_id, ts, last_error)
        return None

    async def _emergency_close_unprotected(
        self, entry_order: OrderResult, stop_id: str, ts: int, cause: Exception | None
    ) -> None:
        self._log_activity("warning", "Posição sem stop-loss após esgotar tentativas — fechando de emergência")
        # Track the position so a failed close below still leaves the engine aware of it
        # (never silently flat while a real, unprotected position sits on the exchange).
        self._position = OpenPositionLive(
            entry_order_id=entry_order.client_order_id,
            stop_order_id=stop_id,
            entry_price=entry_order.avg_fill_price,
            size=entry_order.filled_qty,
            stop_loss_price=entry_order.avg_fill_price,
            entry_ts=ts,
        )
        try:
            self._sequence += 1
            close_id = make_client_order_id(self.symbol, "emergency_close", ts, self._sequence)
            close_order = await self.exchange.place_market_order(self.symbol, "sell", entry_order.filled_qty, close_id)
            self._persist_order(close_order, purpose="emergency_close", requested_qty=entry_order.filled_qty)
            if close_order.status in ("FILLED", "PARTIALLY_FILLED") and close_order.filled_qty:
                await self._finalize_exit(ts, close_order, reason="emergency_close_no_stop_loss")
                return
            close_failure: Exception | str = f"status={close_order.status}"
        except Exception as exc:  # noqa: BLE001 — closing itself failing is the worst case, see below
            close_failure = exc

        # Software has done everything it safely can — pausing stops new entries, but the
        # existing unprotected position remains open on the exchange and needs a human.
        self._log_activity(
            "warning",
            f"ALERTA CRÍTICO: posição sem stop-loss e fechamento de emergência falhou "
            f"(causa original: {cause}; falha no fechamento: {close_failure}) — intervenção humana necessária",
        )
        self._transition(EngineState.PAUSADO, "fechamento de emergência falhou — intervenção humana necessária")

    async def _check_exit(self, snapshot: FeatureSnapshot) -> None:
        pos = self._position
        assert pos is not None

        stop_status = await self.exchange.get_order_status(self.symbol, pos.stop_order_id)
        if stop_status is not None and stop_status.status == "FILLED":
            await self._finalize_exit(snapshot.knowledge_ts, stop_status, reason="stop_loss")
            return

        if self.strategy.should_exit(snapshot):
            try:
                await self.exchange.cancel_order(self.symbol, pos.stop_order_id)
            except Exception as exc:  # noqa: BLE001 — the stop may already be gone (filled,
                # cancelled, or lost — e.g. a testnet data reset); cancelling it is best-effort
                # cleanup before the market exit below, not a precondition for it. Re-checking
                # status here (rather than assuming "not filled" and blindly selling again) is
                # what closed the 2026-08-09 incident: a stop-loss that had actually filled,
                # combined with an unguarded cancel_order, retried the same -2011 forever and
                # never reached _finalize_exit, leaving the position "open" in our state for a
                # week with no further trading possible — see changes/.
                self._log_activity(
                    "warning", f"Falha ao cancelar stop-loss antes da saída por sinal: {exc}"
                )
                stop_status = await self.exchange.get_order_status(self.symbol, pos.stop_order_id)
                if stop_status is not None and stop_status.status == "FILLED":
                    await self._finalize_exit(snapshot.knowledge_ts, stop_status, reason="stop_loss")
                    return
                self._log_activity(
                    "warning",
                    "Stop-loss não encontrado na exchange (e não preenchido) — prosseguindo com a saída por sinal mesmo assim",
                )

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
