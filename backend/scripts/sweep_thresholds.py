"""Fase 2 hyperparameter sweep (spec 04/07): fetches historical klines once, then varies
entry_percentile and horizon_minutes over a grid, reusing the same walk-forward pipeline
as train_model.py for each combination. Exists because a single train_model.py run only
tests one point in this space — after the 2026-07-31 target recalibration dropped the
label=1 rate to ~1%, entry_percentile=80 (tuned for a much higher base rate) was
suspected to be badly miscalibrated, and this is cheaper than N manual CLI runs (each of
which would re-fetch the same 45 days of klines from Binance).

Usage:
    python scripts/sweep_thresholds.py --symbol BTCUSDT --interval 1m --days 45
"""

from __future__ import annotations

import argparse
import time

from tradingbot.backtesting.strategy import RsiBollingerPlaceholderStrategy
from tradingbot.ingestion.binance_rest import BinanceRestClient
from tradingbot.model.dataset import TargetConfig, build_dataset
from tradingbot.model.promotion import PromotionCriteria, evaluate_fold
from tradingbot.model.strategy import ModelStrategy
from tradingbot.model.training import ModelConfig, choose_thresholds, split_fit_calibration, train_model, walk_forward_splits

WARMUP_PREFIX_BARS = 40
STOP_LOSS_PCT = 0.015
MOVE_THRESHOLD_PCT = 0.008  # 2026-07-31 recalibration — held fixed across this sweep

ENTRY_PERCENTILE_GRID = (80.0, 90.0, 95.0, 99.0)
HORIZON_MINUTES_GRID = (10, 15, 30)


def _events_in_ts_range(events, start_ts, end_ts):
    return [e for e in events if start_ts <= e.exchange_ts <= end_ts]


def _warmup_prefix(events, before_ts, n=WARMUP_PREFIX_BARS):
    prior = [e for e in events if e.exchange_ts < before_ts]
    return prior[-n:]


def _run_combo(events, horizon_minutes: float, entry_percentile: float, n_splits: int, min_trades: int):
    target_config = TargetConfig(
        horizon_minutes=horizon_minutes,
        move_threshold_pct=MOVE_THRESHOLD_PCT,
        stop_loss_pct=STOP_LOSS_PCT,
    )
    rows = build_dataset(events, target_config)
    label_rate = sum(r.label for r in rows) / len(rows) if rows else 0.0

    model_config = ModelConfig()
    criteria = PromotionCriteria(min_trades=min_trades)
    fold_results = []

    for fold_index, (train_rows, test_rows) in enumerate(walk_forward_splits(rows, n_splits=n_splits)):
        fit_rows, calib_rows = split_fit_calibration(train_rows, calibration_fraction=0.2)
        model = train_model(fit_rows, model_config, calibration_fraction=0.2)
        entry_threshold, exit_threshold = choose_thresholds(
            model, calib_rows, entry_percentile=entry_percentile, exit_percentile=50.0
        )
        candidate = ModelStrategy(model=model, entry_threshold=entry_threshold, exit_threshold=exit_threshold, stop_loss_pct=STOP_LOSS_PCT)
        baseline = RsiBollingerPlaceholderStrategy(stop_loss_pct=STOP_LOSS_PCT)

        test_start_ts = test_rows[0].knowledge_ts
        test_end_ts = test_rows[-1].knowledge_ts
        fold_events = _events_in_ts_range(events, test_start_ts, test_end_ts)
        warmup_events = _warmup_prefix(events, test_start_ts)

        result = evaluate_fold(fold_index, candidate, baseline, fold_events, criteria, warmup_events=warmup_events)
        fold_results.append(result)

    pfs = [r.candidate_metrics.profit_factor for r in fold_results]
    return {
        "horizon_minutes": horizon_minutes,
        "entry_percentile": entry_percentile,
        "label_rate": label_rate,
        "folds_won": sum(r.candidate_wins for r in fold_results),
        "folds_total": len(fold_results),
        "mean_pf": sum(pfs) / len(pfs) if pfs else 0.0,
        "min_pf": min(pfs) if pfs else 0.0,
        "min_trades_seen": min((r.candidate_metrics.num_trades for r in fold_results), default=0),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--days", type=int, default=45)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--min-trades", type=int, default=15)
    parser.add_argument("--testnet", action="store_true")
    args = parser.parse_args()

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - args.days * 24 * 60 * 60 * 1000

    print(f"Fetching {args.symbol} {args.interval} klines for the last {args.days} day(s)...")
    client = BinanceRestClient(testnet=args.testnet)
    events = client.fetch_klines(args.symbol, args.interval, start_ms, end_ms)
    print(f"Fetched {len(events)} closed klines.\n")
    if not events:
        print("No data returned — aborting.")
        return

    results = []
    for horizon_minutes in HORIZON_MINUTES_GRID:
        for entry_percentile in ENTRY_PERCENTILE_GRID:
            row = _run_combo(events, horizon_minutes, entry_percentile, args.n_splits, args.min_trades)
            results.append(row)
            print(
                f"horizon={row['horizon_minutes']:>3}min entry_pct={row['entry_percentile']:>5.1f} "
                f"label_rate={row['label_rate']:.1%} folds_won={row['folds_won']}/{row['folds_total']} "
                f"mean_pf={row['mean_pf']:.2f} min_pf={row['min_pf']:.2f} min_trades={row['min_trades_seen']}"
            )

    results.sort(key=lambda r: (r["min_pf"], r["mean_pf"]), reverse=True)
    print("\n=== Melhores combinações (ordenado por pior fold, depois média) ===")
    for row in results[:5]:
        print(
            f"horizon={row['horizon_minutes']:>3}min entry_pct={row['entry_percentile']:>5.1f} "
            f"label_rate={row['label_rate']:.1%} folds_won={row['folds_won']}/{row['folds_total']} "
            f"mean_pf={row['mean_pf']:.2f} min_pf={row['min_pf']:.2f}"
        )


if __name__ == "__main__":
    main()
