"""Unit coverage for BinanceTestnetClient's own arithmetic — no real network/testnet
needed since _get_client() is monkeypatched with a fake recording client.

Exists because of a real bug (2026-07-31): place_stop_loss_order rounded stopPrice to the
tick size but not the limit price (stop_price * 0.999/1.001) — Binance rejected every
single stop-loss placement with PRICE_FILTER in production, since multiplying an
already-tick-aligned price by 0.999 almost always breaks that alignment again.
"""

from decimal import Decimal

import pytest

from tradingbot.execution.client import BinanceTestnetClient


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
