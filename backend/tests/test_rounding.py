from decimal import Decimal

from tradingbot.execution.rounding import meets_min_notional, round_down_to_step, round_to_tick


def test_round_down_to_step_floors_to_lot_size():
    # A float-imprecision classic: 0.1 + 0.2 style errors must not push the result up a step.
    assert round_down_to_step(1.23456789, Decimal("0.001")) == 1.234
    assert round_down_to_step(0.0075, Decimal("0.001")) == 0.007


def test_round_down_to_step_handles_known_float_precision_traps():
    # 2.32 / 0.01 in raw float arithmetic drifts to 231.99999999999997 -> would floor to 2.31
    assert round_down_to_step(2.32, Decimal("0.01")) == 2.32


def test_round_down_to_step_zero_step_is_noop():
    assert round_down_to_step(1.23456, Decimal("0")) == 1.23456


def test_round_to_tick_floors_price():
    assert round_to_tick(101.2345, Decimal("0.01")) == 101.23


def test_meets_min_notional_true_when_no_minimum_configured():
    assert meets_min_notional(quantity=0.0001, price=100.0, min_notional=Decimal("0"))


def test_meets_min_notional_rejects_below_threshold():
    assert not meets_min_notional(quantity=0.00001, price=100.0, min_notional=Decimal("10"))


def test_meets_min_notional_accepts_at_or_above_threshold():
    assert meets_min_notional(quantity=0.1, price=100.0, min_notional=Decimal("10"))
