from dataclasses import dataclass

import pytest

from tradingbot.backtesting.strategy import TradeSignal
from tradingbot.execution.orchestrator import EngineState, Orchestrator
from tradingbot.ingestion.schema import EventType, MarketEvent
from tradingbot.persistence.db import get_session_factory
from tradingbot.persistence.repository import get_order, recent_engine_events, trades_in_range
from tradingbot.risk.manager import RiskConfig

from fakes import FakeExchangeClient


def _closed_kline(symbol, close, ts, volume=100.0):
    return MarketEvent(
        symbol=symbol,
        event_type=EventType.KLINE,
        exchange_ts=ts,
        local_ts=ts,
        sequence_id=ts,
        payload={
            "open_time": ts - 60_000,
            "close_time": ts,
            "interval": "1m",
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": volume,
            "is_closed": True,
        },
    )


def _gap_event(ts):
    return MarketEvent(
        symbol="*", event_type=EventType.GAP, exchange_ts=ts, local_ts=ts, sequence_id=ts, payload={"gap_seconds": 30}
    )


@dataclass
class ScriptedStrategy:
    entry_at_ts: int | None = None
    stop_loss_pct: float | None = 0.05
    exit_at_ts: int | None = None

    def on_features(self, snapshot):
        if snapshot.knowledge_ts == self.entry_at_ts:
            return TradeSignal(symbol=snapshot.symbol, confidence=1.0, stop_loss_pct=self.stop_loss_pct)
        return None

    def should_exit(self, snapshot):
        return self.exit_at_ts is not None and snapshot.knowledge_ts == self.exit_at_ts


def _make_orchestrator(tmp_path, strategy, exchange=None, risk_config=None, clock_start=0):
    session_factory = get_session_factory(f"sqlite:///{tmp_path}/test.db")
    clock = {"t": clock_start}

    def now_fn():
        clock["t"] += 1
        return clock["t"]

    orch = Orchestrator(
        symbol="BTCUSDT",
        strategy=strategy,
        risk_config=risk_config or RiskConfig(risk_per_trade_pct=0.10, max_concurrent_exposure_pct=1.0),
        exchange=exchange or FakeExchangeClient(),
        session_factory=session_factory,
        initial_equity=1_000.0,
        strategy_version="test-v1",
        now_fn=now_fn,
    )
    return orch, session_factory


def test_boots_paused_and_ignores_signals(tmp_path):
    exchange = FakeExchangeClient()
    strategy = ScriptedStrategy(entry_at_ts=60_000)
    orch, _ = _make_orchestrator(tmp_path, strategy, exchange)

    assert orch.state == EngineState.PAUSADO

    import asyncio

    asyncio.run(orch.on_event(_closed_kline("BTCUSDT", 100.0, 60_000)))

    assert orch.state == EngineState.PAUSADO
    assert exchange.call_log == []


def test_started_at_is_set_once_on_first_resume_and_not_reset(tmp_path):
    strategy = ScriptedStrategy()
    orch, _ = _make_orchestrator(tmp_path, strategy)
    assert orch.started_at is None

    orch.resume(by="brian")
    first_started_at = orch.started_at
    assert first_started_at is not None

    orch.pause(by="brian")
    orch.resume(by="brian")
    assert orch.started_at == first_started_at


def test_resume_then_entry_places_market_and_stop_orders(tmp_path):
    import asyncio

    exchange = FakeExchangeClient()
    exchange.next_fill_price["BTCUSDT"] = 100.0
    strategy = ScriptedStrategy(entry_at_ts=60_000, stop_loss_pct=0.05)
    orch, session_factory = _make_orchestrator(tmp_path, strategy, exchange)

    orch.resume(by="brian")
    assert orch.state == EngineState.ANALISANDO

    asyncio.run(orch.on_event(_closed_kline("BTCUSDT", 100.0, 60_000)))

    assert orch.state == EngineState.POSICAO_ABERTA
    kinds = [call[0] for call in exchange.call_log]
    assert kinds == ["place_market_order", "place_stop_loss_order"]

    session = session_factory()
    entry_order = get_order(session, orch._position.entry_order_id)
    stop_order = get_order(session, orch._position.stop_order_id)
    assert entry_order.status == "FILLED"
    assert stop_order.status == "NEW"


def test_signal_without_stop_loss_never_reaches_the_exchange(tmp_path):
    import asyncio

    exchange = FakeExchangeClient()
    strategy = ScriptedStrategy(entry_at_ts=60_000, stop_loss_pct=None)
    orch, _ = _make_orchestrator(tmp_path, strategy, exchange)
    orch.resume(by="brian")

    asyncio.run(orch.on_event(_closed_kline("BTCUSDT", 100.0, 60_000)))

    assert orch.state == EngineState.ANALISANDO
    assert exchange.call_log == []


