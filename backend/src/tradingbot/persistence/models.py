"""Persistence schema — spec 06/09. SQLite for local/dev; the same models run unmodified
against Postgres once the Railway addon is provisioned (spec 10) — only DATABASE_URL changes.
"""

from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, Integer, String, UniqueConstraint
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


class OrderBookSnapshot(Base):
    """1 amostra/minuto do order book (top 20 níveis) — spec 02/03, 2026-08-15.
    Sem histórico retroativo possível (Binance não expõe order book passado), então esta
    tabela é o único jeito de acumular dado para uma futura feature de microestrutura —
    campos derivados (spread/imbalance) já vêm prontos para não precisar reprocessar os
    níveis brutos quando a feature for desenhada de verdade.

    `environment` ("testnet"/"mainnet", 2026-08-18): qual endpoint da Binance gerou a
    linha. Sem isso, dado de testnet (sinal sintético — ver
    changes/2026-08-18-captura-aggtrade-fluxo-ordens.md) e mainnet (real) ficariam
    misturados na mesma tabela sem como separar depois — pior que não ter dado nenhum,
    é treinar em dado contaminado achando que é real. Default "testnet" porque é o que a
    captura já vinha gravando antes desta coluna existir (`db.py::_ensure_environment_column`
    faz o backfill retroativo das linhas já persistidas)."""

    __tablename__ = "order_book_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    # Capturado localmente, não é um timestamp autoritativo da exchange — ver spec 02.
    ts: Mapped[int] = mapped_column(BigInteger, index=True)
    environment: Mapped[str] = mapped_column(String, default="testnet")
    best_bid: Mapped[float] = mapped_column(Float)
    best_ask: Mapped[float] = mapped_column(Float)
    spread_pct: Mapped[float] = mapped_column(Float)
    bid_depth_top20: Mapped[float] = mapped_column(Float)
    ask_depth_top20: Mapped[float] = mapped_column(Float)
    imbalance: Mapped[float] = mapped_column(Float)
    raw_bids: Mapped[list] = mapped_column(JSON)
    raw_asks: Mapped[list] = mapped_column(JSON)


class AggTradeBucket(Base):
    """1 bucket/segundo de volume comprador/vendedor (aggressor side) — spec 02/03,
    2026-08-18. Sem histórico retroativo possível (Binance não expõe aggTrade passado além
    da janela recente da REST API), então esta tabela é o único jeito de acumular dado de
    fluxo de ordens para uma futura feature de order flow imbalance — mesma lógica de
    order_book_snapshots acima, aplicada a trades em vez de book depth.

    `notional` (preço × quantidade somado, não só o vwap já dividido) é guardado explicitamente
    para que um backfill de gap (`ingestion/binance_aggtrade_ws.py`) possa fazer merge exato
    num bucket já persistido pelo caminho ao vivo — recalcular vwap a partir de um vwap já
    perdido não reproduz o valor exato; a partir do notional bruto, reproduz.

    Unique em (symbol, ts): o mesmo bucket pode ser tocado duas vezes (caminho ao vivo e
    backfill de gap) — upsert_agg_trade_bucket (repository.py) depende dessa constraint
    para decidir merge vs. insert."""

    __tablename__ = "agg_trade_buckets"
    __table_args__ = (UniqueConstraint("symbol", "ts", name="uq_agg_trade_buckets_symbol_ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    ts: Mapped[int] = mapped_column(BigInteger, index=True)
    # "testnet"/"mainnet" (2026-08-18) — mesmo raciocínio de OrderBookSnapshot.environment
    # acima: sem isso, dado sintético de testnet e dado real de mainnet ficam misturados na
    # mesma tabela sem como separar depois.
    environment: Mapped[str] = mapped_column(String, default="testnet")
    buy_volume: Mapped[float] = mapped_column(Float)
    sell_volume: Mapped[float] = mapped_column(Float)
    buy_count: Mapped[int] = mapped_column(Integer)
    sell_count: Mapped[int] = mapped_column(Integer)
    vwap: Mapped[float] = mapped_column(Float)
    notional: Mapped[float] = mapped_column(Float)


class AggTradeRateSample(Base):
    """Investigação pontual (2026-08-18, changes/2026-08-18-captura-aggtrade-fluxo-ordens.md)
    — não é captura permanente, seguro apagar depois que a decisão de arquitetura do
    aggtrade-capture (polling REST como fonte primária vs. arquivo diário + polling como
    cauda) for tomada. Cada linha é uma amostra de quantos segundos de atividade real de
    mercado (mainnet) cabem numa única resposta de 1000 trades — `scripts/measure_aggtrade_rate.py`
    amostra repetidamente ao longo de um ciclo de ~24h porque o fluxo de BTCUSDT é
    heterogêneo (abertura de sessão, dados macro, movimentos bruscos); uma amostra única
    num momento calmo mentiria. `used_weight_1m` vem direto do header
    `X-MBX-USED-WEIGHT-1M` da própria resposta — peso real observado, não estimado."""

    __tablename__ = "aggtrade_rate_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    ts: Mapped[int] = mapped_column(BigInteger, index=True)
    trades_per_second: Mapped[float] = mapped_column(Float)
    span_ms: Mapped[int] = mapped_column(BigInteger)
    latency_ms: Mapped[float] = mapped_column(Float)
    used_weight_1m: Mapped[int | None] = mapped_column(Integer, nullable=True)


class EngineEvent(Base):
    """State-machine transitions (spec 01) — the audit trail behind the dashboard's Live view."""

    __tablename__ = "engine_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[int] = mapped_column(BigInteger)
    from_state: Mapped[str] = mapped_column(String)
    to_state: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    triggered_by_human: Mapped[bool] = mapped_column(Boolean, default=False)
