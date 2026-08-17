"""Risk profiles — spec 13. Three named presets over parameters already validated
individually (entry selectivity, stop-loss width, position sizing, circuit breaker
tolerance) — not a new model architecture, a different point in the same parameter space
sweep_thresholds.py already explores for entry_percentile/horizon_minutes.
"""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.risk.manager import RiskConfig

# Fixed across all 3 profiles, isolating the risk axis from the entry-timing axis already
# validated separately (specs/11, 9ª-12ª rodadas).
REFERENCE_HORIZON_MINUTES = 45


@dataclass(frozen=True)
class RiskProfile:
    name: str
    entry_percentile: float
    stop_loss_pct: float
    risk_config: RiskConfig


SEGURANCA = RiskProfile(
    name="Segurança",
    entry_percentile=99.5,
    stop_loss_pct=0.010,
    risk_config=RiskConfig(
        risk_per_trade_pct=0.005,
        max_concurrent_exposure_pct=0.10,
        circuit_breaker_loss_pct=0.05,
    ),
)

# Today's already-validated defaults (RiskConfig()), unchanged — this is "keep running as
# it is today," included for side-by-side comparison, not a new profile.
INTERMEDIARIO = RiskProfile(
    name="Intermediário",
    entry_percentile=99.0,
    stop_loss_pct=0.015,
    risk_config=RiskConfig(),
)

ARROJADO = RiskProfile(
    name="Arrojado",
    entry_percentile=95.0,
    stop_loss_pct=0.025,
    risk_config=RiskConfig(
        risk_per_trade_pct=0.02,
        max_concurrent_exposure_pct=0.35,
        circuit_breaker_loss_pct=0.15,
    ),
)

ALL_PROFILES: tuple[RiskProfile, ...] = (SEGURANCA, INTERMEDIARIO, ARROJADO)
