"""Execution client — spec 06. An abstraction over exchange order placement so the
orchestrator can be driven by a deterministic fake in tests, and so testnet vs mainnet is
a constructor argument, never a code branch (spec 06's environment table).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class OrderResult:
    client_order_id: str
    exchange_order_id: str | None
    status: str  # "NEW" | "FILLED" | "PARTIALLY_FILLED" | "REJECTED" | "CANCELED"
    filled_qty: float
    avg_fill_price: float | None
    raw: dict = field(default_factory=dict)


class ExchangeClient(Protocol):
    async def place_market_order(
        self, symbol: str, side: str, quantity: float, client_order_id: str
    ) -> OrderResult: ...

    async def place_stop_loss_order(
        self, symbol: str, side: str, quantity: float, stop_price: float, client_order_id: str
    ) -> OrderResult: ...

    async def cancel_order(self, symbol: str, client_order_id: str) -> OrderResult: ...

    async def get_order_status(self, symbol: str, client_order_id: str) -> OrderResult | None: ...

    async def get_account_balance(self, asset: str) -> float: ...


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
        self, symbol: str, side: str, quantity: float, stop_price: float, client_order_id: str
    ) -> OrderResult:
        client = await self._get_client()
        # STOP_LOSS_LIMIT with the limit price a hair below the stop — guarantees the order
        # is marketable once triggered without becoming a bare market stop.
        limit_price = stop_price * 0.999 if side.lower() == "sell" else stop_price * 1.001
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

    async def get_order_status(self, symbol: str, client_order_id: str) -> OrderResult | None:
        client = await self._get_client()
        try:
            raw = await client.get_order(symbol=symbol, origClientOrderId=client_order_id)
        except Exception:
            return None
        return self._to_order_result(client_order_id, raw)

    async def get_account_balance(self, asset: str) -> float:
        client = await self._get_client()
        raw = await client.get_asset_balance(asset=asset)
        return float(raw["free"]) if raw else 0.0

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close_connection()
