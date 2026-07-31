"""Fase 4 standalone worker (spec 06) — an alternative to running the trading loop inside
the API service (see api/app.py), useful if the worker and the dashboard are later split
into two Railway services (spec 10). Same bootstrap, same Orchestrator either way.

The engine boots PAUSADO. Resuming it is a deliberate operator action via the API/dashboard
— this script does not auto-resume, on purpose.

Required environment variables:
    BINANCE_API_KEY, BINANCE_API_SECRET   — testnet keys unless BINANCE_TESTNET=false
    SYMBOL                                 (default BTCUSDT)
    DATABASE_URL                           (default: local sqlite under results/)

Usage:
    python scripts/run_live.py
"""

from __future__ import annotations

import asyncio
import sys

from tradingbot.execution.bootstrap import MissingCredentialsError, build_orchestrator
from tradingbot.ingestion.binance_ws import BinanceKlineStream


async def main() -> None:
    try:
        orchestrator = build_orchestrator()
    except MissingCredentialsError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    await orchestrator.reconcile_position_on_startup()

    print(
        f"Orquestrador pronto para {orchestrator.symbol} (estratégia: {orchestrator.strategy_version}). "
        f"Estado: {orchestrator.state.value}."
    )
    print("Boots PAUSADO por design — retome via a API/dashboard quando estiver pronto para operar.")

    stream = BinanceKlineStream(symbols=[orchestrator.symbol], interval="1m", testnet=True)
    async for event in stream:
        await orchestrator.on_event(event)


if __name__ == "__main__":
    asyncio.run(main())
