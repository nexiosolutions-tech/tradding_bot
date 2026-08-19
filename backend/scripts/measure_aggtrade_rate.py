"""One-off measurement — spec 02, 2026-08-18. Measures real BTCUSDT mainnet aggTrade
arrival rate via data-api.binance.vision, sampled repeatedly across a full ~24h cycle, to
answer the question that decides aggtrade-capture's architecture: does REST polling by
fromId keep up at the peak, or does the historical archive
(data.binance.vision/data/spot/daily/aggTrades/) need to be the primary source with
polling only covering the recent tail? See
changes/2026-08-18-captura-aggtrade-fluxo-ordens.md.

A single 5-minute sample at a random moment would lie — BTCUSDT flow is heavily
heterogeneous (session opens, macro releases, sharp moves) — so this samples every
SAMPLE_INTERVAL_SECONDS across a full day; the answer that matters is the high percentile
of those samples, not the average (scripts/analyze_aggtrade_rate.py, run once enough
samples have accumulated).

Each sample: fetch the most recent FETCH_LIMIT trades (no fromId — Binance returns the
latest when it's omitted), derive trades/second from the real timestamp span they cover,
and read the actual weight cost from the `X-MBX-USED-WEIGHT-1M` response header — measured,
not assumed.

Not part of the running system — invoked manually as a temporary standalone service,
deleted once enough samples have accumulated and the architecture decision is made.

Required environment variables:
    SYMBOL          (default BTCUSDT)
    DATABASE_URL    (default: local sqlite under results/)

Usage:
    python scripts/measure_aggtrade_rate.py
"""

from __future__ import annotations

import asyncio
import os
import time

import httpx

from tradingbot.persistence.db import get_session_factory
from tradingbot.persistence.models import AggTradeRateSample
from tradingbot.persistence.repository import record_aggtrade_rate_sample

SAMPLE_INTERVAL_SECONDS = 300  # 5 min -> ~288 samples/24h
FETCH_LIMIT = 1000  # the max Binance allows per aggTrades call


def _sample_once(client: httpx.Client, symbol: str) -> dict | None:
    t0 = time.monotonic()
    try:
        resp = client.get(
            "https://data-api.binance.vision/api/v3/aggTrades",
            params={"symbol": symbol, "limit": FETCH_LIMIT},
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"amostra falhou, tentando de novo no próximo ciclo: {exc!r}")
        return None
    latency_ms = (time.monotonic() - t0) * 1000

    rows = resp.json()
    if len(rows) < 2:
        print(f"amostra com {len(rows)} trade(s) retornado(s), pulando")
        return None

    span_ms = int(rows[-1]["T"]) - int(rows[0]["T"])
    if span_ms <= 0:
        print("amostra com span não-positivo (relógio do servidor?), pulando")
        return None

    used_weight = resp.headers.get("x-mbx-used-weight-1m")
    return {
        "ts": int(time.time() * 1000),
        "trades_per_second": len(rows) / (span_ms / 1000),
        "span_ms": span_ms,
        "latency_ms": latency_ms,
        "used_weight_1m": int(used_weight) if used_weight is not None else None,
    }


async def main() -> None:
    symbol = os.environ.get("SYMBOL", "BTCUSDT")
    session_factory = get_session_factory(os.environ.get("DATABASE_URL"))

    print(
        f"Medindo taxa de chegada de aggTrade de {symbol} (mainnet via "
        f"data-api.binance.vision), 1 amostra/{SAMPLE_INTERVAL_SECONDS}s..."
    )
    with httpx.Client(timeout=15.0) as client:
        while True:
            sample = await asyncio.to_thread(_sample_once, client, symbol)
            if sample is not None:
                session = session_factory()
                record_aggtrade_rate_sample(
                    session,
                    AggTradeRateSample(symbol=symbol, **sample),
                )
                print(
                    f"amostra: {sample['trades_per_second']:.1f} trades/s "
                    f"(janela de {sample['span_ms']}ms para {FETCH_LIMIT} trades), "
                    f"latência {sample['latency_ms']:.0f}ms, "
                    f"peso usado (1min) {sample['used_weight_1m']}"
                )
            await asyncio.sleep(SAMPLE_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
