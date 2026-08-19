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


def test_walk_forward_splits_purges_trailing_train_rows_when_requested():
    """purge_bars (2026-08-19 finding, "purged walk-forward"): a training row's label is
    computed by looking up to horizon_bars forward from its own knowledge_ts
    (model/dataset.py::_triple_barrier_label) — with purge_bars=0, the last horizon_bars
    rows of every training slice have labels that peek into the immediately following test
    slice. Confirmed real leakage by code inspection, not the feature-side anti-leakage
    invariant (spec 03), which stays intact. test_rows must be untouched — test labels are
    never consulted (the backtest runs on real price action)."""
    rows = _separable_rows(500)
    purge_bars = 15
    unpurged = list(walk_forward_splits(rows, n_splits=5, min_train_fraction=0.4, purge_bars=0))
    purged = list(walk_forward_splits(rows, n_splits=5, min_train_fraction=0.4, purge_bars=purge_bars))

    assert len(unpurged) == len(purged)
    for (train_u, test_u), (train_p, test_p) in zip(unpurged, purged):
        assert test_p == test_u
        assert train_p == train_u[:-purge_bars]


def test_walk_forward_splits_purge_never_produces_negative_length_train():
    rows = _separable_rows(50)
    for train, _test in walk_forward_splits(rows, n_splits=2, min_train_fraction=0.4, purge_bars=10_000):
        assert len(train) == 0


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

    entry, exit_ = choose_thresholds(model, calib_rows, entry_percentile=80)
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

    # label_rate = 0% here -> floor_percentile = 100 - 3*0 = 100, capped at 99.9, so the
    # floor (not the requested 80) decides — covered separately by the floor-specific test
    # below. Use a high enough label_rate that the floor stays out of the way, isolating
    # "does this rank on raw score at all" from "does the floor apply".
    calib_rows = [_row(i, rsi=0.0, label=1) for i in range(11)]  # label_rate 100% -> floor = -200
    entry, exit_ = choose_thresholds(_StubRawModel(), calib_rows, entry_percentile=80)
    assert entry == pytest.approx(np.percentile(np.arange(11), 80))


def test_choose_thresholds_applies_label_rate_floor_and_noise_hysteresis():
    """Regression guard (2026-08-19, fifth round): switching to the raw score alone
    (without this floor) measurably made results worse on real data — 362 trades vs. 113,
    net pnl -2152 vs. -765 on the same fixed window (changes/2026-08-19-benchmark-e-teste-
    de-nulidade.md) — because a rare-event classifier's raw score is itself concentrated
    near a low value for most rows, so entry_percentile=80 alone is still far too
    permissive relative to the true event rate."""

    class _StubRawModel:
        def predict_raw_batch(self, rows):
            return np.array([0.0, 1.0, 2.0, 10.0, 11.0, 12.0, 20.0, 21.0, 22.0, 100.0])

    raw = np.array([0.0, 1.0, 2.0, 10.0, 11.0, 12.0, 20.0, 21.0, 22.0, 100.0])
    calib_rows = [_row(i, rsi=0.0, label=1 if i == 0 else 0) for i in range(10)]  # label_rate 10%

    entry, exit_ = choose_thresholds(_StubRawModel(), calib_rows, entry_percentile=50.0)

    # floor_percentile = 100 - 3.0 * 10.0 = 70, stricter than the requested 50 -> floor wins
    expected_entry = np.percentile(raw, 70.0)
    assert entry == pytest.approx(expected_entry)

    noise_stdev = float(np.std(np.diff(raw)))
    expected_exit = max(0.0, expected_entry - 3.0 * noise_stdev)
    assert exit_ == pytest.approx(expected_exit)
    assert exit_ < entry


def test_choose_thresholds_leaves_a_stricter_caller_percentile_untouched():
    """A caller already asking for something stricter than the label-rate floor (e.g.
    risk_profiles.py's 95-99.5 presets) must not be loosened by this change."""

    class _StubRawModel:
        def predict_raw_batch(self, rows):
            return np.arange(len(rows), dtype=float)

    calib_rows = [_row(i, rsi=0.0, label=1 if i == 0 else 0) for i in range(10)]  # label_rate 10% -> floor 70
    entry, _ = choose_thresholds(_StubRawModel(), calib_rows, entry_percentile=95.0)
    assert entry == pytest.approx(np.percentile(np.arange(10), 95.0))


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
