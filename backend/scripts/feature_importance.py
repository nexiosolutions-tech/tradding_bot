"""Fase 2 diagnostic (spec 04/11): SHAP feature importance for the walk-forward model —
motivated by six rounds of feature/target/threshold iteration (specs/11 roadmap) that
still haven't closed the gap to the promotion criteria (specs/07). Answers "what is the
model actually using?", computed on held-out rows from the final walk-forward fold (never
seen during training/calibration) — SHAP on the training set would just describe what the
model memorized, not what it generalizes on.

Usage:
    python scripts/feature_importance.py --symbol BTCUSDT --interval 1m --days 90 \
        --horizon-minutes 45 --entry-percentile 99
"""

from __future__ import annotations

import argparse
import time

import numpy as np
import shap

from tradingbot.ingestion.binance_rest import BinanceRestClient
from tradingbot.model.dataset import MODEL_FEATURE_NAMES, TargetConfig, build_dataset
from tradingbot.model.training import ModelConfig, split_fit_calibration, train_model, walk_forward_splits

STOP_LOSS_PCT = 0.015
MOVE_THRESHOLD_PCT = 0.008  # 2026-07-31 recalibration — held fixed, consistent with the other Fase 2 scripts


def _to_matrix(rows, feature_names: tuple[str, ...] = MODEL_FEATURE_NAMES) -> np.ndarray:
    return np.array([[r.features[name] for name in feature_names] for r in rows])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--horizon-minutes", type=int, default=45)
    parser.add_argument("--move-threshold-pct", type=float, default=MOVE_THRESHOLD_PCT)
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

    target_config = TargetConfig(
        horizon_minutes=args.horizon_minutes,
        move_threshold_pct=args.move_threshold_pct,
        stop_loss_pct=STOP_LOSS_PCT,
    )
    rows = build_dataset(events, target_config)
    print(f"Built {len(rows)} labeled rows (label=1 rate: {sum(r.label for r in rows) / len(rows):.1%}).")

    # Last fold — most training data, the same one train_model.py would actually save if
    # this config cleared the promotion gate.
    *_, (train_rows, test_rows) = walk_forward_splits(rows, n_splits=args.n_splits)
    fit_rows, _ = split_fit_calibration(train_rows, calibration_fraction=0.2)
    model = train_model(fit_rows, ModelConfig())
    print(f"Modelo treinado em {len(fit_rows)} linhas; explicando {len(test_rows)} linhas fora da amostra (fold final).\n")

    x_test = _to_matrix(test_rows)
    explainer = shap.TreeExplainer(model.booster)
    shap_values = explainer.shap_values(x_test)
    # Some SHAP/LightGBM version combos return a list [class0, class1] for a binary
    # classifier; others return the positive class directly as a 2D array — normalize.
    if isinstance(shap_values, list):
        shap_values = shap_values[1]

    mean_abs = np.abs(shap_values).mean(axis=0)
    # Correlation between a feature's own value and its SHAP contribution — positive means
    # "higher value pushes the prediction up", negative the opposite (same signal a SHAP
    # summary plot's color axis shows, without needing a plot).
    direction = np.array(
        [np.corrcoef(x_test[:, i], shap_values[:, i])[0, 1] if np.std(x_test[:, i]) > 0 else 0.0 for i in range(x_test.shape[1])]
    )
    order = np.argsort(-mean_abs)

    print(f"{'feature':<22}{'|SHAP| médio':>14}{'direção (corr)':>16}")
    for i in order:
        name = MODEL_FEATURE_NAMES[i]
        print(f"{name:<22}{mean_abs[i]:>14.5f}{direction[i]:>16.2f}")


if __name__ == "__main__":
    main()
