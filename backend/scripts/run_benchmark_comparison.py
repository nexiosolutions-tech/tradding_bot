"""Benchmark comparison — spec 07/11 (statistical-rigor thread, 2026-08-19). Compares the
candidate (trained model + regime filter, same walk-forward pipeline as train_model.py)
against two trivial benchmarks on each out-of-sample fold: buy-and-hold and flat (do
nothing). Beating RsiBollingerPlaceholderStrategy (promotion.py's baseline) is necessary
but not sufficient — a candidate that only beats a structurally weak baseline while still
losing to just holding the asset, or carrying more volatility than holding cash, has no
real edge. Comparison is risk-adjusted (return/drawdown, return/volatility via
backtesting/metrics.py), not just raw return vs. hold, and includes the "always flat"
baseline.

Runs per fold, not on the aggregate period — an aggregate figure can hide a candidate
that's only ahead because of one regime (see promotion.py's own module docstring: "winning
on average across folds is not enough").

Usage:
    python scripts/run_benchmark_comparison.py --symbol BTCUSDT --interval 1m --days 45
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from tradingbot.backtesting.metrics import BacktestMetrics, buy_and_hold_equity_curve, compute_metrics, flat_equity_curve
from tradingbot.ingestion.binance_rest import BinanceRestClient
from tradingbot.model.dataset import TargetConfig, build_dataset
from tradingbot.model.promotion import run_backtest
from tradingbot.model.strategy import ModelStrategy, RegimeFilteredStrategy, choose_regime_threshold
from tradingbot.model.training import ModelConfig, choose_thresholds, split_fit_calibration, train_model, walk_forward_splits

RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"
WARMUP_PREFIX_BARS = 40
STOP_LOSS_PCT = 0.015  # same as train_model.py — fair cost/risk comparison


def _events_in_ts_range(events, start_ts, end_ts):
    return [e for e in events if start_ts <= e.exchange_ts <= end_ts]


def _warmup_prefix(events, before_ts, n=WARMUP_PREFIX_BARS):
    prior = [e for e in events if e.exchange_ts < before_ts]
    return prior[-n:]


def _fmt(m: BacktestMetrics) -> str:
    return (
        f"trades={m.num_trades} pf={m.profit_factor:.2f} return={m.total_return_pct:+.1%} "
        f"dd={m.max_drawdown_pct:.1%} vol={m.volatility_pct:.2%} "
        f"ret/dd={m.return_over_drawdown:.2f} ret/vol={m.return_over_volatility:.2f}"
    )


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
    parser.add_argument("--regime-calib-min-trades", type=int, default=5)
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

    target_config = TargetConfig(
        horizon_minutes=args.horizon_minutes,
        move_threshold_pct=args.move_threshold_pct,
        stop_loss_pct=STOP_LOSS_PCT,
    )
    rows = build_dataset(events, target_config)
    model_config = ModelConfig()

    fold_reports = []
    for fold_index, (train_rows, test_rows) in enumerate(walk_forward_splits(rows, n_splits=args.n_splits)):
        if not train_rows or not test_rows:
            continue
        fit_rows, calib_rows = split_fit_calibration(train_rows, calibration_fraction=0.2)
        model = train_model(fit_rows, model_config, calibration_fraction=0.2)
        entry_threshold, exit_threshold = choose_thresholds(
            model, calib_rows, entry_percentile=args.entry_percentile, exit_percentile=args.exit_percentile
        )
        model_strategy = ModelStrategy(
            model=model, entry_threshold=entry_threshold, exit_threshold=exit_threshold, stop_loss_pct=STOP_LOSS_PCT
        )

        calib_start_ts = calib_rows[0].knowledge_ts
        calib_end_ts = calib_rows[-1].knowledge_ts
        calib_events = _events_in_ts_range(events, calib_start_ts, calib_end_ts)
        calib_warmup_events = _warmup_prefix(events, calib_start_ts)
        min_trend_pct = choose_regime_threshold(
            model_strategy, calib_events, min_trades=args.regime_calib_min_trades, warmup_events=calib_warmup_events
        )
        candidate = RegimeFilteredStrategy(inner=model_strategy, min_trend_pct=min_trend_pct)

        test_start_ts = test_rows[0].knowledge_ts
        test_end_ts = test_rows[-1].knowledge_ts
        fold_events = _events_in_ts_range(events, test_start_ts, test_end_ts)
        warmup_events = _warmup_prefix(events, test_start_ts)

        candidate_metrics = run_backtest(
            candidate, fold_events, initial_capital=args.initial_capital, warmup_events=warmup_events
        )
        buy_hold_metrics = compute_metrics(
            [], buy_and_hold_equity_curve(fold_events, args.initial_capital), initial_capital=args.initial_capital
        )
        flat_metrics = compute_metrics(
            [], flat_equity_curve(fold_events, args.initial_capital), initial_capital=args.initial_capital
        )

        print(f"\nFold {fold_index}:")
        print(f"  candidate : {_fmt(candidate_metrics)}")
        print(f"  buy&hold  : {_fmt(buy_hold_metrics)}")
        print(f"  flat      : {_fmt(flat_metrics)}")

        fold_reports.append(
            {
                "fold_index": fold_index,
                "candidate": asdict(candidate_metrics),
                "buy_and_hold": asdict(buy_hold_metrics),
                "flat": asdict(flat_metrics),
            }
        )

    if not fold_reports:
        print("Nenhum fold com dados suficientes — nada a comparar.")
        return

    beats_both = sum(
        1
        for r in fold_reports
        if r["candidate"]["return_over_drawdown"] >= r["buy_and_hold"]["return_over_drawdown"]
        and r["candidate"]["total_return_pct"] >= r["flat"]["total_return_pct"]
    )
    print(f"\nCandidato supera buy&hold (ret/dd) e flat (retorno) em {beats_both}/{len(fold_reports)} folds.")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"benchmark_comparison_{args.symbol}_{end_ms}.json"
    out_path.write_text(json.dumps(fold_reports, indent=2, default=str))
    print(f"Relatório salvo em {out_path}")


if __name__ == "__main__":
    main()
