import numpy as np

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
