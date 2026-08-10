"""In-memory fake exchange — lets execution/orchestrator tests exercise real control flow
(idempotency, stop-loss enforcement, reconciliation) without any network dependency."""

from __future__ import annotations

from decimal import Decimal

from tradingbot.execution.client import OrderResult, SymbolFilters

# Permissive by default so existing tests (written before exchange-filter validation
# existed) keep passing without needing to know about filters at all.
_PERMISSIVE_FILTERS = SymbolFilters(
    step_size=Decimal("0.00000001"), tick_size=Decimal("0.00000001"), min_notional=Decimal("0")
)


class FakeExchangeClient:
    def __init__(self):
        self.orders: dict[str, OrderResult] = {}
        self.next_fill_price: dict[str, float] = {}
        self.reject_next_market_order: bool = False
        self.balances: dict[str, float] = {}
        self.call_log: list[tuple] = []
        self.fail_stop_loss_times: int = 0
        self.fail_market_sell_times: int = 0
        self.fail_cancel_times: int = 0
        self.symbol_filters: SymbolFilters = _PERMISSIVE_FILTERS

    async def place_market_order(self, symbol, side, quantity, client_order_id) -> OrderResult:
        self.call_log.append(("place_market_order", symbol, side, quantity, client_order_id))
        if client_order_id in self.orders:
            return self.orders[client_order_id]  # idempotent replay, not a new order

        if side == "sell" and self.fail_market_sell_times > 0:
            self.fail_market_sell_times -= 1
            raise ConnectionError("simulated network failure placing market sell order")

        if self.reject_next_market_order:
            self.reject_next_market_order = False
            result = OrderResult(client_order_id, None, "REJECTED", 0.0, None, {})
        else:
            price = self.next_fill_price.pop(symbol, 100.0)
            result = OrderResult(
                client_order_id, f"ex-{len(self.orders) + 1}", "FILLED", quantity, price, {"quantity": quantity}
            )
        self.orders[client_order_id] = result
        return result

    async def place_stop_loss_order(
        self, symbol, side, quantity, stop_price, client_order_id, tick_size=None
    ) -> OrderResult:
        self.call_log.append(("place_stop_loss_order", symbol, side, quantity, stop_price, client_order_id))
        if client_order_id in self.orders:
            return self.orders[client_order_id]
        if self.fail_stop_loss_times > 0:
            self.fail_stop_loss_times -= 1
            raise ConnectionError("simulated network failure placing stop-loss order")
        result = OrderResult(
            client_order_id,
            f"ex-{len(self.orders) + 1}",
            "NEW",
            0.0,
            None,
            {"quantity": quantity, "stop_price": stop_price},
        )
        self.orders[client_order_id] = result
        return result

    async def cancel_order(self, symbol, client_order_id) -> OrderResult:
        self.call_log.append(("cancel_order", symbol, client_order_id))
        if self.fail_cancel_times > 0:
            self.fail_cancel_times -= 1
            raise RuntimeError("simulated -2011 Unknown order sent")
        existing = self.orders.get(client_order_id)
        if existing is None:
            return OrderResult(client_order_id, None, "CANCELED", 0.0, None, {})
        updated = OrderResult(
            client_order_id, existing.exchange_order_id, "CANCELED", existing.filled_qty, existing.avg_fill_price, existing.raw
        )
        self.orders[client_order_id] = updated
        return updated

    async def get_order_status(self, symbol, client_order_id) -> OrderResult | None:
        return self.orders.get(client_order_id)

    async def get_account_balance(self, asset) -> float:
        return self.balances.get(asset, 0.0)

    async def get_symbol_filters(self, symbol) -> SymbolFilters:
        self.call_log.append(("get_symbol_filters", symbol))
        return self.symbol_filters

    def simulate_fill(self, client_order_id: str, fill_price: float | None = None) -> None:
        """Test helper: mark a resting order (e.g. a stop-loss) as filled by the exchange,
        the way it would be if the market price actually crossed the stop."""
        existing = self.orders[client_order_id]
        quantity = existing.raw.get("quantity", existing.filled_qty)
        price = fill_price if fill_price is not None else existing.avg_fill_price
        self.orders[client_order_id] = OrderResult(
            client_order_id, existing.exchange_order_id, "FILLED", quantity, price, existing.raw
        )
