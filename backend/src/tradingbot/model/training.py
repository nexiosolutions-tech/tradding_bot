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

from tradingbot.model.dataset import MODEL_FEATURE_NAMES, DatasetRow


@dataclass(frozen=True)
class ModelConfig:
    num_leaves: int = 31
    learning_rate: float = 0.05
    n_estimators: int = 200
    min_child_samples: int = 30
    # label=1 has been observed at 0.5-6% of rows depending on horizon (2026-07-31 sweep)
    # — without this, LightGBM can reach a low training loss by mostly predicting the
    # majority class, exactly the failure mode a rare-opportunity target invites.
    balance_classes: bool = True
    # Fixed so hyperparameter sweeps compare configs, not training-run noise — without
    # this, LGBMClassifier's own randomness (bagging/feature subsampling) could make two
    # runs of the *same* config differ enough to look like a config difference.
    random_state: int = 42


@dataclass
class TrainedModel:
    booster: LGBMClassifier
    calibrator: IsotonicRegression
    feature_names: tuple[str, ...]

    def predict_raw(self, features: dict[str, float]) -> float:
        """Pre-calibration LightGBM output — near-continuous, used for ranking (entry/exit
        thresholds, spec 04). Isotonic regression is a monotonic step function: it preserves
        order but collapses raw scores into a handful of plateaus by construction (confirmed
        2026-08-19: 259-561 distinct raw values vs. 8-31 calibrated, on the same real fold —
        changes/2026-08-19-benchmark-e-teste-de-nulidade.md). A percentile computed on the
        calibrated score can land exactly on a plateau, producing near-identical entry/exit
        thresholds (a real fold hit entry_threshold == exit_threshold exactly) — ranking on
        the raw score sidesteps that without needing calibration to be finer-grained."""
        x = np.array([[features[name] for name in self.feature_names]])
        return float(self.booster.predict_proba(x)[0, 1])

    def predict_raw_batch(self, rows: list[DatasetRow]) -> np.ndarray:
        x = _to_matrix(rows, self.feature_names)[0]
        return self.booster.predict_proba(x)[:, 1]

    def predict_proba(self, features: dict[str, float]) -> float:
        """Calibrated score — "0.7 means ~70% historical hit rate" (module docstring).
        Used for human/dashboard-facing confidence (TradeSignal.confidence) and for
        brier_score below; NOT for entry/exit decisions — see predict_raw."""
        raw = self.predict_raw(features)
        return float(self.calibrator.predict([raw])[0])

    def predict_proba_batch(self, rows: list[DatasetRow]) -> np.ndarray:
        raw = self.predict_raw_batch(rows)
        return self.calibrator.predict(raw)


