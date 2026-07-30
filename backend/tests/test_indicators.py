from tradingbot.features.indicators import (
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
