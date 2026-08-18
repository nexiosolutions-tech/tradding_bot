"""Incremental technical indicators — spec 03.

Every indicator here is O(1) per update (or O(window) bounded by a fixed-size deque) and
deterministic: the same sequence of inputs always produces the same sequence of outputs,
which is what makes backtesting and production comparable.
"""

from __future__ import annotations

import math
from collections import deque


class SMA:
    def __init__(self, period: int):
        self._window: deque[float] = deque(maxlen=period)

    def update(self, value: float) -> float | None:
        self._window.append(value)
        if len(self._window) < self._window.maxlen:
            return None
        return sum(self._window) / len(self._window)


class EMA:
    def __init__(self, period: int):
        self.period = period
        self._alpha = 2 / (period + 1)
        self.value: float | None = None

    def update(self, price: float) -> float:
        self.value = price if self.value is None else self._alpha * price + (1 - self._alpha) * self.value
        return self.value


class RSI:
    """Wilder's smoothing, incremental. First `period` updates return None (warm-up)."""

    def __init__(self, period: int = 14):
        self.period = period
        self._avg_gain: float | None = None
        self._avg_loss: float | None = None
        self._prev_price: float | None = None
        self._count = 0
        self.value: float | None = None

    def update(self, price: float) -> float | None:
        if self._prev_price is None:
            self._prev_price = price
            return None

        change = price - self._prev_price
        self._prev_price = price
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        self._count += 1

        if self._avg_gain is None:
            self._avg_gain = gain
            self._avg_loss = loss
        else:
            self._avg_gain = (self._avg_gain * (self.period - 1) + gain) / self.period
            self._avg_loss = (self._avg_loss * (self.period - 1) + loss) / self.period

        if self._count < self.period:
            return None

        if self._avg_loss == 0:
            self.value = 100.0
        else:
            rs = self._avg_gain / self._avg_loss
            self.value = 100 - (100 / (1 + rs))
        return self.value


class ATR:
    """Average True Range, Wilder-smoothed (same smoothing style as RSI). Captures
    intrabar range (wicks) that RealizedVolatility's close-to-close log returns ignore
    entirely — a candle that wicks hard in both directions but closes flat looks
    perfectly calm to RealizedVolatility, but ATR sees the real range."""

    def __init__(self, period: int = 14):
        self.period = period
        self._prev_close: float | None = None
        self._avg_tr: float | None = None
        self._count = 0
        self.value: float | None = None

    def update(self, high: float, low: float, close: float) -> float | None:
        true_range = (
            high - low
            if self._prev_close is None
            else max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        )
        self._prev_close = close
        self._count += 1

        self._avg_tr = true_range if self._avg_tr is None else (self._avg_tr * (self.period - 1) + true_range) / self.period

        if self._count < self.period:
            return None
        self.value = self._avg_tr
        return self.value


class MACD:
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self._fast = EMA(fast)
        self._slow = EMA(slow)
        self._signal = EMA(signal)
        self.macd: float | None = None
        self.signal_value: float | None = None
        self.histogram: float | None = None

    def update(self, price: float) -> tuple[float, float, float]:
        fast_v = self._fast.update(price)
        slow_v = self._slow.update(price)
        self.macd = fast_v - slow_v
        self.signal_value = self._signal.update(self.macd)
        self.histogram = self.macd - self.signal_value
        return self.macd, self.signal_value, self.histogram


class RollingWindow:
    def __init__(self, size: int):
        self.size = size
        self._values: deque[float] = deque(maxlen=size)

    def update(self, value: float) -> "RollingWindow":
        self._values.append(value)
        return self

    @property
    def is_full(self) -> bool:
        return len(self._values) == self.size

    def mean(self) -> float | None:
        if not self._values:
            return None
        return sum(self._values) / len(self._values)

    def stdev(self) -> float | None:
        n = len(self._values)
        if n < 2:
            return None
        m = self.mean()
        variance = sum((v - m) ** 2 for v in self._values) / n
        return math.sqrt(variance)


class BollingerBands:
    def __init__(self, period: int = 20, num_std: float = 2.0):
        self._window = RollingWindow(period)
        self.num_std = num_std
        self.middle: float | None = None
        self.upper: float | None = None
        self.lower: float | None = None

    def update(self, price: float) -> tuple[float | None, float | None, float | None]:
        self._window.update(price)
        if not self._window.is_full:
            self.middle = self.upper = self.lower = None
            return self.middle, self.upper, self.lower
        self.middle = self._window.mean()
        std = self._window.stdev()
        self.upper = self.middle + self.num_std * std
        self.lower = self.middle - self.num_std * std
        return self.middle, self.upper, self.lower

    def percent_b(self, price: float) -> float | None:
        if self.upper is None or self.lower is None or self.upper == self.lower:
            return None
        return (price - self.lower) / (self.upper - self.lower)


class RelativeVolume:
    """Current volume divided by the trailing average — computed *before* the current
    value is folded into the average, so it never compares a bar against itself."""

    def __init__(self, period: int = 20):
        self._window = RollingWindow(period)

    def update(self, volume: float) -> float | None:
        avg = self._window.mean() if self._window.is_full else None
        self._window.update(volume)
        if avg is None or avg == 0:
            return None
        return volume / avg


class ReturnOverWindow:
    """Percentage return between the price `period` candles ago and the current price —
    the building block for cross-asset relative-strength features (spec 03): comparing two
    assets' returns over the identical window says which one is leading/lagging, independent
    of either asset's absolute price level."""

    def __init__(self, period: int):
        self._window: deque[float] = deque(maxlen=period + 1)

    def update(self, price: float) -> float | None:
        self._window.append(price)
        if len(self._window) < self._window.maxlen:
            return None
        oldest = self._window[0]
        if oldest == 0:
            return None
        return (price - oldest) / oldest


class RealizedVolatility:
    """Rolling stdev of log returns."""

    def __init__(self, period: int = 20):
        self._window = RollingWindow(period)
        self._prev_price: float | None = None

    def update(self, price: float) -> float | None:
        if self._prev_price is None or price <= 0 or self._prev_price <= 0:
            self._prev_price = price
            return None
        ret = math.log(price / self._prev_price)
        self._prev_price = price
        self._window.update(ret)
        return self._window.stdev() if self._window.is_full else None
