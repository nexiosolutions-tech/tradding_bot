import numpy as np
import pytest

from tradingbot.model.dataset import FEATURE_NAMES, DatasetRow
from tradingbot.model.training import (
    ModelConfig,
    brier_score,
    choose_thresholds,
    split_fit_calibration,
    train_model,
    walk_forward_splits,
)


def _row(ts, rsi, label):
    features = {name: 0.0 for name in FEATURE_NAMES}
    features["rsi"] = rsi
    return DatasetRow(symbol="BTCUSDT", knowledge_ts=ts, close=100.0, features=features, label=label)


def _separable_rows(n=400, seed=0):
    """label = 1 iff rsi > 50, with a bit of noise — a trivial pattern LightGBM should
    have no trouble learning, used to sanity-check the training/calibration wiring."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        rsi = float(rng.uniform(0, 100))
        noise = rng.uniform(-5, 5)
        label = 1 if (rsi + noise) > 50 else 0
        rows.append(_row(i, rsi, label))
    return rows


def test_walk_forward_splits_never_overlap_and_expand():
    rows = _separable_rows(500)
    splits = list(walk_forward_splits(rows, n_splits=5, min_train_fraction=0.4))
    assert len(splits) == 5

    prev_train_end = 0
    for train, test in splits:
        assert len(train) >= prev_train_end
        train_max_ts = train[-1].knowledge_ts
        test_min_ts = test[0].knowledge_ts
        assert train_max_ts < test_min_ts  # strictly chronological, no overlap
        prev_train_end = len(train)

    # folds cover the tail of the dataset without gaps
    assert splits[-1][1][-1].knowledge_ts == rows[-1].knowledge_ts


def test_split_fit_calibration_is_chronological_and_non_overlapping():
    rows = _separable_rows(200)
    fit_rows, calib_rows = split_fit_calibration(rows, calibration_fraction=0.2)
    assert len(fit_rows) + len(calib_rows) == len(rows)
    assert fit_rows[-1].knowledge_ts < calib_rows[0].knowledge_ts


def test_trained_model_learns_the_separable_pattern():
    rows = _separable_rows(600)
    fit_rows, calib_rows = split_fit_calibration(rows, calibration_fraction=0.2)
    model = train_model(fit_rows, ModelConfig(n_estimators=50), calibration_fraction=0.2)

    high_rsi = {**{name: 0.0 for name in FEATURE_NAMES}, "rsi": 90.0}
    low_rsi = {**{name: 0.0 for name in FEATURE_NAMES}, "rsi": 10.0}
    assert model.predict_proba(high_rsi) > model.predict_proba(low_rsi)

    score = brier_score(model, calib_rows)
    assert 0.0 <= score < 0.2  # much better than a coin-flip model (~0.25)


def test_choose_thresholds_are_derived_from_calibration_rows_only():
    rows = _separable_rows(600)
    fit_rows, calib_rows = split_fit_calibration(rows, calibration_fraction=0.2)
    model = train_model(fit_rows, ModelConfig(n_estimators=50), calibration_fraction=0.2)

    entry, exit_ = choose_thresholds(model, calib_rows, entry_percentile=80, exit_percentile=50)
    assert 0.0 <= exit_ <= entry <= 1.0


def test_choose_thresholds_ranks_on_raw_score_not_calibrated():
    """Regression guard (2026-08-19): ModelStrategy compares live scores against these
    thresholds via predict_raw, not predict_proba — so they must come from
    predict_raw_batch. A stub exposing only predict_raw_batch (no predict_proba_batch)
    would raise AttributeError if choose_thresholds ever regressed to ranking on the
    calibrated score."""

    class _StubRawModel:
        def predict_raw_batch(self, rows):
            return np.arange(len(rows), dtype=float)

    calib_rows = _separable_rows(11)
    entry, exit_ = choose_thresholds(_StubRawModel(), calib_rows, entry_percentile=80, exit_percentile=50)
    assert entry == pytest.approx(np.percentile(np.arange(11), 80))
    assert exit_ == pytest.approx(np.percentile(np.arange(11), 50))


def test_predict_raw_bypasses_calibration():
    rows = _separable_rows(600)
    fit_rows, calib_rows = split_fit_calibration(rows, calibration_fraction=0.2)
    model = train_model(fit_rows, ModelConfig(n_estimators=50), calibration_fraction=0.2)

    high_rsi = {**{name: 0.0 for name in FEATURE_NAMES}, "rsi": 90.0}
    x = np.array([[high_rsi[name] for name in model.feature_names]])
    expected_raw = float(model.booster.predict_proba(x)[0, 1])
    assert model.predict_raw(high_rsi) == pytest.approx(expected_raw)


def test_predict_raw_batch_has_at_least_as_many_distinct_values_as_calibrated():
    """The empirical property the 2026-08-19 fix rests on (confirmed on real BTCUSDT
    folds: 259-561 raw distinct values vs. 8-31 calibrated) — isotonic regression is a
    monotonic step function and collapses a near-continuous raw score into a handful of
    plateaus by construction."""
    rows = _separable_rows(600)
    fit_rows, calib_rows = split_fit_calibration(rows, calibration_fraction=0.2)
    model = train_model(fit_rows, ModelConfig(n_estimators=50), calibration_fraction=0.2)

    raw = model.predict_raw_batch(calib_rows)
    calibrated = model.predict_proba_batch(calib_rows)
    assert len({round(v, 6) for v in raw}) >= len({round(v, 6) for v in calibrated})


def _imbalanced_rows(n=100, positive_every=10):
    """label=1 rate ~10%, evenly spread across the timeline so any chronological prefix
    (as split_fit_calibration/walk_forward_splits produce) keeps the same ratio — real
    datasets here see label=1 at 0.5-6% of rows (2026-07-31 sweep), this mirrors that."""
    return [_row(i, rsi=90.0 if i % positive_every == positive_every - 1 else 10.0, label=int(i % positive_every == positive_every - 1)) for i in range(n)]


def test_scale_pos_weight_reflects_class_imbalance_when_balancing_enabled():
    rows = _imbalanced_rows(n=100, positive_every=10)  # ~9 negatives per positive
    model = train_model(rows, ModelConfig(n_estimators=10, balance_classes=True), calibration_fraction=0.2)
    assert model.booster.scale_pos_weight == pytest.approx(9.0, rel=0.2)


def test_scale_pos_weight_is_a_no_op_when_balancing_disabled():
    rows = _imbalanced_rows(n=100, positive_every=10)
    model = train_model(rows, ModelConfig(n_estimators=10, balance_classes=False), calibration_fraction=0.2)
    assert model.booster.scale_pos_weight == 1.0


def test_training_is_deterministic_given_the_same_config():
    """Without a fixed random_state, two runs of the *same* ModelConfig could produce
    different scores purely from LightGBM's own internal randomness — making it
    impossible to tell a real config improvement from training-run noise, exactly the
    kind of comparison the hyperparameter sweeps (2026-07-31) depend on being clean."""
    rows = _separable_rows(400)
    fit_rows, calib_rows = split_fit_calibration(rows, calibration_fraction=0.2)

    model_a = train_model(fit_rows, ModelConfig(n_estimators=30), calibration_fraction=0.2)
    model_b = train_model(fit_rows, ModelConfig(n_estimators=30), calibration_fraction=0.2)

    scores_a = model_a.predict_proba_batch(calib_rows)
    scores_b = model_b.predict_proba_batch(calib_rows)
    assert np.array_equal(scores_a, scores_b)
