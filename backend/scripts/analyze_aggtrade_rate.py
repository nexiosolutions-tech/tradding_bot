"""Reads back the samples scripts/measure_aggtrade_rate.py collected and reports the
peak (p95/p99), not the average — a single busy 5-minute window decides whether REST
polling can be aggtrade-capture's primary source, not the typical case. Run this after
measure_aggtrade_rate.py has been collecting for at least one full ~24h cycle. See
changes/2026-08-18-captura-aggtrade-fluxo-ordens.md.

Usage:
    python scripts/analyze_aggtrade_rate.py
"""

from __future__ import annotations

import os

from tradingbot.persistence.db import get_session_factory
from tradingbot.persistence.repository import list_aggtrade_rate_samples


def _percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile (no numpy dependency for a one-off script)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lower = int(k)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (k - lower)


def main() -> None:
    symbol = os.environ.get("SYMBOL", "BTCUSDT")
    session_factory = get_session_factory(os.environ.get("DATABASE_URL"))
    session = session_factory()
    samples = list_aggtrade_rate_samples(session, symbol=symbol)

    if not samples:
        print("Nenhuma amostra ainda — deixe scripts/measure_aggtrade_rate.py rodando.")
        return

    span_hours = (samples[-1].ts - samples[0].ts) / (1000 * 60 * 60)
    rates = [s.trades_per_second for s in samples]
    latencies = [s.latency_ms for s in samples]
    weights = [s.used_weight_1m for s in samples if s.used_weight_1m is not None]

    p50_rate = _percentile(rates, 0.50)
    p95_rate = _percentile(rates, 0.95)
    p99_rate = _percentile(rates, 0.99)
    peak_rate = max(rates)
    p95_latency = _percentile(latencies, 0.95)
    peak_weight = max(weights) if weights else None

    seconds_covered_at_p99 = 1000 / p99_rate if p99_rate else float("inf")
    serial_latency_seconds = p95_latency / 1000
    headroom = seconds_covered_at_p99 / serial_latency_seconds if serial_latency_seconds else float("inf")

    print(f"Símbolo: {symbol}")
    print(f"Amostras: {len(samples)}, cobrindo {span_hours:.1f}h")
    print(f"Taxa de chegada (trades/s): p50={p50_rate:.1f} p95={p95_rate:.1f} p99={p99_rate:.1f} pico={peak_rate:.1f}")
    print(f"Latência da chamada (ms): p95={p95_latency:.0f}")
    if peak_weight is not None:
        print(f"Peso usado (X-MBX-USED-WEIGHT-1M), pico observado: {peak_weight}/6000 por minuto")
    print(f"Segundos de mercado cobertos por chamada de 1000 trades, no p99 de taxa: {seconds_covered_at_p99:.2f}s")
    print(f"Folga (cobertura / latência serial, p95): {headroom:.1f}x")
    print()
    if headroom >= 3.0:
        print("Folga confortável (>=3x) no pico observado — polling como fonte primária é defensável.")
    else:
        print(
            "Folga insuficiente (<3x) no pico observado — polling não deve ser fonte primária "
            "sozinho; arquivo diário + polling como cauda recente é o desenho mais seguro."
        )


if __name__ == "__main__":
    main()
