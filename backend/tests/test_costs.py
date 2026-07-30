import pytest

from tradingbot.backtesting.costs import FeeModel, SlippageModel


def test_fee_model_charges_taker_rate_on_notional():
    fee_model = FeeModel(taker_fee_pct=0.001)
    assert fee_model.fee(10_000) == pytest.approx(10.0)


def test_slippage_makes_buys_more_expensive():
    slippage = SlippageModel(slippage_bps=10)
    filled = slippage.apply(100.0, "buy")
    assert filled > 100.0
    assert filled == pytest.approx(100.1)


def test_slippage_makes_sells_receive_less():
    slippage = SlippageModel(slippage_bps=10)
    filled = slippage.apply(100.0, "sell")
    assert filled < 100.0
    assert filled == pytest.approx(99.9)


def test_slippage_rejects_unknown_side():
    slippage = SlippageModel()
    with pytest.raises(ValueError):
        slippage.apply(100.0, "hold")
