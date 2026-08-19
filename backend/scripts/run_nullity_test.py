"""Nullity test — spec 07/11 (statistical-rigor thread, 2026-08-19). Runs the exact same
walk-forward harness train_model.py uses (model/evaluation.py::evaluate_config) against
the SAME real historical events and configuration, except the labels are a permutation of
themselves (evaluate_config's shuffle_labels=True) — by construction, there is no real
relationship left between any row's features and its label.

Expected result: the candidate wins zero folds. A fold won here is not evidence of a lucky
model — it's evidence the harness itself is leaking information (most likely a violation
of spec 03's anti-leakage invariant somewhere in the feature pipeline), and the fix belongs
in the harness, not in the strategy. That is the entire value of this test: taking a
positive result here seriously instead of shrugging it off as noise.

Usage:
    python scripts/run_nullity_test.py --symbol BTCUSDT --interval 1m --days 45
"""

from __future__ import annotations

import argparse
import time

from tradingbot.ingestion.binance_rest import BinanceRestClient
from tradingbot.model.evaluation import evaluate_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--days", type=int, default=45)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--horizon-minutes", type=int, default=15)
    parser.add_argument("--move-threshold-pct", type=float, default=0.008)
    parser.add_argument("--entry-percentile", type=float, default=80.0)
    parser.add_argument("--min-trades", type=int, default=15)
    parser.add_argument("--shuffle-seed", type=int, default=0)
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

    result = evaluate_config(
        events,
        horizon_minutes=args.horizon_minutes,
        entry_percentile=args.entry_percentile,
        move_threshold_pct=args.move_threshold_pct,
        n_splits=args.n_splits,
        min_trades=args.min_trades,
        shuffle_labels=True,
        shuffle_seed=args.shuffle_seed,
    )

    for fold in result.folds:
        status = "GANHOU (suspeito)" if fold.won else "perdeu (esperado)"
        print(
            f"Fold {fold.fold_index}: pf={fold.profit_factor:.2f} trades={fold.num_trades} "
            f"dd={fold.max_drawdown_pct:.1%} -> {status} ({fold.reason})"
        )

    print(
        f"\n{result.folds_won}/{result.folds_total} folds vencidos com labels embaralhados "
        f"(label_rate={result.label_rate:.1%})."
    )
    if result.folds_won == 0:
        print("Resultado esperado: nenhum alfa encontrado em labels embaralhados.")
    else:
        print(
            "ATENÇÃO: o pipeline encontrou 'alfa' em labels embaralhados — isso não é sorte, "
            "é evidência de vazamento no harness (spec 03). Investigue antes de confiar em "
            "qualquer resultado real de evaluate_config."
        )


if __name__ == "__main__":
    main()
