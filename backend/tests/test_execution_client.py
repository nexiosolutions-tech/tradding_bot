"""Unit coverage for BinanceTestnetClient's own arithmetic — no real network/testnet
needed since _get_client() is monkeypatched with a fake recording client.

Exists because of a real bug (2026-07-31): place_stop_loss_order rounded stopPrice to the
tick size but not the limit price (stop_price * 0.999/1.001) — Binance rejected every
single stop-loss placement with PRICE_FILTER in production, since multiplying an
already-tick-aligned price by 0.999 almost always breaks that alignment again.
"""

import json
from decimal import Decimal

import pytest
from binance.exceptions import BinanceAPIException

from tradingbot.execution.client import BinanceTestnetClient


def _binance_api_exception(code: int, msg: str = "error") -> BinanceAPIException:
    return BinanceAPIException(response=None, status_code=400, text=json.dumps({"code": code, "msg": msg}))


class _FakeAsyncClient:
    def __init__(self):
        self.create_order_calls: list[dict] = []

    async def create_order(self, **kwargs):
        self.create_order_calls.append(kwargs)
        return {"orderId": 1, "status": "NEW", "executedQty": "0", "fills": []}


@pytest.mark.asyncio
async def test_stop_loss_limit_price_is_rounded_to_tick_size():
    client = BinanceTestnetClient(api_key="x", api_secret="y", testnet=True)
    fake = _FakeAsyncClient()
    client._client = fake  # bypass _get_client()'s real AsyncClient.create()

    # A tick-aligned stop price (2 decimals, as BTCUSDT's tickSize=0.01 requires).
    stop_price = 63759.74
    await client.place_stop_loss_order(
        "BTCUSDT", "sell", 0.01, stop_price, "test-stop-1", tick_size=Decimal("0.01")
    )

    assert len(fake.create_order_calls) == 1
    call = fake.create_order_calls[0]
    limit_price = float(call["price"])
    # Rounded to 2 decimals (tick_size=0.01) — not stop_price * 0.999's raw many-decimal value.
    assert round(limit_price, 2) == limit_price
    assert limit_price < stop_price  # still a hair below the stop, for a marketable sell


@pytest.mark.asyncio
async def test_stop_loss_without_tick_size_falls_back_to_unrounded_price():
    """Backwards-compatible default (tick_size omitted) — behavior before the fix,
    kept only so callers that genuinely don't know the tick size don't crash."""
    client = BinanceTestnetClient(api_key="x", api_secret="y", testnet=True)
    fake = _FakeAsyncClient()
    client._client = fake

    stop_price = 63759.74
    await client.place_stop_loss_order("BTCUSDT", "sell", 0.01, stop_price, "test-stop-2")

    limit_price = float(fake.create_order_calls[0]["price"])
    assert limit_price == pytest.approx(stop_price * 0.999)


class _FakeAsyncClientGetOrder:
    def __init__(self, exc: Exception | None = None, result: dict | None = None):
        self._exc = exc
        self._result = result

    async def get_order(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return self._result


@pytest.mark.asyncio
async def test_get_order_status_returns_none_when_exchange_has_no_record_of_the_order():
    """Binance code -2011 ("Unknown order sent") is a legitimate "not found" answer —
    already filled and pruned, cancelled, or lost (e.g. a testnet data reset)."""
    client = BinanceTestnetClient(api_key="x", api_secret="y", testnet=True)
    client._client = _FakeAsyncClientGetOrder(exc=_binance_api_exception(-2011))

    result = await client.get_order_status("BTCUSDT", "some-client-order-id")

    assert result is None


@pytest.mark.asyncio
async def test_get_order_status_propagates_errors_other_than_unknown_order():
    """2026-08-09 incident: collapsing every failure (network blips included) into the
    same None as a real -2011 let a transient error be misread as 'this order doesn't
    exist', which downstream logic then acted on incorrectly. Only -2011 is swallowed —
    anything else must propagate so the caller's broad exception handler retries instead
    of silently misinterpreting the failure."""
    client = BinanceTestnetClient(api_key="x", api_secret="y", testnet=True)
    client._client = _FakeAsyncClientGetOrder(exc=_binance_api_exception(-1021, "Timestamp outside recvWindow"))

    with pytest.raises(BinanceAPIException):
        await client.get_order_status("BTCUSDT", "some-client-order-id")
