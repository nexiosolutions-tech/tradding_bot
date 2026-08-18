"""Cross-asset relative strength comparison — spec 03/11 (14ª rodada). Research tool,
read-only: fetches BTCUSDT and ETHUSDT klines once, runs the exact walk-forward backtest
already validated for BTCUSDT (specs/11) with and without eth_relative_strength_pct on the
identical window, and reports folds_won/PF side by side — same ablation method as the
multi-timeframe features round (12ª rodada).

Usage:
    python scripts/run_cross_asset_comparison.py --days 90
"""

from __future__ import annotations

import argparse
import time

from tradingbot.ingestion.binance_rest import BinanceRestClient
from tradingbot.model.dataset import CROSS_ASSET_FEATURE_NAMES
from tradingbot.model.evaluation import evaluate_config

HORIZON_MINUTES = 45
ENTRY_PERCENTILE = 99.0


def _run(label, events, **kwargs):
    result = evaluate_config(
        events,
        horizon_minutes=HORIZON_MINUTES,
        entry_percentile=ENTRY_PERCENTILE,
        n_splits=5,
        min_trades=15,
        use_regime_filter=False,
        **kwargs,
    )
    print(f"=== {label} ===")
    for f in result.folds:
        print(f"  fold {f.fold_index}: pf={f.profit_factor:.2f} trades={f.num_trades} dd={f.max_drawdown_pct:.1%} won={f.won}")
    print(
        f"folds_won={result.folds_won}/{result.folds_total} mean_pf={result.mean_profit_factor:.2f} "
        f"min_pf={result.min_profit_factor:.2f} label_rate={result.label_rate:.2%}\n"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - args.days * 24 * 60 * 60 * 1000

    client = BinanceRestClient()
    print(f"Buscando BTCUSDT 1m para os últimos {args.days} dia(s)...")
    btc_events = client.fetch_klines("BTCUSDT", "1m", start_ms, end_ms)
    print(f"{len(btc_events)} candles de BTCUSDT.")
    print(f"Buscando ETHUSDT 1m para os últimos {args.days} dia(s)...")
    eth_events = client.fetch_klines("ETHUSDT", "1m", start_ms, end_ms)
    print(f"{len(eth_events)} candles de ETHUSDT.\n")

    merged_events = sorted(btc_events + eth_events, key=lambda e: e.exchange_ts)

    _run("SEM força relativa cross-asset (baseline, só BTCUSDT)", btc_events)
    _run(
        "COM força relativa cross-asset (BTC+ETH, mesma janela)",
        merged_events,
        feature_names=CROSS_ASSET_FEATURE_NAMES,
        reference_symbol="ETHUSDT",
    )


if __name__ == "__main__":
    main()
