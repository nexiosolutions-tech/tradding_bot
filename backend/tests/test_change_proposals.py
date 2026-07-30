from datetime import date

from tradingbot.learning_engine.change_proposals import draft_change_proposals
from tradingbot.learning_engine.daily_report import DailyReport, Finding

REPORT_DATE = date(2026, 7, 30)


def test_no_proposals_when_all_findings_are_preliminary(tmp_path, monkeypatch):
    import tradingbot.learning_engine.change_proposals as change_proposals_module

    monkeypatch.setattr(change_proposals_module, "CHANGES_DIR", tmp_path / "changes")

    report = DailyReport(
        report_date=REPORT_DATE,
        num_trades=3,
        win_rate=0.0,
        total_pnl=-10.0,
        circuit_breaker_triggered=False,
        findings=[Finding(title="Win rate baixo no horário 05h UTC", observation="x", sample_size=3, preliminary=True)],
    )

    written = draft_change_proposals(REPORT_DATE, report)
    assert written == []
    assert not (tmp_path / "changes").exists()


def test_proposal_written_for_finding_with_enough_sample(tmp_path, monkeypatch):
    import tradingbot.learning_engine.change_proposals as change_proposals_module

    monkeypatch.setattr(change_proposals_module, "CHANGES_DIR", tmp_path / "changes")

    finding = Finding(
        title="Win rate baixo no horário 03h UTC",
        observation="win rate de 10% em 10 trade(s), P&L total -40.00",
        sample_size=10,
        preliminary=False,
    )
    report = DailyReport(
        report_date=REPORT_DATE,
        num_trades=10,
        win_rate=0.1,
        total_pnl=-40.0,
        circuit_breaker_triggered=False,
        findings=[finding],
    )

    written = draft_change_proposals(REPORT_DATE, report)

    assert len(written) == 1
    content = written[0].read_text()
    assert "**Status:** pendente" in content
    assert "learnings/2026-07-30.md" in content
    assert "win rate de 10%" in content
    assert "requer revisão humana" in content


def test_proposal_never_marks_itself_approved(tmp_path, monkeypatch):
    import tradingbot.learning_engine.change_proposals as change_proposals_module

    monkeypatch.setattr(change_proposals_module, "CHANGES_DIR", tmp_path / "changes")

    finding = Finding(title="Win rate baixo no horário 04h UTC", observation="x", sample_size=15, preliminary=False)
    report = DailyReport(REPORT_DATE, 15, 0.1, -10.0, False, [finding])

    written = draft_change_proposals(REPORT_DATE, report)
    content = written[0].read_text()

    assert "Aprovado/rejeitado por: " in content
    status_line = next(line for line in content.splitlines() if line.startswith("**Status:**"))
    assert status_line.strip() == "**Status:** pendente"
