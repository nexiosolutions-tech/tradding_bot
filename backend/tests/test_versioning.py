import numpy as np

from tradingbot.model.dataset import FEATURE_NAMES, MODEL_FEATURE_NAMES, DatasetRow, TargetConfig
from tradingbot.model.training import ModelConfig, split_fit_calibration, train_model
from tradingbot.model.versioning import load_metadata, load_model, save_model


def _row(ts, rsi, label):
    features = {name: 0.0 for name in FEATURE_NAMES}
    features["rsi"] = rsi
    return DatasetRow(symbol="BTCUSDT", knowledge_ts=ts, close=100.0, features=features, label=label)


def _rows(n=300, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        rsi = float(rng.uniform(0, 100))
        label = 1 if rsi > 50 else 0
        rows.append(_row(i, rsi, label))
    return rows


def test_save_and_load_model_round_trip(tmp_path):
    rows = _rows()
    fit_rows, _ = split_fit_calibration(rows, calibration_fraction=0.2)
    model_config = ModelConfig(n_estimators=30)
    model = train_model(fit_rows, model_config)

    sample = {name: 0.0 for name in FEATURE_NAMES} | {"rsi": 80.0}
    original_score = model.predict_proba(sample)

    version_dir = save_model(
        output_dir=tmp_path,
        version="v1",
        model=model,
        target_config=TargetConfig(),
        model_config=model_config,
        entry_threshold=0.7,
        exit_threshold=0.4,
        stop_loss_pct=0.02,
        validation_summary={"folds_won": 3, "folds_total": 3},
    )

    loaded = load_model(version_dir)
    assert loaded.predict_proba(sample) == original_score

    metadata = load_metadata(version_dir)
    assert metadata["version"] == "v1"
    assert metadata["entry_threshold"] == 0.7
    assert metadata["validation_summary"]["folds_won"] == 3
    assert set(metadata["feature_names"]) == set(MODEL_FEATURE_NAMES)
