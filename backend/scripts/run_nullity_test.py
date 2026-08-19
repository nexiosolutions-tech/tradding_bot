"""Nullity test — spec 07/11 (statistical-rigor thread, 2026-08-19). Runs the exact same
walk-forward harness train_model.py uses (model/evaluation.py::run_nullity_test /
evaluate_config) against the SAME real historical events and configuration, once for real
and N times more with labels replaced by a fresh permutation of themselves each time — by
construction, there is no real relationship left between any row's features and its label
in the permuted runs. A single permutation says nothing about whether a result is typical
or a fluke of that one shuffle — N permutations build a null distribution, and the real
result's position in it is reported as an empirical p-value (fraction of permutations that
matched or beat the real total_pnl — summed across folds, never a mean of per-fold
profit_factor ratios, which degenerates to inf whenever any single fold has zero losing
trades).

Interpretation (corrected same day after shipping an inverted version — see
changes/2026-08-19-benchmark-e-teste-de-nulidade.md): tests H0 "the features carry no real
information about the label". A LOW p-value (real >> the null distribution) REJECTS H0 —
that is evidence of genuine predictive signal, the desired finding, not an alarm. Caveat,
not an alarm: this pattern is also consistent with lookahead leakage in feature/label
construction (spec 03's anti-leakage invariant, and the walk-forward purge —
model/training.py::walk_forward_splits' purge_bars) — worth a due-diligence check on a low
p-value, not because the test flagged something wrong. A HIGH p-value (real indistinguishable
from null) is not unconditionally "no signal" either: if some other mechanism (e.g. an exit
rule firing from score noise) destroys performance the same way regardless of label quality,
both real and permuted get strangled identically and the test loses power to detect a real
signal underneath — an unusually low null-distribution median is itself a symptom of this.

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
    parser.add_argument(
        "--start-ms", type=int, default=None,
        help="Fixed window start (ms epoch). --days is relative to time.time() otherwise, "
        "which makes two runs minutes apart pull different data and produce non-comparable "
        "fold splits (2026-08-19 finding) — pass this (with --end-ms) to match a specific "
        "run_benchmark_comparison.py window.",
    )
    parser.add_argument("--end-ms", type=int, default=None, help="Fixed window end (ms epoch); see --start-ms.")
    args = parser.parse_args()

    if (args.start_ms is None) != (args.end_ms is None):
        raise SystemExit("--start-ms and --end-ms must be given together")
    if args.end_ms is not None:
        end_ms, start_ms = args.end_ms, args.start_ms
    else:
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - args.days * 24 * 60 * 60 * 1000
    print(f"Janela: start_ms={start_ms} end_ms={end_ms} (passe ambos de volta via --start-ms/--end-ms para reproduzir)")

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

    print(f"\nReal: total_pnl={result.real_total_pnl:.2f} "
          f"(PF agregado={result.real_aggregate_profit_factor:.3f}, "
          f"{result.real_folds_won}/{result.real_folds_total} folds vencidos)")
    sorted_permuted = sorted(result.permuted_total_pnls)
    print(
        f"Distribuição nula ({result.n_permutations} permutações, total_pnl): "
        f"min={sorted_permuted[0]:.2f} mediana={sorted_permuted[len(sorted_permuted) // 2]:.2f} "
        f"max={sorted_permuted[-1]:.2f}"
    )
    print(f"p-valor empírico: {result.p_value:.3f}")

    if result.p_value < 0.05:
        print(
            "Sinal real (p < 0.05): o resultado real supera a esmagadora maioria das "
            "permutações com labels embaralhados — rejeita a hipótese nula de que as "
            "features não carregam informação sobre o label. É o resultado desejado, não "
            "um alarme. Ressalva de precaução (não porque o teste acusou algo): esse "
            "padrão também é compatível com vazamento de lookahead na construção de "
            "features/labels — vale conferir o invariante anti-vazamento (spec 03) e a "
            "purga na fronteira do walk-forward (walk_forward_splits, purge_bars) antes "
            "de confiar no número."
        )
    else:
        print(
            "Sem sinal detectável (p >= 0.05): o resultado real não se distingue do que o "
            "acaso produz neste pipeline. Não é conclusivo por si só se a mediana da "
            "distribuição nula estiver anormalmente baixa (abaixo do que entradas "
            "aleatórias líquidas de custo produziriam) — pode indicar que algum mecanismo "
            "(ex.: saída disparando por ruído) estrangula real e permutado por igual, "
            "mascarando sinal genuíno em vez de confirmar sua ausência."
        )


if __name__ == "__main__":
    main()
