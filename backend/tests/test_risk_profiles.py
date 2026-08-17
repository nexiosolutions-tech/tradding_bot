from __future__ import annotations

from tradingbot.model.risk_profiles import ALL_PROFILES, ARROJADO, INTERMEDIARIO, SEGURANCA
from tradingbot.risk.manager import RiskConfig


def test_all_profiles_has_exactly_three_distinct_names():
    names = [p.name for p in ALL_PROFILES]
    assert names == ["Segurança", "Intermediário", "Arrojado"]
    assert len(set(names)) == 3


def test_intermediario_matches_todays_already_validated_defaults():
    """Intermediário isn't a new profile — it's "keep running as it is today," included
    for side-by-side comparison against the other two."""
    assert INTERMEDIARIO.risk_config == RiskConfig()
    assert INTERMEDIARIO.stop_loss_pct == 0.015
    assert INTERMEDIARIO.entry_percentile == 99.0


def test_seguranca_is_more_conservative_than_arrojado_on_every_axis():
    assert SEGURANCA.entry_percentile > ARROJADO.entry_percentile  # more selective
    assert SEGURANCA.stop_loss_pct < ARROJADO.stop_loss_pct  # tighter stop
    assert SEGURANCA.risk_config.risk_per_trade_pct < ARROJADO.risk_config.risk_per_trade_pct
    assert SEGURANCA.risk_config.max_concurrent_exposure_pct < ARROJADO.risk_config.max_concurrent_exposure_pct
    assert SEGURANCA.risk_config.circuit_breaker_loss_pct < ARROJADO.risk_config.circuit_breaker_loss_pct


def test_intermediario_sits_between_seguranca_and_arrojado():
    assert SEGURANCA.entry_percentile > INTERMEDIARIO.entry_percentile > ARROJADO.entry_percentile
    assert SEGURANCA.stop_loss_pct < INTERMEDIARIO.stop_loss_pct < ARROJADO.stop_loss_pct
