import pytest

from tradingbot.backtesting.runner import NoKlinesFetchedError, run_and_save_backtest
from tradingbot.ingestion.schema import EventType, MarketEvent


def _closed_kline(symbol, close, ts):
    return MarketEvent(
        symbol=symbol,
        event_type=EventType.KLINE,
        exchange_ts=ts,
        local_ts=ts,
        sequence_id=ts,
        payload={
            "open_time": ts - 60_000,
            "close_time": ts,
            "interval": "1m",
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 100.0,
            "is_closed": True,
        },
    )


def _fake_klines(n=50, start_price=100.0):
    return [_closed_kline("BTCUSDT", start_price + i * 0.01, i * 60_000) for i in range(n)]


def test_run_and_save_backtest_writes_report(tmp_path, monkeypatch):
    import tradingbot.backtesting.runner as runner_module

    monkeypatch.setattr(
        runner_module.BinanceRestClient, "fetch_klines", lambda self, *a, **k: _fake_klines()
    )

    run_dir, num_klines = run_and_save_backtest(tmp_path, symbol="BTCUSDT", interval="1m", days=7)

    assert num_klines == 50
    assert (run_dir / "report.json").exists()
    assert (run_dir / "report.md").exists()
    assert run_dir.parent == tmp_path
    assert run_dir.name.startswith("BTCUSDT_1m_7d_")


def test_run_and_save_backtest_raises_when_no_klines(tmp_path, monkeypatch):
    import tradingbot.backtesting.runner as runner_module

    monkeypatch.setattr(runner_module.BinanceRestClient, "fetch_klines", lambda self, *a, **k: [])

    with pytest.raises(NoKlinesFetchedError):
        run_and_save_backtest(tmp_path, symbol="BTCUSDT", interval="1m", days=7)

    assert list(tmp_path.iterdir()) == []
