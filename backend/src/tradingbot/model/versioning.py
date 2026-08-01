"""Model versioning — spec 04. Every trained model is saved with enough metadata to audit
which dataset, hyperparameters, and validation result produced it, and to roll back a
promotion if a later version underperforms.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import joblib

from tradingbot.model.dataset import TargetConfig
from tradingbot.model.training import ModelConfig, TrainedModel


def save_model(
    output_dir: Path,
    version: str,
    model: TrainedModel,
    target_config: TargetConfig,
    model_config: ModelConfig,
    entry_threshold: float,
    exit_threshold: float,
    stop_loss_pct: float,
    min_trend_pct: float,
    validation_summary: dict,
) -> Path:
    version_dir = output_dir / version
    version_dir.mkdir(parents=True, exist_ok=True)

    joblib.dump(model, version_dir / "model.joblib")
    metadata = {
        "version": version,
        "feature_names": list(model.feature_names),
        "target_config": asdict(target_config),
        "model_config": asdict(model_config),
        "entry_threshold": entry_threshold,
        "exit_threshold": exit_threshold,
        "stop_loss_pct": stop_loss_pct,
        "min_trend_pct": min_trend_pct,
        "validation_summary": validation_summary,
    }
    (version_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str))
    return version_dir


def load_model(version_dir: Path) -> TrainedModel:
    return joblib.load(version_dir / "model.joblib")


def load_metadata(version_dir: Path) -> dict:
    return json.loads((version_dir / "metadata.json").read_text())
