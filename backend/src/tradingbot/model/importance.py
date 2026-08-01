"""SHAP feature importance — spec 04/11 diagnostic (2026-08-01), and a tool the Fase 5
agentic loop (spec 09) can call. Computed on held-out rows from the final walk-forward
fold only — SHAP on the training set would describe memorization, not generalization.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shap

from tradingbot.ingestion.schema import MarketEvent
from tradingbot.model.dataset import MODEL_FEATURE_NAMES, TargetConfig, build_dataset
from tradingbot.model.training import ModelConfig, split_fit_calibration, train_model, walk_forward_splits

STOP_LOSS_PCT = 0.015


@dataclass(frozen=True)
class FeatureImportance:
    name: str
    mean_abs_shap: float
    # Correlation between a feature's own value and its SHAP contribution — positive means
    # "higher value pushes the prediction up", negative the opposite (same signal a SHAP
    # summary plot's color axis shows, without needing a plot). 0.0 when the feature had no
    # variance in the explained rows.
    direction_corr: float


def _to_matrix(rows, feature_names: tuple[str, ...] = MODEL_FEATURE_NAMES) -> np.ndarray:
    return np.array([[r.features[name] for name in feature_names] for r in rows])


def compute_feature_importance(
    events: list[MarketEvent],
    horizon_minutes: int,
    move_threshold_pct: float = 0.008,
    n_splits: int = 5,
) -> tuple[FeatureImportance, ...]:
    """Trains on the final walk-forward fold's fit rows, explains the model's held-out test
    rows, and returns features sorted by importance (most important first)."""
    target_config = TargetConfig(
        horizon_minutes=horizon_minutes, move_threshold_pct=move_threshold_pct, stop_loss_pct=STOP_LOSS_PCT
    )
    rows = build_dataset(events, target_config)

    *_, (train_rows, test_rows) = walk_forward_splits(rows, n_splits=n_splits)
    fit_rows, _ = split_fit_calibration(train_rows, calibration_fraction=0.2)
    model = train_model(fit_rows, ModelConfig())

    x_test = _to_matrix(test_rows)
    explainer = shap.TreeExplainer(model.booster)
    shap_values = explainer.shap_values(x_test)
    # Some SHAP/LightGBM version combos return a list [class0, class1] for a binary
    # classifier; others return the positive class directly as a 2D array — normalize.
    if isinstance(shap_values, list):
        shap_values = shap_values[1]

    mean_abs = np.abs(shap_values).mean(axis=0)
    # A feature the model never split on has constant (usually all-zero) SHAP values —
    # np.corrcoef divides by each array's own stddev, so a constant SHAP column (zero
    # variance) yields nan regardless of how much the feature itself varies. Guard both.
    direction = np.array(
        [
            np.corrcoef(x_test[:, i], shap_values[:, i])[0, 1]
            if np.std(x_test[:, i]) > 0 and np.std(shap_values[:, i]) > 0
            else 0.0
            for i in range(x_test.shape[1])
        ]
    )
    order = np.argsort(-mean_abs)
    return tuple(
        FeatureImportance(name=MODEL_FEATURE_NAMES[i], mean_abs_shap=float(mean_abs[i]), direction_corr=float(direction[i]))
        for i in order
    )
