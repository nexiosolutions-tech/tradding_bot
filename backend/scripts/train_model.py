"""Fase 2 exit-criterion script (spec 11): fetch real historical klines, build the labeled
dataset (spec 04), walk-forward train a LightGBM baseline, and evaluate the candidate
against the Fase 1 placeholder strategy fold by fold (spec 07). Promotes and saves a model
artifact only if the candidate beats the baseline in every fold.

Usage:
    python scripts/train_model.py --symbol BTCUSDT --interval 1m --days 45
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from tradingbot.backtesting.strategy import RsiBollingerPlaceholderStrategy
from tradingbot.ingestion.binance_rest import BinanceRestClient
from tradingbot.model.dataset import TargetConfig, build_dataset
from tradingbot.model.promotion import PromotionCriteria, decide_promotion, evaluate_fold
from tradingbot.model.strategy import ModelStrategy
from tradingbot.model.training import ModelConfig, choose_thresholds, split_fit_calibration, train_model, walk_forward_splits
from tradingbot.model.versioning import save_model

RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"
MODELS_DIR = Path(__file__).resolve().parents[2] / "results" / "models"

WARMUP_PREFIX_BARS = 40
STOP_LOSS_PCT = 0.015  # same as the Fase 1 placeholder, for a fair cost/risk comparison


def _events_in_ts_range(events, start_ts, end_ts):
    return [e for e in events if start_ts <= e.exchange_ts <= end_ts]


def _warmup_prefix(events, before_ts, n=WARMUP_PREFIX_BARS):
    prior = [e for e in events if e.exchange_ts < before_ts]
    return prior[-n:]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--days", type=int, default=45)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--horizon-minutes", type=int, default=15)
    parser.add_argument("--move-threshold-pct", type=float, default=0.008)
    parser.add_argument("--entry-percentile", type=float, default=80.0)
    parser.add_argument("--exit-percentile", type=float, default=50.0)
    parser.add_argument("--min-trades", type=int, default=15)
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

    target_config = TargetConfig(
        horizon_minutes=args.horizon_minutes,
        move_threshold_pct=args.move_threshold_pct,
        stop_loss_pct=STOP_LOSS_PCT,
    )
    rows = build_dataset(events, target_config)
    print(f"Built {len(rows)} labeled rows (label=1 rate: {sum(r.label for r in rows) / len(rows):.1%}).")

    model_config = ModelConfig()
    criteria = PromotionCriteria(min_trades=args.min_trades)
    fold_results = []
    last_model = None
    last_thresholds = None

    for fold_index, (train_rows, test_rows) in enumerate(
        walk_forward_splits(rows, n_splits=args.n_splits)
    ):
        fit_rows, calib_rows = split_fit_calibration(train_rows, calibration_fraction=0.2)
        model = train_model(fit_rows, model_config, calibration_fraction=0.2)
        entry_threshold, exit_threshold = choose_thresholds(
            model, calib_rows, entry_percentile=args.entry_percentile, exit_percentile=args.exit_percentile
        )

        candidate = ModelStrategy(
            model=model,
            entry_threshold=entry_threshold,
            exit_threshold=exit_threshold,
            stop_loss_pct=STOP_LOSS_PCT,
        )
        baseline = RsiBollingerPlaceholderStrategy(stop_loss_pct=STOP_LOSS_PCT)

        test_start_ts = test_rows[0].knowledge_ts
        test_end_ts = test_rows[-1].knowledge_ts
        fold_events = _events_in_ts_range(events, test_start_ts, test_end_ts)
        warmup_events = _warmup_prefix(events, test_start_ts)

        result = evaluate_fold(
            fold_index, candidate, baseline, fold_events, criteria, warmup_events=warmup_events
        )
        fold_results.append(result)
        last_model, last_thresholds = model, (entry_threshold, exit_threshold)

        print(
            f"Fold {fold_index}: candidate pf={result.candidate_metrics.profit_factor:.2f} "
            f"trades={result.candidate_metrics.num_trades} dd={result.candidate_metrics.max_drawdown_pct:.1%} | "
            f"baseline pf={result.baseline_metrics.profit_factor:.2f} "
            f"trades={result.baseline_metrics.num_trades} dd={result.baseline_metrics.max_drawdown_pct:.1%} "
            f"-> {'PROMOVE' if result.candidate_wins else 'rejeita'} ({result.reason})"
        )

    promoted = decide_promotion(fold_results)
    print(f"\nDecisão final: {'PROMOVER' if promoted else 'NÃO promover'} — "
          f"{sum(r.candidate_wins for r in fold_results)}/{len(fold_results)} folds vencidos.")

    if not promoted:
        print("Modelo não superou o baseline em todos os folds — nenhuma versão será salva.")
        return

    entry_threshold, exit_threshold = last_thresholds
    version = f"{args.symbol}_{args.interval}_{end_ms}"
    version_dir = save_model(
        output_dir=MODELS_DIR,
        version=version,
        model=last_model,
        target_config=target_config,
        model_config=model_config,
        entry_threshold=entry_threshold,
        exit_threshold=exit_threshold,
        stop_loss_pct=STOP_LOSS_PCT,
        validation_summary={
            "folds_won": sum(r.candidate_wins for r in fold_results),
            "folds_total": len(fold_results),
            "fold_profit_factors": [r.candidate_metrics.profit_factor for r in fold_results],
        },
    )
    print(f"Modelo promovido e salvo em {version_dir}")


if __name__ == "__main__":
    main()
