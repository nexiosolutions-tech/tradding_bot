import pytest

from tradingbot.features.indicators import (
    ATR,
    EMA,
    RSI,
    BollingerBands,
    RealizedVolatility,
    RelativeVolume,
    SMA,
)


def test_sma_returns_none_until_window_full():
    sma = SMA(3)
    assert sma.update(1) is None
    assert sma.update(2) is None
    assert sma.update(3) == 2.0
    assert sma.update(6) == (2 + 3 + 6) / 3


def test_ema_first_value_seeds_with_price():
    ema = EMA(10)
    assert ema.update(100.0) == 100.0
    second = ema.update(110.0)
    assert 100.0 < second < 110.0


def test_rsi_is_100_when_all_gains():
    rsi = RSI(period=3)
    rsi.update(10)
    rsi.update(11)
    rsi.update(12)
    value = rsi.update(13)
    assert value == 100.0


def test_rsi_is_bounded_between_0_and_100():
    rsi = RSI(period=5)
    prices = [10, 9, 11, 8, 12, 7, 13, 6, 14, 5]
    values = [v for p in prices if (v := rsi.update(p)) is not None]
    assert values
    assert all(0.0 <= v <= 100.0 for v in values)


def test_bollinger_bands_none_until_window_full():
    bb = BollingerBands(period=3, num_std=2.0)
    assert bb.update(10) == (None, None, None)
    assert bb.update(10) == (None, None, None)
    mid, upper, lower = bb.update(10)
    assert mid == 10.0
    assert upper == 10.0
    assert lower == 10.0


def test_bollinger_percent_b_at_lower_band_is_zero():
    bb = BollingerBands(period=3, num_std=2.0)
    for p in (8, 10, 12):
        bb.update(p)
    percent_b = bb.percent_b(bb.lower)
    assert abs(percent_b - 0.0) < 1e-9


def test_relative_volume_excludes_current_bar_from_its_own_average():
    rv = RelativeVolume(period=2)
    rv.update(100)
    rv.update(100)
    result = rv.update(1000)
    assert result == 10.0  # 1000 / avg(100, 100), not 1000 / avg(100, 100, 1000)


def test_realized_volatility_zero_for_constant_price():
    vol = RealizedVolatility(period=3)
    result = None
    for _ in range(5):
        result = vol.update(100.0)
    assert result == 0.0


def test_atr_none_until_warmup_period():
    atr = ATR(period=3)
    assert atr.update(high=101, low=99, close=100) is None
    assert atr.update(high=102, low=99, close=101) is None
    assert atr.update(high=103, low=100, close=102) is not None


def test_atr_sees_intrabar_range_that_close_to_close_volatility_misses():
    """The gap this closes: a candle with a huge wick in both directions but a flat
    close looks perfectly calm to RealizedVolatility (close-to-close), but ATR sees the
    real range via true range (high-low, or the gap from the previous close)."""
    atr = ATR(period=3)
    vol = RealizedVolatility(period=3)
    closes = [100.0, 100.0, 100.0, 100.0]
    highs = [100.0, 150.0, 100.0, 150.0]  # huge wick up every other candle
    lows = [100.0, 50.0, 100.0, 50.0]  # huge wick down every other candle

    atr_value = None
    vol_value = None
    for h, low, c in zip(highs, lows, closes):
        atr_value = atr.update(high=h, low=low, close=c)
        vol_value = vol.update(c)

    assert vol_value == 0.0  # close never moves — blind to the wicks
    assert atr_value is not None and atr_value > 0  # sees the real intrabar range


def test_atr_true_range_includes_gap_from_previous_close():
    atr = ATR(period=2)
    atr.update(high=101, low=99, close=100)  # 1st true range = high-low = 2 (seeds avg_tr)
    # Next candle's high/low don't span much, but it gapped up hard from the prior close.
    value = atr.update(high=121, low=120, close=120.5)
    assert value is not None
    # 2nd true range = max(high-low, |high-prev_close|, |low-prev_close|) = max(1, 21, 20) = 21
    # Wilder smoothing: (avg_tr_prev * (period-1) + true_range) / period = (2*1 + 21) / 2
    expected_avg_tr = (2 * 1 + 21) / 2
    assert value == pytest.approx(expected_avg_tr)
