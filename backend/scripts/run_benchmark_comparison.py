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

Two caveats the printed report states explicitly rather than leaving implicit, so a reader
three months from now doesn't mistake either comparison for a fair one at face value:
- **Cost asymmetry**: buy-and-hold enters/exits for free in this comparison (a single mark-
  to-market, no simulated order); the candidate pays real fees/slippage on every trade
  (backtesting/costs.py). This biases the comparison *against* the candidate, which is the
  safe direction, but it must stay visible instead of silently favoring buy-and-hold.
- **Exposure**: buy-and-hold is 100% exposed to price risk by definition, flat is 0%, and
  the candidate is whatever BacktestMetrics.exposure_pct comes out to (usually well under
  100%) — part of any return/risk gap between them is explained by how much of the period
  each was even in the market, not by strategy skill alone.

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


def _fmt(m: BacktestMetrics, exposure_override: float | None = None) -> str:
    exposure = m.exposure_pct if exposure_override is None else exposure_override
    return (
        f"trades={m.num_trades} pf={m.profit_factor:.2f} return={m.total_return_pct:+.1%} "
        f"exposure={exposure:.1%} dd={m.max_drawdown_pct:.1%} vol/barra={m.volatility_pct:.2%} "
        f"ret/dd={m.return_over_drawdown:.2f} ret/vol_não_anualizado={m.return_over_volatility:.2f}"
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
    parser.add_argument("--label-rate-floor-multiple", type=float, default=3.0)
    parser.add_argument("--exit-hysteresis-stdevs", type=float, default=3.0)
    parser.add_argument("--regime-calib-min-trades", type=int, default=5)
    parser.add_argument("--initial-capital", type=float, default=10_000.0)
    parser.add_argument("--testnet", action="store_true")
    parser.add_argument(
        "--start-ms", type=int, default=None,
        help="Fixed window start (ms epoch). --days is relative to time.time() otherwise, "
        "which makes two runs minutes apart pull different data and produce non-comparable "
        "fold splits (2026-08-19 finding) — pass this (with --end-ms) for a reproducible run.",
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

    print(
        "\nNOTA: buy&hold não paga taxa/slippage nesta comparação (o candidato paga) — "
        "viés a favor do buy&hold, do lado seguro, mas explícito para não ser lido como "
        "comparação justa. ret/vol_não_anualizado usa volatilidade por barra do candle "
        "usado (não anualizada) — não comparável a um Sharpe publicado sem converter.\n"
    )

    target_config = TargetConfig(
        horizon_minutes=args.horizon_minutes,
        move_threshold_pct=args.move_threshold_pct,
        stop_loss_pct=STOP_LOSS_PCT,
    )
    rows = build_dataset(events, target_config)
    model_config = ModelConfig()

    fold_reports = []
    for fold_index, (train_rows, test_rows) in enumerate(
        walk_forward_splits(rows, n_splits=args.n_splits, purge_bars=target_config.horizon_bars)
    ):
        if not train_rows or not test_rows:
            continue
        fit_rows, calib_rows = split_fit_calibration(train_rows, calibration_fraction=0.2)
        model = train_model(fit_rows, model_config, calibration_fraction=0.2)
        entry_threshold, exit_threshold = choose_thresholds(
            model,
            calib_rows,
            entry_percentile=args.entry_percentile,
            label_rate_floor_multiple=args.label_rate_floor_multiple,
            exit_hysteresis_stdevs=args.exit_hysteresis_stdevs,
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
        # buy-and-hold/flat aren't built from ClosedTrade objects, so exposure_pct as
        # computed by compute_metrics would read 0.0 for both — overridden here with their
        # true exposure by definition (always in market / never in market).
        print(f"  buy&hold  : {_fmt(buy_hold_metrics, exposure_override=1.0)}")
        print(f"  flat      : {_fmt(flat_metrics, exposure_override=0.0)}")

        fold_reports.append(
            {
                "fold_index": fold_index,
                "candidate": asdict(candidate_metrics),
                "buy_and_hold": {**asdict(buy_hold_metrics), "exposure_pct": 1.0},
                "flat": {**asdict(flat_metrics), "exposure_pct": 0.0},
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

    report = {
        "window": {"start_ms": start_ms, "end_ms": end_ms, "symbol": args.symbol, "interval": args.interval},
        "caveats": {
            "cost_asymmetry": "buy_and_hold pays no fees/slippage in this comparison; "
            "the candidate pays real fees/slippage on every trade (backtesting/costs.py) "
            "— biases the comparison against the candidate, the safe direction, but must "
            "stay explicit.",
            "return_over_volatility": "computed from bar-level (not annualized) "
            "volatility — not comparable to a published annualized Sharpe ratio.",
        },
        "folds": fold_reports,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"benchmark_comparison_{args.symbol}_{end_ms}.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"Relatório salvo em {out_path}")


if __name__ == "__main__":
    main()
