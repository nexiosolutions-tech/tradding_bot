"""Event-driven backtest engine — spec 07.

Processes events strictly in chronological order through the same FeatureEngine used in
production (spec 03), applies fees and slippage to every fill, and enforces the same
structural risk rules as spec 05 (mandatory stop-loss, percentage-of-capital sizing,
circuit breaker). This is deliberately not a vectorized backtest — vectorizing would hide
ordering/timing effects that matter for a system meant to run live.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tradingbot.backtesting.costs import FeeModel, SlippageModel
from tradingbot.backtesting.strategy import Strategy
from tradingbot.features.engine import FeatureEngine, FeatureSnapshot
from tradingbot.ingestion.schema import MarketEvent
from tradingbot.risk.manager import MissingStopLossError, RiskConfig, RiskManager

ExitReason = Literal["stop_loss", "signal_exit", "end_of_data"]


@dataclass
class OpenPosition:
    entry_price: float
    size: float
    stop_loss_price: float
    entry_ts: int
    entry_fee: float


@dataclass(frozen=True)
class ClosedTrade:
    symbol: str
    entry_ts: int
    exit_ts: int
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    fees_paid: float
    exit_reason: ExitReason


class BacktestEngine:
    def __init__(
        self,
        strategy: Strategy,
        risk_config: RiskConfig,
        fee_model: FeeModel,
        slippage_model: SlippageModel,
        initial_capital: float,
    ):
        self.feature_engine = FeatureEngine()
        self.strategy = strategy
        self.risk = RiskManager(risk_config)
        self.fee_model = fee_model
        self.slippage_model = slippage_model
        self.equity = initial_capital
        self._position: OpenPosition | None = None
        self._last_snapshot: FeatureSnapshot | None = None
        self.equity_curve: list[tuple[int, float]] = []
        self.trades: list[ClosedTrade] = []
        self.rejected_signals: list[str] = []

    def warm_up(self, events: list[MarketEvent]) -> None:
        """Primes indicator state from events preceding the evaluation window, without
        recording trades or equity — lets an out-of-sample fold start with fully warmed-up
        indicators instead of contaminating its own metrics with a few in-sample bars."""
        for event in events:
            self.feature_engine.on_event(event)

    def run(self, events: list[MarketEvent]) -> None:
        for event in events:
            snapshot = self.feature_engine.on_event(event)
            if snapshot is None:
                continue
            self._on_snapshot(snapshot)

        if self._position is not None and self._last_snapshot is not None:
            self._close_position(self._last_snapshot, reason="end_of_data")

    def _on_snapshot(self, snapshot: FeatureSnapshot) -> None:
        self._last_snapshot = snapshot

        if self._position is not None:
            self._check_exit(snapshot)
        elif self.risk.can_enter():
            signal = self.strategy.on_features(snapshot)
            if signal is not None:
                self._try_enter(signal, snapshot)

        mark = self._mark_to_market(snapshot)
        self.risk.record_equity(snapshot.knowledge_ts, mark)
        self.equity_curve.append((snapshot.knowledge_ts, mark))

    def _try_enter(self, signal, snapshot: FeatureSnapshot) -> None:
        fill_price = self.slippage_model.apply(snapshot.close, "buy")
        try:
            size = self.risk.position_size(self.equity, fill_price, signal.stop_loss_pct)
        except MissingStopLossError:
            self.rejected_signals.append("missing_stop_loss")
            return

        size = self.risk.cap_to_max_exposure(size, fill_price, self.equity)
        notional = size * fill_price
        entry_fee = self.fee_model.fee(notional)
        stop_loss_price = fill_price * (1 - signal.stop_loss_pct)

        # Entry fee is held on the position and settled together with the exit fee in
        # _close_position — equity reflects realized P&L only, never a mid-trade half-state.
        self._position = OpenPosition(
            entry_price=fill_price,
            size=size,
            stop_loss_price=stop_loss_price,
            entry_ts=snapshot.knowledge_ts,
            entry_fee=entry_fee,
        )

    def _check_exit(self, snapshot: FeatureSnapshot) -> None:
        pos = self._position
        assert pos is not None
        if snapshot.close <= pos.stop_loss_price:
            self._close_position(snapshot, reason="stop_loss", exit_price_override=pos.stop_loss_price)
            return
        if self.strategy.should_exit(snapshot):
            self._close_position(snapshot, reason="signal_exit")

    def _close_position(
        self,
        snapshot: FeatureSnapshot,
        reason: ExitReason,
        exit_price_override: float | None = None,
    ) -> None:
        pos = self._position
        assert pos is not None
        raw_price = exit_price_override if exit_price_override is not None else snapshot.close
        fill_price = self.slippage_model.apply(raw_price, "sell")
        notional = pos.size * fill_price
        exit_fee = self.fee_model.fee(notional)

        total_fees = exit_fee + pos.entry_fee
        pnl = (fill_price - pos.entry_price) * pos.size - total_fees
        self.equity += pnl

        self.trades.append(
            ClosedTrade(
                symbol=snapshot.symbol,
                entry_ts=pos.entry_ts,
                exit_ts=snapshot.knowledge_ts,
                entry_price=pos.entry_price,
                exit_price=fill_price,
                size=pos.size,
                pnl=pnl,
                fees_paid=total_fees,
                exit_reason=reason,
            )
        )
        self._position = None

    def _mark_to_market(self, snapshot: FeatureSnapshot) -> float:
        if self._position is None:
            return self.equity
        pos = self._position
        unrealized = (snapshot.close - pos.entry_price) * pos.size - pos.entry_fee
        return self.equity + unrealized
