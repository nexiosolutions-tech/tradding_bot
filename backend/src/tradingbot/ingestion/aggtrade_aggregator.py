"""Order flow (buy/sell volume) aggregation — spec 02/03, 2026-08-18. Reduces a
continuous aggTrade stream (often hundreds of trades/minute for BTCUSDT) into one
buy/sell-volume bucket per minute, deciding aggressor side (`is_buyer_maker`) at capture
time so a later feature-engineering pass doesn't need to replay every individual trade.
No persistence import here on purpose — this stays a pure transformation, like the rest
of ingestion/.

Differs from DepthSampler: a depth snapshot is already a complete instantaneous state, so
sampling just keeps the first event of a new bucket and drops the rest. A trade is one
increment of a period, so this accumulates every event within the bucket and only emits
once the bucket is provably complete — mirrors features/engine.py's _TimeframeAggregator
(emit on the first event of the *next* bucket, never a still-forming one), the same
anti-leakage invariant spec 03 requires elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ingestion.schema import MarketEvent

# 1 segundo, não 1 minuto — bucket size é uma decisão irreversível (dá pra agregar mais
# grosso depois somando buckets finos, nunca mais fino a partir de um bucket já gravado).
# BTCUSDT aggTrade gera a ordem de dezenas de milhares de mensagens/dia; mesmo a 1
# bucket/segundo isso é ~86 400 linhas/dia (~35 bytes de payload numérico cada) — trivial
# pro Postgres do Railway, e preserva resolução suficiente pra qualquer reagregação futura
# (order flow imbalance em janela de 1min, 5min, etc. vira só um SUM sobre estas linhas).
BUCKET_INTERVAL_MS = 1_000


@dataclass(frozen=True)
class AggTradeBucketFields:
    symbol: str
    ts: int
    buy_volume: float
    sell_volume: float
    buy_count: int
    sell_count: int
    vwap: float
    notional: float


class _BucketAccumulator:
    def __init__(self, symbol: str, bucket_start_ts: int):
        self.symbol = symbol
        self.bucket_start_ts = bucket_start_ts
        self.buy_volume = 0.0
        self.sell_volume = 0.0
        self.buy_count = 0
        self.sell_count = 0
        self._notional = 0.0

    def add(self, price: float, quantity: float, is_buyer_maker: bool) -> None:
        self._notional += price * quantity
        if is_buyer_maker:
            # Buyer was the resting order (maker) -> seller crossed the spread -> aggressor sell.
            self.sell_volume += quantity
            self.sell_count += 1
        else:
            self.buy_volume += quantity
            self.buy_count += 1

    def finalize(self) -> AggTradeBucketFields:
        total_volume = self.buy_volume + self.sell_volume
        vwap = self._notional / total_volume if total_volume else 0.0
        return AggTradeBucketFields(
            symbol=self.symbol,
            ts=self.bucket_start_ts,
            buy_volume=self.buy_volume,
            sell_volume=self.sell_volume,
            buy_count=self.buy_count,
            sell_count=self.sell_count,
            vwap=vwap,
            notional=self._notional,
        )


class AggTradeAggregator:
    """Accumulates aggTrade events per symbol into BUCKET_INTERVAL_MS buckets. Call
    `add(event)` for every trade; it returns the completed previous bucket the instant a
    trade from a new bucket arrives (or None while still accumulating the current one)."""

    def __init__(self, bucket_interval_ms: int = BUCKET_INTERVAL_MS):
        self._bucket_interval_ms = bucket_interval_ms
        self._current: dict[str, _BucketAccumulator] = {}

    def add(self, event: MarketEvent) -> AggTradeBucketFields | None:
        bucket_start = (event.exchange_ts // self._bucket_interval_ms) * self._bucket_interval_ms
        acc = self._current.get(event.symbol)

        completed: AggTradeBucketFields | None = None
        if acc is None:
            acc = _BucketAccumulator(event.symbol, bucket_start)
            self._current[event.symbol] = acc
        elif bucket_start != acc.bucket_start_ts:
            completed = acc.finalize()
            acc = _BucketAccumulator(event.symbol, bucket_start)
            self._current[event.symbol] = acc

        acc.add(event.payload["price"], event.payload["quantity"], event.payload["is_buyer_maker"])
        return completed

    def flush(self, symbol: str) -> AggTradeBucketFields | None:
        """Force-closes the in-progress bucket for `symbol` regardless of whether the next
        bucket has started — the live stream never calls this on its own (there's always a
        "next" trade eventually), but graceful shutdown and REST backfill batches both have
        a definite last event with nothing after it to trigger the normal rollover."""
        acc = self._current.pop(symbol, None)
        return acc.finalize() if acc is not None else None
