"""Transaction cost models — spec 07. Backtests without these are not representative."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class FeeModel:
    """Binance spot default fee tier. Override for a specific account's VIP tier."""

    taker_fee_pct: float = 0.001

    def fee(self, notional: float) -> float:
        return notional * self.taker_fee_pct


@dataclass(frozen=True)
class SlippageModel:
    slippage_bps: float = 5.0

    def apply(self, price: float, side: Side) -> float:
        slip = price * (self.slippage_bps / 10_000)
        if side == "buy":
            return price + slip
        if side == "sell":
            return price - slip
        raise ValueError(f"unknown side: {side}")
