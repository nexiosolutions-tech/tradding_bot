"""Model training — spec 04. LightGBM baseline, calibrated so that a score of 0.7 means
roughly 70% historical hit rate, trained and validated with chronological splits only —
random cross-validation would leak future information into training.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np
from lightgbm import LGBMClassifier
from sklearn.isotonic import IsotonicRegression

from tradingbot.model.dataset import FEATURE_NAMES, DatasetRow


@dataclass(frozen=True)
class ModelConfig:
    num_leaves: int = 31
    learning_rate: float = 0.05
    n_estimators: int = 200
    min_child_samples: int = 30


@dataclass
class TrainedModel:
    booster: LGBMClassifier
    calibrator: IsotonicRegression
    feature_names: tuple[str, ...]

    def predict_proba(self, features: dict[str, float]) -> float:
        x = np.array([[features[name] for name in self.feature_names]])
        raw = float(self.booster.predict_proba(x)[0, 1])
        return float(self.calibrator.predict([raw])[0])

    def predict_proba_batch(self, rows: list[DatasetRow]) -> np.ndarray:
        x = _to_matrix(rows, self.feature_names)[0]
        raw = self.booster.predict_proba(x)[:, 1]
        return self.calibrator.predict(raw)


def _to_matrix(rows: list[DatasetRow], feature_names: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
    x = np.array([[r.features[name] for name in feature_names] for r in rows])
    y = np.array([r.label for r in rows])
    return x, y


def walk_forward_splits(
    rows: list[DatasetRow],
    n_splits: int = 5,
    min_train_fraction: float = 0.4,
) -> Iterator[tuple[list[DatasetRow], list[DatasetRow]]]:
    """Expanding-window walk-forward: each fold trains on everything up to that point in
    time and tests on the immediately following block it has never seen — never a random
    shuffle, per spec 04/07."""
    n = len(rows)
    min_train = int(n * min_train_fraction)
    remaining = n - min_train
    fold_size = remaining // n_splits
    if fold_size <= 0:
        raise ValueError("not enough rows for the requested number of walk-forward splits")

    for i in range(n_splits):
        train_end = min_train + i * fold_size
        test_end = train_end + fold_size if i < n_splits - 1 else n
        yield rows[:train_end], rows[train_end:test_end]


def split_fit_calibration(
    train_rows: list[DatasetRow],
    calibration_fraction: float = 0.2,
) -> tuple[list[DatasetRow], list[DatasetRow]]:
    split = int(len(train_rows) * (1 - calibration_fraction))
    fit_rows, calib_rows = train_rows[:split], train_rows[split:]
    if not fit_rows or not calib_rows:
        raise ValueError("not enough rows to split into fit/calibration sets")
    return fit_rows, calib_rows


def train_model(
    train_rows: list[DatasetRow],
    config: ModelConfig,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
    calibration_fraction: float = 0.2,
) -> TrainedModel:
    """Splits train_rows further: fits the booster on the earlier slice, calibrates on the
    later slice. Calibrating on the same rows used to fit would overstate confidence —
    the model has already memorized those labels."""
    fit_rows, calib_rows = split_fit_calibration(train_rows, calibration_fraction)

    x_fit, y_fit = _to_matrix(fit_rows, feature_names)
    booster = LGBMClassifier(
        num_leaves=config.num_leaves,
        learning_rate=config.learning_rate,
        n_estimators=config.n_estimators,
        min_child_samples=config.min_child_samples,
        verbosity=-1,
    )
    booster.fit(x_fit, y_fit)

    x_calib, y_calib = _to_matrix(calib_rows, feature_names)
    raw_calib_scores = booster.predict_proba(x_calib)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_calib_scores, y_calib)

    return TrainedModel(booster=booster, calibrator=calibrator, feature_names=feature_names)


def choose_thresholds(
    model: TrainedModel,
    calib_rows: list[DatasetRow],
    entry_percentile: float = 80.0,
    exit_percentile: float = 50.0,
) -> tuple[float, float]:
    """Derives entry/exit score thresholds from the *training-side* calibration rows only
    — never from the out-of-sample test fold, which would leak the evaluation data into a
    model hyperparameter."""
    scores = model.predict_proba_batch(calib_rows)
    entry = float(np.percentile(scores, entry_percentile))
    exit_ = float(np.percentile(scores, exit_percentile))
    return entry, exit_


def brier_score(model: TrainedModel, rows: list[DatasetRow]) -> float:
    scores = model.predict_proba_batch(rows)
    labels = np.array([r.label for r in rows])
    return float(np.mean((scores - labels) ** 2))
