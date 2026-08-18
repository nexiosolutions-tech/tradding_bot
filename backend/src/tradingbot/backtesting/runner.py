"""Runs a backtest end-to-end against real Binance klines and persists the report — spec 07/08.
Shared by scripts/run_backtest.py (CLI) and the dashboard's POST /api/backtests/run (spec 08),
so both paths produce identical reports for the same inputs instead of drifting apart."""

from __future__ import annotations

import time
from pathlib import Path

from tradingbot.backtesting.costs import FeeModel, SlippageModel
from tradingbot.backtesting.engine import BacktestEngine
from tradingbot.backtesting.report import save_report
from tradingbot.backtesting.strategy import RsiBollingerPlaceholderStrategy
from tradingbot.ingestion.binance_rest import BinanceRestClient
from tradingbot.risk.manager import RiskConfig


class NoKlinesFetchedError(RuntimeError):
    """Binance returned no closed klines for the requested symbol/interval/window."""


def run_and_save_backtest(
    results_dir: Path,
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    days: int = 7,
    initial_capital: float = 10_000.0,
    testnet: bool = False,
) -> tuple[Path, int]:
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 60 * 60 * 1000

    client = BinanceRestClient(testnet=testnet)
    events = client.fetch_klines(symbol, interval, start_ms, end_ms)
    if not events:
        raise NoKlinesFetchedError(
            f"nenhuma kline retornada para {symbol} {interval} nos últimos {days} dia(s)"
        )

    engine = BacktestEngine(
        strategy=RsiBollingerPlaceholderStrategy(),
        risk_config=RiskConfig(),
        fee_model=FeeModel(),
        slippage_model=SlippageModel(),
        initial_capital=initial_capital,
    )
    engine.run(events)

    run_name = f"{symbol}_{interval}_{days}d_{end_ms}"
    run_dir = save_report(engine, results_dir, run_name)
    return run_dir, len(events)
