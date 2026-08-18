from datetime import date, datetime, timezone

from tradingbot.backtesting.costs import net_trade_pnl
from tradingbot.learning_engine.daily_report import build_daily_report, render_markdown, write_daily_report
from tradingbot.persistence.db import get_session_factory
from tradingbot.persistence.repository import record_engine_event, record_trade
from tradingbot.persistence.models import EngineEvent, TradeRecord

REPORT_DATE = date(2026, 7, 30)


def _ts_at_hour(hour: int) -> int:
    dt = datetime(REPORT_DATE.year, REPORT_DATE.month, REPORT_DATE.day, hour, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _session(tmp_path):
    factory = get_session_factory(f"sqlite:///{tmp_path}/learning-test.db")
    return factory()


def _add_trade(session, hour: int, pnl: float, i: int):
    record_trade(
        session,
        TradeRecord(
            symbol="BTCUSDT",
            entry_order_id=f"e{hour}-{i}",
            exit_order_id=f"x{hour}-{i}",
            entry_ts=_ts_at_hour(hour) - 60_000,
            exit_ts=_ts_at_hour(hour),
            entry_price=100.0,
            exit_price=100.0 + pnl,
            size=1.0,
            pnl=pnl,
            fees_paid=0.1,
            exit_reason="signal_exit",
            strategy_version="test-v1",
        ),
    )


def test_report_with_no_trades_is_empty_but_valid(tmp_path):
    session = _session(tmp_path)
    report = build_daily_report(session, REPORT_DATE)

    assert report.num_trades == 0
    assert report.win_rate == 0.0
    assert report.findings == []
    assert "Nenhum achado relevante hoje." in render_markdown(report)


def test_underperforming_hour_flagged_with_enough_sample(tmp_path):
    session = _session(tmp_path)
    # hour 3: 10 trades, only 1 win -> 10% win rate, well past the sample threshold
    for i in range(10):
        _add_trade(session, hour=3, pnl=10.0 if i == 0 else -5.0, i=i)
    # hour 10: 12 trades, 8 wins -> 66% win rate, should NOT be flagged
    for i in range(12):
        _add_trade(session, hour=10, pnl=5.0 if i < 8 else -5.0, i=i)

    report = build_daily_report(session, REPORT_DATE)

    titles = [f.title for f in report.findings]
    assert any("03h" in t for t in titles)
    assert not any("10h" in t for t in titles)

    flagged = next(f for f in report.findings if "03h" in f.title)
    assert flagged.sample_size == 10
    assert flagged.preliminary is False


def test_small_sample_hour_is_marked_preliminary(tmp_path):
    session = _session(tmp_path)
    for i in range(3):
        _add_trade(session, hour=5, pnl=-5.0, i=i)

    report = build_daily_report(session, REPORT_DATE)

    assert len(report.findings) == 1
    assert report.findings[0].preliminary is True
    markdown = render_markdown(report)
    assert "preliminar" in markdown


def test_circuit_breaker_detected_within_day_bounds(tmp_path):
    session = _session(tmp_path)
    record_engine_event(
        session,
        EngineEvent(
            ts=_ts_at_hour(12),
            from_state="ANALISANDO",
            to_state="PARADO_CIRCUIT_BREAKER",
            reason="circuit breaker acionado",
            triggered_by_human=False,
        ),
    )

    report = build_daily_report(session, REPORT_DATE)
    assert report.circuit_breaker_triggered is True


def test_net_pnl_can_flip_a_marginal_raw_win_into_a_net_loss():
    """The fee-blind-spot finding this project already made by hand, now built into the
    automated report: testnet's real fees_paid is always 0.0 (execution/orchestrator.py),
    so a tiny raw win can look profitable while a real round-trip fee (~0.2% notional)
    would have eaten it entirely."""

    class _Trade:
        entry_price = 100.0
        exit_price = 100.15
        size = 1.0
        pnl = 0.15

    assert _Trade.pnl > 0  # raw: a win
    assert net_trade_pnl(_Trade()) < 0  # net of realistic fees: actually a loss


def test_daily_report_net_win_rate_is_lower_than_raw_when_wins_are_marginal(tmp_path):
    session = _session(tmp_path)
    # 5 trades that are tiny raw wins (+0.10) -- each one is a net loss once fees apply.
    for i in range(5):
        _add_trade(session, hour=8, pnl=0.10, i=i)

    report = build_daily_report(session, REPORT_DATE)

    assert report.win_rate == 1.0  # raw: every trade "won"
    assert report.net_win_rate == 0.0  # net: every trade actually lost money
    assert report.net_total_pnl < report.total_pnl


def test_render_markdown_shows_both_raw_and_net_figures(tmp_path):
    session = _session(tmp_path)
    _add_trade(session, hour=8, pnl=0.10, i=0)
    report = build_daily_report(session, REPORT_DATE)
    markdown = render_markdown(report)

    assert "bruto, sem taxa" in markdown
    assert "líquido, com taxa real" in markdown


def test_underperforming_hour_finding_uses_net_pnl_not_raw(tmp_path):
    """A hour whose raw win rate clears the 35% threshold but whose net (fee-corrected)
    win rate doesn't must still be flagged -- otherwise the automated report would miss
    exactly the kind of marginal-win pattern this fix exists to catch."""
    session = _session(tmp_path)
    for i in range(10):
        _add_trade(session, hour=6, pnl=0.10, i=i)  # 100% raw win rate, 0% net

    report = build_daily_report(session, REPORT_DATE)

    titles = [f.title for f in report.findings]
    assert any("06h" in t for t in titles)


def test_write_daily_report_creates_markdown_file(tmp_path, monkeypatch):
    import tradingbot.learning_engine.daily_report as daily_report_module

    monkeypatch.setattr(daily_report_module, "LEARNINGS_DIR", tmp_path / "learnings")
    session = _session(tmp_path)
    _add_trade(session, hour=8, pnl=15.0, i=0)

    path, report = write_daily_report(session, REPORT_DATE)

    assert path.exists()
    assert path.name == "2026-07-30.md"
    assert report.num_trades == 1
    assert "# Learnings — 2026-07-30" in path.read_text()
