"""Fase 1 exit-criterion script (spec 11): fetch real historical klines from Binance and run
the full event-driven backtest end to end, producing a report under results/.

Usage:
    python scripts/run_backtest.py --symbol BTCUSDT --interval 1m --days 7
"""

from __future__ import annotations

import argparse
from pathlib import Path

from tradingbot.backtesting.runner import NoKlinesFetchedError, run_and_save_backtest

RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--initial-capital", type=float, default=10_000.0)
    parser.add_argument("--testnet", action="store_true")
    args = parser.parse_args()

    print(f"Fetching {args.symbol} {args.interval} klines for the last {args.days} day(s)...")
    try:
        run_dir, num_klines = run_and_save_backtest(
            RESULTS_DIR,
            symbol=args.symbol,
            interval=args.interval,
            days=args.days,
            initial_capital=args.initial_capital,
            testnet=args.testnet,
        )
    except NoKlinesFetchedError:
        print("No data returned — aborting.")
        return

    print(f"Fetched {num_klines} closed klines.")
    print(f"Report written to {run_dir}")
    print((run_dir / "report.md").read_text())


if __name__ == "__main__":
    main()
