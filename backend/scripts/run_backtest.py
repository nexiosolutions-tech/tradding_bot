"""Fase 1 exit-criterion script (spec 11): fetch real historical klines from Binance and run
the full event-driven backtest end to end, producing a report under results/.

Usage:
    python scripts/run_backtest.py --symbol BTCUSDT --interval 1m --days 7
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from tradingbot.backtesting.costs import FeeModel, SlippageModel
from tradingbot.backtesting.engine import BacktestEngine
from tradingbot.backtesting.report import save_report
from tradingbot.backtesting.strategy import RsiBollingerPlaceholderStrategy
from tradingbot.ingestion.binance_rest import BinanceRestClient
from tradingbot.risk.manager import RiskConfig

RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--initial-capital", type=float, default=10_000.0)
    parser.add_argument("--testnet", action="store_true")
    args = parser.parse_args()

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - args.days * 24 * 60 * 60 * 1000

    print(f"Fetching {args.symbol} {args.interval} klines for the last {args.days} day(s)...")
    client = BinanceRestClient(testnet=args.testnet)
    events = client.fetch_klines(args.symbol, args.interval, start_ms, end_ms)
    print(f"Fetched {len(events)} closed klines.")

    if not events:
        print("No data returned — aborting.")
        return

    engine = BacktestEngine(
        strategy=RsiBollingerPlaceholderStrategy(),
        risk_config=RiskConfig(),
        fee_model=FeeModel(),
        slippage_model=SlippageModel(),
        initial_capital=args.initial_capital,
    )
    engine.run(events)

    run_name = f"{args.symbol}_{args.interval}_{args.days}d_{end_ms}"
    run_dir = save_report(engine, RESULTS_DIR, run_name)
    print(f"Report written to {run_dir}")
    print((run_dir / "report.md").read_text())


if __name__ == "__main__":
    main()
