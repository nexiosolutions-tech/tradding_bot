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

from tradingbot.ingestion.binance_rest import BinanceRestClient
from tradingbot.model.evaluation import evaluate_config

MOVE_THRESHOLD_PCT = 0.008  # 2026-07-31 recalibration — held fixed across this sweep

ENTRY_PERCENTILE_GRID = (80.0, 90.0, 95.0, 99.0)
HORIZON_MINUTES_GRID = (10, 15, 30)


def _run_combo(
    events,
    horizon_minutes: float,
    entry_percentile: float,
    n_splits: int,
    min_trades: int,
    use_regime_filter: bool = True,
    regime_calib_min_trades: int = 5,
):
    result = evaluate_config(
        events,
        horizon_minutes=horizon_minutes,
        entry_percentile=entry_percentile,
        move_threshold_pct=MOVE_THRESHOLD_PCT,
        n_splits=n_splits,
        min_trades=min_trades,
        use_regime_filter=use_regime_filter,
        regime_calib_min_trades=regime_calib_min_trades,
    )
    return {
        "horizon_minutes": horizon_minutes,
        "entry_percentile": entry_percentile,
        "label_rate": result.label_rate,
        "folds_won": result.folds_won,
        "folds_total": result.folds_total,
        "mean_pf": result.mean_profit_factor,
        "min_pf": result.min_profit_factor,
        "min_trades_seen": min((f.num_trades for f in result.folds), default=0),
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
