import numpy as np
import pytest

from tradingbot.model.dataset import FEATURE_NAMES, DatasetRow, TargetConfig
from tradingbot.model.training import ModelConfig, split_fit_calibration, train_model
from tradingbot.model.versioning import save_model


def _rows(n=200, seed=2):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        rsi = float(rng.uniform(0, 100))
        features = {name: 0.0 for name in FEATURE_NAMES} | {"rsi": rsi}
        rows.append(DatasetRow(symbol="BTCUSDT", knowledge_ts=i, close=100.0, features=features, label=int(rsi > 50)))
    return rows


def test_load_active_strategy_falls_back_to_placeholder_when_no_models(tmp_path, monkeypatch):
    import tradingbot.execution.bootstrap as bootstrap

    monkeypatch.setattr(bootstrap, "MODELS_DIR", tmp_path / "empty")

    strategy, version = bootstrap.load_active_strategy()

    assert version == "placeholder-fase1"
    assert strategy.stop_loss_pct == bootstrap.PLACEHOLDER_STOP_LOSS_PCT


def test_load_active_strategy_picks_latest_promoted_version(tmp_path, monkeypatch):
    import tradingbot.execution.bootstrap as bootstrap

    fit_rows, _ = split_fit_calibration(_rows(), calibration_fraction=0.2)
    model = train_model(fit_rows, ModelConfig(n_estimators=20))

    for version in ("BTCUSDT_1m_1000", "BTCUSDT_1m_2000"):
        save_model(
            output_dir=tmp_path,
            version=version,
            model=model,
            target_config=TargetConfig(),
            model_config=ModelConfig(n_estimators=20),
            entry_threshold=0.7,
            exit_threshold=0.4,
            stop_loss_pct=0.02,
            validation_summary={},
        )

    monkeypatch.setattr(bootstrap, "MODELS_DIR", tmp_path)

    strategy, version = bootstrap.load_active_strategy()

    assert version == "BTCUSDT_1m_2000"  # lexicographically (and numerically) latest
    assert strategy.entry_threshold == 0.7


def test_build_orchestrator_requires_credentials(monkeypatch):
    import tradingbot.execution.bootstrap as bootstrap

    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)

    with pytest.raises(bootstrap.MissingCredentialsError):
        bootstrap.build_orchestrator()


def test_build_orchestrator_blocks_mainnet_without_explicit_override(monkeypatch):
    import tradingbot.execution.bootstrap as bootstrap

    monkeypatch.setenv("BINANCE_API_KEY", "fake")
    monkeypatch.setenv("BINANCE_API_SECRET", "fake")
    monkeypatch.setenv("BINANCE_TESTNET", "false")

    with pytest.raises(RuntimeError):
        bootstrap.build_orchestrator()


def test_build_orchestrator_reconstructs_equity_from_realized_pnl(tmp_path, monkeypatch):
    """A restart must never silently wipe P&L already booked from real trades — equity
    should be INITIAL_EQUITY plus whatever the DB already shows as realized, not always
    reset to the config default (2026-07-31, real gap found in production)."""
    import tradingbot.execution.bootstrap as bootstrap
    from tradingbot.persistence import repository
    from tradingbot.persistence.db import get_session_factory
    from tradingbot.persistence.models import TradeRecord

    monkeypatch.setenv("BINANCE_API_KEY", "fake")
    monkeypatch.setenv("BINANCE_API_SECRET", "fake")
    monkeypatch.setenv("INITIAL_EQUITY", "1000")
    monkeypatch.setenv("SYMBOL", "BTCUSDT")

    session_factory = get_session_factory(f"sqlite:///{tmp_path}/test.db")
    with session_factory() as session:
        repository.record_trade(
            session,
            TradeRecord(
                symbol="BTCUSDT", entry_order_id="e1", exit_order_id="x1", entry_ts=1, exit_ts=2,
                entry_price=100.0, exit_price=110.0, size=1.0, pnl=42.5, fees_paid=1.0,
                exit_reason="signal_exit", strategy_version="test",
            ),
        )
        repository.record_trade(
            session,
            TradeRecord(
                symbol="BTCUSDT", entry_order_id="e2", exit_order_id="x2", entry_ts=3, exit_ts=4,
                entry_price=100.0, exit_price=90.0, size=1.0, pnl=-10.0, fees_paid=1.0,
                exit_reason="stop_loss", strategy_version="test",
            ),
        )

    orchestrator = bootstrap.build_orchestrator(session_factory=session_factory)

    assert orchestrator.equity == pytest.approx(1000.0 + 42.5 - 10.0)
