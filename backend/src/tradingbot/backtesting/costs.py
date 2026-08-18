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


def net_trade_pnl(trade, fee_model: FeeModel | None = None) -> float:
    """2026-08-17: real trades persisted from execution/orchestrator.py always carry
    fees_paid=0.0 (a known gap, not a real number — testnet genuinely charges no fee, so
    trade.pnl is fee-free by construction). Anywhere production P&L gets reported, use
    this instead of trade.pnl directly — otherwise the number silently overstates what the
    same trades would net once a real fee applies. Works on any object exposing
    entry_price/exit_price/size/pnl (TradeRecord and backtesting.engine.ClosedTrade both
    qualify), so it's the one place this correction is computed, not one per caller."""
    model = fee_model or FeeModel()
    entry_notional = trade.entry_price * trade.size
    exit_notional = trade.exit_price * trade.size
    return trade.pnl - model.fee(entry_notional) - model.fee(exit_notional)
