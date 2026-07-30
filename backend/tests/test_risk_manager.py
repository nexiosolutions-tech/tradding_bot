import pytest

from tradingbot.risk.manager import MissingStopLossError, RiskConfig, RiskManager


def test_position_size_is_percentage_of_equity_not_fixed_amount():
    config = RiskConfig(risk_per_trade_pct=0.01)
    manager = RiskManager(config)

    size_small_account = manager.position_size(equity=1_000, entry_price=100, stop_loss_pct=0.02)
    size_large_account = manager.position_size(equity=100_000, entry_price=100, stop_loss_pct=0.02)

    assert size_large_account == pytest.approx(size_small_account * 100)
    # risking 1% of 1000 = 10; stop is 2% of price (2 per unit) -> size = 5 units
    assert size_small_account == pytest.approx(5.0)


def test_position_size_rejects_missing_stop_loss():
    manager = RiskManager(RiskConfig())
    with pytest.raises(MissingStopLossError):
        manager.position_size(equity=1_000, entry_price=100, stop_loss_pct=None)
    with pytest.raises(MissingStopLossError):
        manager.position_size(equity=1_000, entry_price=100, stop_loss_pct=0.0)


def test_cap_to_max_exposure_limits_notional():
    manager = RiskManager(RiskConfig(max_concurrent_exposure_pct=0.20))
    oversized = 1000.0  # 1000 units * 100 price = way over 20% of 1000 equity
    capped = manager.cap_to_max_exposure(oversized, entry_price=100, equity=1_000)
    assert capped * 100 == pytest.approx(200.0)  # 20% of 1000


def test_circuit_breaker_trips_on_drawdown_within_window():
    config = RiskConfig(circuit_breaker_loss_pct=0.10, circuit_breaker_window_minutes=60)
    manager = RiskManager(config)

    manager.record_equity(ts=0, equity=1_000)
    assert manager.can_enter()

    manager.record_equity(ts=60_000, equity=895)  # 10.5% drawdown from peak
    assert not manager.can_enter()


def test_circuit_breaker_does_not_recover_automatically():
    config = RiskConfig(circuit_breaker_loss_pct=0.10, circuit_breaker_window_minutes=60)
    manager = RiskManager(config)

    manager.record_equity(ts=0, equity=1_000)
    manager.record_equity(ts=60_000, equity=850)
    assert not manager.can_enter()

    manager.record_equity(ts=120_000, equity=1_000)  # recovers fully
    assert not manager.can_enter()  # still requires human ack, not automatic


def test_risk_config_rejects_out_of_range_percentages():
    with pytest.raises(ValueError):
        RiskConfig(risk_per_trade_pct=0.0)
    with pytest.raises(ValueError):
        RiskConfig(circuit_breaker_loss_pct=1.5)
