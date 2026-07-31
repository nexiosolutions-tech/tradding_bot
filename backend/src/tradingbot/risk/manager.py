"""Risk management — spec 05. Shared by backtesting now and by the execution layer once
spec 06 is implemented; the sizing/circuit-breaker rules must be identical in both.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade_pct: float = 0.01
    max_concurrent_exposure_pct: float = 0.20
    circuit_breaker_loss_pct: float = 0.10
    circuit_breaker_window_minutes: int = 60

    def __post_init__(self):
        for name, value in (
            ("risk_per_trade_pct", self.risk_per_trade_pct),
            ("max_concurrent_exposure_pct", self.max_concurrent_exposure_pct),
            ("circuit_breaker_loss_pct", self.circuit_breaker_loss_pct),
        ):
            if not 0 < value <= 1:
                raise ValueError(f"{name} must be a fraction in (0, 1], got {value}")


class MissingStopLossError(Exception):
    """Raised when a trade signal reaches the risk manager without a stop-loss.

    Spec 05 / CLAUDE.md rule 2: no code path may size a position without one — this is not
    a validation nicety, it is the structural enforcement of that rule.
    """


class RiskManager:
    def __init__(self, config: RiskConfig):
        self.config = config
        self._equity_history: deque[tuple[int, float]] = deque()
        self._session_peak: float | None = None
        self.circuit_breaker_triggered = False
        self.circuit_breaker_triggered_at: int | None = None

    def position_size(self, equity: float, entry_price: float, stop_loss_pct: float | None) -> float:
        """Size (in base-asset units) such that hitting the stop-loss loses exactly
        `risk_per_trade_pct` of current equity — sizing is always a percentage of capital,
        per spec 05, never a fixed amount."""
        if stop_loss_pct is None or stop_loss_pct <= 0:
            raise MissingStopLossError("every position requires a positive stop_loss_pct")
        if equity <= 0 or entry_price <= 0:
            raise ValueError("equity and entry_price must be positive")

        risk_amount = equity * self.config.risk_per_trade_pct
        loss_per_unit = entry_price * stop_loss_pct
        return risk_amount / loss_per_unit

    def cap_to_max_exposure(self, size: float, entry_price: float, equity: float) -> float:
        notional = size * entry_price
        max_notional = equity * self.config.max_concurrent_exposure_pct
        if notional <= max_notional:
            return size
        return max_notional / entry_price

    def record_equity(self, ts: int, equity: float) -> None:
        self._equity_history.append((ts, equity))
        window_ms = self.config.circuit_breaker_window_minutes * 60_000
        while self._equity_history and ts - self._equity_history[0][0] > window_ms:
            self._equity_history.popleft()

        if self._session_peak is None or equity > self._session_peak:
            self._session_peak = equity

        if self.circuit_breaker_triggered:
            return

        windowed_peak = max(e for _, e in self._equity_history)
        if windowed_peak > 0:
            windowed_dd = (windowed_peak - equity) / windowed_peak
            if windowed_dd >= self.config.circuit_breaker_loss_pct:
                self.circuit_breaker_triggered = True
                self.circuit_breaker_triggered_at = ts
                return

        # Complementary trigger: the windowed check above is blind to a slow bleed that
        # never shows up within a single window because the reference peak slides down
        # with it. This tracks a peak that only resets on human acknowledgement.
        if self._session_peak > 0:
            session_dd = (self._session_peak - equity) / self._session_peak
            if session_dd >= self.config.circuit_breaker_loss_pct:
                self.circuit_breaker_triggered = True
                self.circuit_breaker_triggered_at = ts

    def reset_session_peak(self, equity: float) -> None:
        """Called on human acknowledgement of the circuit breaker (spec 05) — without
        this, the session peak from before the trip would immediately re-trigger the
        breaker on the next equity update, since capital hasn't recovered yet."""
        self._session_peak = equity

    @property
    def peak_equity(self) -> float | None:
        if not self._equity_history:
            return None
        return max(equity for _, equity in self._equity_history)

    def can_enter(self) -> bool:
        """Once tripped, stays tripped for the rest of this run — spec 05: the circuit
        breaker does not recover on its own, it requires explicit human acknowledgement,
        which a backtest has no stand-in for."""
        return not self.circuit_breaker_triggered
