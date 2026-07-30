from tradingbot.execution.idempotency import make_client_order_id


def test_same_inputs_produce_same_id():
    id1 = make_client_order_id("BTCUSDT", "entry", 1_700_000_000_000, attempt=0)
    id2 = make_client_order_id("BTCUSDT", "entry", 1_700_000_000_000, attempt=0)
    assert id1 == id2


def test_different_purpose_or_symbol_or_ts_produce_different_ids():
    base = make_client_order_id("BTCUSDT", "entry", 1_700_000_000_000)
    assert base != make_client_order_id("ETHUSDT", "entry", 1_700_000_000_000)
    assert base != make_client_order_id("BTCUSDT", "stop_loss", 1_700_000_000_000)
    assert base != make_client_order_id("BTCUSDT", "entry", 1_700_000_000_001)


def test_id_fits_binance_client_order_id_length_limit():
    order_id = make_client_order_id("BTCUSDT", "entry", 1_700_000_000_000)
    assert len(order_id) <= 36
