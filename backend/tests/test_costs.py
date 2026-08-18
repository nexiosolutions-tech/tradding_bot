import pytest

from tradingbot.backtesting.costs import FeeModel, SlippageModel, net_trade_pnl


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


class _Trade:
    def __init__(self, entry_price, exit_price, size, pnl):
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.size = size
        self.pnl = pnl


def test_net_trade_pnl_subtracts_entry_and_exit_fees():
    trade = _Trade(entry_price=100.0, exit_price=110.0, size=1.0, pnl=10.0)
    fee_model = FeeModel(taker_fee_pct=0.001)
    expected_fees = fee_model.fee(100.0) + fee_model.fee(110.0)
    assert net_trade_pnl(trade, fee_model) == pytest.approx(10.0 - expected_fees)


def test_net_trade_pnl_defaults_to_a_fee_model_when_none_given():
    trade = _Trade(entry_price=100.0, exit_price=110.0, size=1.0, pnl=10.0)
    assert net_trade_pnl(trade) == pytest.approx(net_trade_pnl(trade, FeeModel()))


def test_net_trade_pnl_can_flip_a_marginal_win_into_a_loss():
    trade = _Trade(entry_price=100.0, exit_price=100.15, size=1.0, pnl=0.15)
    assert trade.pnl > 0
    assert net_trade_pnl(trade) < 0
