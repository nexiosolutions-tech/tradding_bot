"""Nullity test — spec 07/11 (statistical-rigor thread, 2026-08-19). Runs the exact same
walk-forward harness train_model.py uses (model/evaluation.py::run_nullity_test /
evaluate_config) against the SAME real historical events and configuration, once for real
and N times more with labels replaced by a fresh permutation of themselves each time — by
construction, there is no real relationship left between any row's features and its label
in the permuted runs. A single permutation says nothing about whether a result is typical
or a fluke of that one shuffle — N permutations build a null distribution, and the real
result's position in it is reported as an empirical p-value (fraction of permutations that
matched or beat the real mean profit factor).

Expected result: a high p-value (the real result looks unremarkable next to what pure
chance produces on this pipeline). A low p-value is not evidence of a lucky model — it's
evidence the harness itself is leaking information (most likely a violation of spec 03's
anti-leakage invariant somewhere in the feature pipeline), and the fix belongs in the
harness, not in the strategy. That is the entire value of this test: taking a positive
result here seriously instead of shrugging it off as noise.

Usage:
    python scripts/run_nullity_test.py --symbol BTCUSDT --interval 1m --days 45 --n-permutations 30
"""

from __future__ import annotations

import argparse
import time

from tradingbot.ingestion.binance_rest import BinanceRestClient
from tradingbot.model.evaluation import run_nullity_test


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
    parser.add_argument("--n-permutations", type=int, default=30)
    parser.add_argument("--base-seed", type=int, default=0)
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

    print(f"Rodando 1 avaliação real + {args.n_permutations} permutações (isso treina "
          f"{args.n_permutations + 1} modelos, pode levar um tempo)...")
    result = run_nullity_test(
        events,
        horizon_minutes=args.horizon_minutes,
        entry_percentile=args.entry_percentile,
        move_threshold_pct=args.move_threshold_pct,
        n_splits=args.n_splits,
        min_trades=args.min_trades,
        n_permutations=args.n_permutations,
        base_seed=args.base_seed,
    )

    print(f"\nReal: mean_profit_factor={result.real_mean_profit_factor:.3f} "
          f"({result.real_folds_won}/{result.real_folds_total} folds vencidos)")
    sorted_permuted = sorted(result.permuted_mean_profit_factors)
    print(
        f"Distribuição nula ({result.n_permutations} permutações): "
        f"min={sorted_permuted[0]:.3f} mediana={sorted_permuted[len(sorted_permuted) // 2]:.3f} "
        f"max={sorted_permuted[-1]:.3f}"
    )
    print(f"p-valor empírico: {result.p_value:.3f}")

    if result.p_value >= 0.05:
        print(
            "Resultado esperado: o resultado real não se distingue do que o acaso produz "
            "neste pipeline (p >= 0.05)."
        )
    else:
        print(
            "ATENÇÃO: o resultado real supera a esmagadora maioria das permutações com "
            "labels embaralhados (p < 0.05) — isso não é sorte, é evidência de vazamento "
            "no harness (spec 03). Investigue antes de confiar em qualquer resultado real "
            "de evaluate_config."
        )


if __name__ == "__main__":
    main()
