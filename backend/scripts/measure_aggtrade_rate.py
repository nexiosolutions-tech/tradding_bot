"""Continuous measurement — spec 02, 2026-08-18. Measures real BTCUSDT mainnet aggTrade
arrival rate via data-api.binance.vision, to answer the question that decides
aggtrade-capture's architecture: does REST polling by fromId keep up at the peak, or does
the historical archive (data.binance.vision/data/spot/daily/aggTrades/) need to be the
primary source with polling only covering the recent tail? See
changes/2026-08-18-captura-aggtrade-fluxo-ordens.md.

Sampled continuously, not for a fixed window — a single 5-minute sample at a random moment
would lie (BTCUSDT flow is heavily heterogeneous: session opens, macro releases, sharp
moves), and even a full 24h cycle only captures intraday seasonality, not event-driven
tail risk (a liquidation cascade doesn't obey a clock and may not show up in any given
day). The answer that matters is a high percentile across as much history as exists
(scripts/analyze_aggtrade_rate.py), and that percentile is a floor on the true peak, not
the peak itself — the architecture decision's 3x headroom margin exists specifically to
absorb that gap, not as a separate safety factor on top of it. Left running permanently
(2026-08-18, not deleted after the initial decision): the cost is trivial (a few requests/
minute, single-digit weight — see SAMPLE_INTERVAL_SECONDS below), the percentile only gets
more trustworthy with more history, and it doubles as a standing detector if the endpoint's
real-world behavior ever changes.

Each sample: fetch the most recent FETCH_LIMIT trades (no fromId — Binance returns the
latest when it's omitted), derive trades/second from the real timestamp span they cover,
and read the actual weight cost from the `X-MBX-USED-WEIGHT-1M` response header — measured,
not assumed.

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

# 30s, not the original 5min: a 60-90s burst — the exact failure mode this measures — can
# fall entirely inside a 5min gap between samples, systematically underestimating the true
# peak. Weight observed per sample (~4, see the header this script reads) leaves enormous
# headroom against the 6000/min per-IP ceiling even at this cadence — confirmed with the
# measured value, not assumed, before tightening it (2026-08-18).
SAMPLE_INTERVAL_SECONDS = 30
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