def test_rejected_entry_order_does_not_open_a_position(tmp_path):
    import asyncio

    exchange = FakeExchangeClient()
    exchange.reject_next_market_order = True
    strategy = ScriptedStrategy(entry_at_ts=60_000)
    orch, _ = _make_orchestrator(tmp_path, strategy, exchange)
    orch.resume(by="brian")

    asyncio.run(orch.on_event(_closed_kline("BTCUSDT", 100.0, 60_000)))

    assert orch.state == EngineState.ANALISANDO
    assert orch._position is None
    # only the market order was attempted — no stop-loss for a position that never opened
    assert [c[0] for c in exchange.call_log] == ["place_market_order"]


def test_stop_loss_fill_detected_on_exchange_finalizes_trade(tmp_path):
    import asyncio

    exchange = FakeExchangeClient()
    exchange.next_fill_price["BTCUSDT"] = 100.0
    strategy = ScriptedStrategy(entry_at_ts=60_000, stop_loss_pct=0.05)
    orch, session_factory = _make_orchestrator(tmp_path, strategy, exchange)
    orch.resume(by="brian")

    asyncio.run(orch.on_event(_closed_kline("BTCUSDT", 100.0, 60_000)))
    assert orch.state == EngineState.POSICAO_ABERTA

    stop_order_id = orch._position.stop_order_id
    exchange.simulate_fill(stop_order_id, fill_price=95.0)

    asyncio.run(orch.on_event(_closed_kline("BTCUSDT", 95.0, 120_000)))

    assert orch.state == EngineState.ANALISANDO
    assert orch._position is None

    session = session_factory()
    trades = trades_in_range(session, 0, 10**15)
    assert len(trades) == 1
    assert trades[0].exit_reason == "stop_loss"
    assert trades[0].pnl < 0


def test_signal_exit_cancels_stop_and_sells_at_market(tmp_path):
    import asyncio

    exchange = FakeExchangeClient()
    exchange.next_fill_price["BTCUSDT"] = 100.0
    strategy = ScriptedStrategy(entry_at_ts=60_000, stop_loss_pct=0.05, exit_at_ts=120_000)
    orch, session_factory = _make_orchestrator(tmp_path, strategy, exchange)
    orch.resume(by="brian")

    asyncio.run(orch.on_event(_closed_kline("BTCUSDT", 100.0, 60_000)))
    exchange.next_fill_price["BTCUSDT"] = 110.0
    asyncio.run(orch.on_event(_closed_kline("BTCUSDT", 110.0, 120_000)))

    assert orch.state == EngineState.ANALISANDO
    kinds = [c[0] for c in exchange.call_log]
    assert "cancel_order" in kinds

    session = session_factory()
    trades = trades_in_range(session, 0, 10**15)
    assert len(trades) == 1
    assert trades[0].exit_reason == "signal_exit"
    assert trades[0].pnl > 0


def test_circuit_breaker_trips_and_requires_human_acknowledgement(tmp_path):
    import asyncio

    exchange = FakeExchangeClient()
    exchange.next_fill_price["BTCUSDT"] = 100.0
    strategy = ScriptedStrategy(entry_at_ts=60_000, stop_loss_pct=0.50)
    risk_config = RiskConfig(risk_per_trade_pct=0.50, circuit_breaker_loss_pct=0.05, max_concurrent_exposure_pct=1.0)
    orch, session_factory = _make_orchestrator(tmp_path, strategy, exchange, risk_config=risk_config)
    orch.resume(by="brian")

    asyncio.run(orch.on_event(_closed_kline("BTCUSDT", 100.0, 60_000)))
    exchange.simulate_fill(orch._position.stop_order_id, fill_price=94.0)
    asyncio.run(orch.on_event(_closed_kline("BTCUSDT", 94.0, 120_000)))

    assert orch.state == EngineState.PARADO_CIRCUIT_BREAKER

    with pytest.raises(RuntimeError):
        orch.resume(by="brian")

    orch.acknowledge_circuit_breaker(by="brian")
    assert orch.state == EngineState.ANALISANDO

    session = session_factory()
    events = recent_engine_events(session, limit=10)
    ack_events = [e for e in events if e.triggered_by_human and "reconhecido" in e.reason]
    assert len(ack_events) == 1


def test_gap_reconciles_stop_already_filled_while_disconnected(tmp_path):
    import asyncio

    exchange = FakeExchangeClient()
    exchange.next_fill_price["BTCUSDT"] = 100.0
    strategy = ScriptedStrategy(entry_at_ts=60_000, stop_loss_pct=0.05)
    orch, session_factory = _make_orchestrator(tmp_path, strategy, exchange)
    orch.resume(by="brian")

    asyncio.run(orch.on_event(_closed_kline("BTCUSDT", 100.0, 60_000)))
    exchange.simulate_fill(orch._position.stop_order_id, fill_price=95.0)

    asyncio.run(orch.on_event(_gap_event(200_000)))

    assert orch.state == EngineState.ANALISANDO
    assert orch._position is None
    session = session_factory()
    assert len(trades_in_range(session, 0, 10**15)) == 1


def test_gap_with_no_open_position_is_a_no_op(tmp_path):
    import asyncio

    strategy = ScriptedStrategy()
    orch, _ = _make_orchestrator(tmp_path, strategy)
    orch.resume(by="brian")

    asyncio.run(orch.on_event(_gap_event(200_000)))
    assert orch.state == EngineState.ANALISANDO
