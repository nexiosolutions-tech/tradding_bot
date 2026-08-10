"""Execution client — spec 06. An abstraction over exchange order placement so the
orchestrator can be driven by a deterministic fake in tests, and so testnet vs mainnet is
a constructor argument, never a code branch (spec 06's environment table).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from tradingbot.execution.rounding import round_to_tick


@dataclass(frozen=True)
class OrderResult:
    client_order_id: str
    exchange_order_id: str | None
    status: str  # "NEW" | "FILLED" | "PARTIALLY_FILLED" | "REJECTED" | "CANCELED"
    filled_qty: float
    avg_fill_price: float | None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SymbolFilters:
    """Binance's LOT_SIZE / PRICE_FILTER / MIN_NOTIONAL trading rules for a symbol — an
    order that violates any of these is hard-rejected by the exchange, not just warned
    about, so every order must be shaped to fit before it is sent."""

    step_size: Decimal
    tick_size: Decimal
    min_notional: Decimal


class ExchangeClient(Protocol):
    async def place_market_order(
        self, symbol: str, side: str, quantity: float, client_order_id: str
    ) -> OrderResult: ...

    async def place_stop_loss_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
        client_order_id: str,
        tick_size: Decimal = Decimal("0"),
    ) -> OrderResult: ...

    async def cancel_order(self, symbol: str, client_order_id: str) -> OrderResult: ...

    async def get_order_status(self, symbol: str, client_order_id: str) -> OrderResult | None: ...

    async def get_account_balance(self, asset: str) -> float: ...

    async def get_symbol_filters(self, symbol: str) -> SymbolFilters: ...


class BinanceTestnetClient:
    """Thin wrapper over python-binance's AsyncClient, restricted to spot testnet unless
    explicitly constructed otherwise — mainnet requires passing testnet=False, which is a
    deliberate, visible choice at the call site, never a default.
    """

    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self._api_key = api_key
        self._api_secret = api_secret
        self._testnet = testnet
        self._client = None

    async def _get_client(self):
        if self._client is None:
            from binance import AsyncClient

            self._client = await AsyncClient.create(
                self._api_key, self._api_secret, testnet=self._testnet
            )
        return self._client

    @staticmethod
    def _to_order_result(client_order_id: str, raw: dict) -> OrderResult:
        fills = raw.get("fills", [])
        filled_qty = float(raw.get("executedQty", 0.0))
        avg_price = None
        if fills:
            total_cost = sum(float(f["price"]) * float(f["qty"]) for f in fills)
            total_qty = sum(float(f["qty"]) for f in fills)
            avg_price = total_cost / total_qty if total_qty else None
        return OrderResult(
            client_order_id=client_order_id,
            exchange_order_id=str(raw.get("orderId")) if raw.get("orderId") is not None else None,
            status=raw.get("status", "UNKNOWN"),
            filled_qty=filled_qty,
            avg_fill_price=avg_price,
            raw=raw,
        )

    async def place_market_order(
        self, symbol: str, side: str, quantity: float, client_order_id: str
    ) -> OrderResult:
        client = await self._get_client()
        raw = await client.create_order(
            symbol=symbol,
            side=side.upper(),
            type="MARKET",
            quantity=quantity,
            newClientOrderId=client_order_id,
        )
        return self._to_order_result(client_order_id, raw)

    async def place_stop_loss_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
        client_order_id: str,
        tick_size: Decimal = Decimal("0"),
    ) -> OrderResult:
        client = await self._get_client()
        # STOP_LOSS_LIMIT with the limit price a hair below the stop — guarantees the order
        # is marketable once triggered without becoming a bare market stop. stop_price
        # arrives already tick-aligned, but multiplying it by 0.999/1.001 almost always
        # breaks that alignment again — the limit price needs its own rounding, or Binance
        # rejects it with PRICE_FILTER (this was silently 100% of stop-loss placements
        # failing in production until 2026-07-31).
        raw_limit = stop_price * 0.999 if side.lower() == "sell" else stop_price * 1.001
        limit_price = round_to_tick(raw_limit, tick_size) if tick_size > 0 else raw_limit
        raw = await client.create_order(
            symbol=symbol,
            side=side.upper(),
            type="STOP_LOSS_LIMIT",
            quantity=quantity,
            price=f"{limit_price:.8f}",
            stopPrice=f"{stop_price:.8f}",
            timeInForce="GTC",
            newClientOrderId=client_order_id,
        )
        return self._to_order_result(client_order_id, raw)

    async def cancel_order(self, symbol: str, client_order_id: str) -> OrderResult:
        client = await self._get_client()
        raw = await client.cancel_order(symbol=symbol, origClientOrderId=client_order_id)
        return self._to_order_result(client_order_id, raw)

    # Binance uses two different codes for "no record of this order" depending on which
    # endpoint asks: -2013 ("Order does not exist") from the query endpoint used here,
    # -2011 ("Unknown order sent") from the cancel endpoint. Confirmed directly against
    # testnet.binance.vision during the 2026-08-09 incident (a real order queried right
    # after a testnet data reset raised -2013, not -2011 as first assumed) — both mean the
    # same thing and both must map to the same None.
    _ORDER_NOT_FOUND_CODES = (-2011, -2013)

    async def get_order_status(self, symbol: str, client_order_id: str) -> OrderResult | None:
        """None means the exchange has no record of this order — a legitimate "not found"
        answer (already filled and pruned, cancelled, or lost, e.g. a testnet data reset).
        Any other failure (network, rate limit, ...) propagates instead of being silently
        folded into the same None — on_event's broad handler logs it and the next candle
        retries, rather than the caller misreading a transient blip as "this order doesn't
        exist" (2026-08-09 incident: that conflation is what let a stuck exit retry the
        same failure forever instead of surfacing a distinguishable one — see changes/).
        """
        from binance.exceptions import BinanceAPIException

        client = await self._get_client()
        try:
            raw = await client.get_order(symbol=symbol, origClientOrderId=client_order_id)
        except BinanceAPIException as exc:
            if exc.code in self._ORDER_NOT_FOUND_CODES:
                return None
            raise
        return self._to_order_result(client_order_id, raw)

    async def get_account_balance(self, asset: str) -> float:
        client = await self._get_client()
        raw = await client.get_asset_balance(asset=asset)
        return float(raw["free"]) if raw else 0.0

    async def get_symbol_filters(self, symbol: str) -> SymbolFilters:
        client = await self._get_client()
        info = await client.get_symbol_info(symbol)
        step_size = tick_size = min_notional = None
        for f in info["filters"]:
            filter_type = f["filterType"]
            if filter_type == "LOT_SIZE":
                step_size = Decimal(f["stepSize"])
            elif filter_type == "PRICE_FILTER":
                tick_size = Decimal(f["tickSize"])
            elif filter_type in ("MIN_NOTIONAL", "NOTIONAL"):
                min_notional = Decimal(f.get("minNotional") or f.get("notional") or "0")
        return SymbolFilters(
            step_size=step_size or Decimal("0"),
            tick_size=tick_size or Decimal("0"),
            min_notional=min_notional or Decimal("0"),
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close_connection()
