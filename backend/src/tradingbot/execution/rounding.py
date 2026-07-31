"""Rounding to Binance's exchange trading filters — spec 06. Uses Decimal throughout;
float arithmetic on step/tick sizes like 0.00001 reliably produces off-by-one-ulp errors
that push a value just past what floor/round would suggest.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal


def round_down_to_step(value: float, step: Decimal) -> float:
    """Floors `value` to the nearest multiple of `step` — Binance's LOT_SIZE filter."""
    if step <= 0:
        return value
    quantity = Decimal(str(value))
    steps = (quantity / step).to_integral_value(rounding=ROUND_DOWN)
    return float(steps * step)


def round_to_tick(value: float, tick: Decimal) -> float:
    """Floors `value` to the nearest multiple of `tick` — Binance's PRICE_FILTER."""
    return round_down_to_step(value, tick)


def meets_min_notional(quantity: float, price: float, min_notional: Decimal) -> bool:
    if min_notional <= 0:
        return True
    notional = Decimal(str(quantity)) * Decimal(str(price))
    return notional >= min_notional