def _to_matrix(rows: list[DatasetRow], feature_names: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
    x = np.array([[r.features[name] for name in feature_names] for r in rows])
    y = np.array([r.label for r in rows])
    return x, y


def walk_forward_splits(
    rows: list[DatasetRow],
    n_splits: int = 5,
    min_train_fraction: float = 0.4,
    purge_bars: int = 0,
) -> Iterator[tuple[list[DatasetRow], list[DatasetRow]]]:
    """Expanding-window walk-forward: each fold trains on everything up to that point in
    time and tests on the immediately following block it has never seen — never a random
    shuffle, per spec 04/07.

    purge_bars (2026-08-19 finding — "purged walk-forward", López de Prado): a row's label
    is computed by looking up to horizon_bars forward from its own knowledge_ts
    (model/dataset.py::_triple_barrier_label) — so, with purge_bars=0, the last horizon_bars
    rows of every training slice have labels that were determined using price action from
    inside the immediately following test slice. That is real leakage across the train/test
    boundary, confirmed by code inspection (not the anti-leakage invariant spec 03 already
    guards for features, which stays intact — only the label's own forward-looking window is
    affected). Pass target_config.horizon_bars here to drop those trailing rows from
    train_rows before it's returned; test_rows is untouched (test labels are never used —
    the backtest runs on real price action, not DatasetRow.label — so no embargo is needed
    on the test side)."""
    n = len(rows)
    min_train = int(n * min_train_fraction)
    remaining = n - min_train
    fold_size = remaining // n_splits
    if fold_size <= 0:
        raise ValueError("not enough rows for the requested number of walk-forward splits")

    for i in range(n_splits):
        train_end = min_train + i * fold_size
        test_end = train_end + fold_size if i < n_splits - 1 else n
        purged_train_end = max(0, train_end - purge_bars)
        yield rows[:purged_train_end], rows[train_end:test_end]


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
    feature_names: tuple[str, ...] = MODEL_FEATURE_NAMES,
    calibration_fraction: float = 0.2,
) -> TrainedModel:
    """Splits train_rows further: fits the booster on the earlier slice, calibrates on the
    later slice. Calibrating on the same rows used to fit would overstate confidence —
    the model has already memorized those labels."""
    fit_rows, calib_rows = split_fit_calibration(train_rows, calibration_fraction)

    x_fit, y_fit = _to_matrix(fit_rows, feature_names)

    scale_pos_weight = 1.0
    if config.balance_classes:
        n_pos = int(y_fit.sum())
        n_neg = len(y_fit) - n_pos
        if n_pos > 0:
            scale_pos_weight = n_neg / n_pos

    booster = LGBMClassifier(
        num_leaves=config.num_leaves,
        learning_rate=config.learning_rate,
        n_estimators=config.n_estimators,
        min_child_samples=config.min_child_samples,
        scale_pos_weight=scale_pos_weight,
        random_state=config.random_state,
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
    label_rate_floor_multiple: float = 3.0,
    exit_hysteresis_stdevs: float = 3.0,
) -> tuple[float, float]:
    """Derives entry/exit score thresholds from the *training-side* calibration rows only
    — never from the out-of-sample test fold, which would leak the evaluation data into a
    model hyperparameter. Ranks on the raw (uncalibrated) score, not predict_proba_batch's
    calibrated output — percentiles only need ordering, and isotonic calibration collapses
    the score into a handful of plateaus by construction (see TrainedModel.predict_raw).
    The returned thresholds live in raw-score space — callers must compare against
    model.predict_raw, not model.predict_proba (see ModelStrategy).

    entry_percentile alone is the wrong tool for a rare-event target (2026-08-19): label=1
    has been observed at 0.5-6% of rows (spec 04), so entry_percentile=80 means trading on
    the top 20% of bars — one to two orders of magnitude more permissive than the event
    itself. Switching to the raw score alone (removing isotonic calibration's incidental,
    unintentional tie-driven filtering) measurably made this worse, not better (362 trades
    vs. 113, net pnl -2152 vs. -765, same fixed window) — see
    changes/2026-08-19-benchmark-e-teste-de-nulidade.md, quarta/quinta rodadas. A floor
    anchored to this fold's own label_rate is applied on top of whatever percentile the
    caller asks for: the effective percentile is never more permissive than
    `100 - label_rate_floor_multiple * label_rate_pct`, so a caller-selected percentile too
    loose for this fold's real event rate gets tightened automatically, while a caller
    already asking for something stricter (e.g. risk_profiles.py's 95-99.5) is untouched.

    exit_threshold is derived, not an independent percentile: entry_threshold minus
    exit_hysteresis_stdevs times the bar-to-bar raw-score noise measured on this same
    calibration slice — a fixed number of noise-units below entry, so should_exit can't
    fire from ordinary score noise by construction, independent of how the score is
    distributed (unlike a percentile-based exit, which reads an arbitrary position in
    whatever shape the score happens to have)."""
    scores = model.predict_raw_batch(calib_rows)

    label_rate_pct = 100.0 * sum(r.label for r in calib_rows) / len(calib_rows) if calib_rows else 0.0
    floor_percentile = min(100.0 - label_rate_floor_multiple * label_rate_pct, 99.9)
    effective_entry_percentile = max(entry_percentile, floor_percentile)
    entry = float(np.percentile(scores, effective_entry_percentile))

    score_diffs = np.diff(scores)
    noise_stdev = float(np.std(score_diffs)) if len(score_diffs) > 1 else 0.0
    exit_ = max(0.0, entry - exit_hysteresis_stdevs * noise_stdev)

    return entry, exit_


def brier_score(model: TrainedModel, rows: list[DatasetRow]) -> float:
    scores = model.predict_proba_batch(rows)
    labels = np.array([r.label for r in rows])
    return float(np.mean((scores - labels) ** 2))
