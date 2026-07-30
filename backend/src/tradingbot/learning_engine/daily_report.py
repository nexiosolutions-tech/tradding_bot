"""Daily learning job — spec 09. Strictly read-only over the persistence layer; never
applies anything. Produces learnings/AAAA-MM-DD.md following the template in
learnings/README.md. Reuses the exact metric functions backtesting uses (spec 07), so a
day of live trading and a backtest run are judged by the same yardstick.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime, timezone
from pathlib import Path

from tradingbot.backtesting.metrics import win_rate
from tradingbot.persistence.repository import recent_engine_events, trades_in_range

# backend/src/tradingbot/learning_engine/daily_report.py -> parents[4] is the repo root.
LEARNINGS_DIR = Path(__file__).resolve().parents[4] / "learnings"

MIN_SAMPLE_SIZE_FOR_CONFIDENT_FINDING = 10
HOUR_UNDERPERFORMANCE_WIN_RATE_THRESHOLD = 0.35


@dataclass(frozen=True)
class Finding:
    title: str
    observation: str
    sample_size: int
    preliminary: bool


@dataclass(frozen=True)
class DailyReport:
    report_date: date_type
    num_trades: int
    win_rate: float
    total_pnl: float
    circuit_breaker_triggered: bool
    findings: list[Finding] = field(default_factory=list)


def _day_bounds_ms(report_date: date_type) -> tuple[int, int]:
    start = datetime(report_date.year, report_date.month, report_date.day, tzinfo=timezone.utc)
    start_ms = int(start.timestamp() * 1000)
    return start_ms, start_ms + 24 * 60 * 60 * 1000 - 1


def _find_underperforming_hours(trades: list) -> list[Finding]:
    by_hour: dict[int, list] = {}
    for t in trades:
        hour = datetime.fromtimestamp(t.exit_ts / 1000, tz=timezone.utc).hour
        by_hour.setdefault(hour, []).append(t)

    findings = []
    for hour, hour_trades in sorted(by_hour.items()):
        wr = win_rate(hour_trades)
        if wr < HOUR_UNDERPERFORMANCE_WIN_RATE_THRESHOLD:
            sample = len(hour_trades)
            findings.append(
                Finding(
                    title=f"Win rate baixo no horário {hour:02d}h UTC",
                    observation=(
                        f"win rate de {wr:.0%} em {sample} trade(s), "
                        f"P&L total {sum(t.pnl for t in hour_trades):.2f}"
                    ),
                    sample_size=sample,
                    preliminary=sample < MIN_SAMPLE_SIZE_FOR_CONFIDENT_FINDING,
                )
            )
    return findings


def build_daily_report(session, report_date: date_type) -> DailyReport:
    start_ms, end_ms = _day_bounds_ms(report_date)
    trades = trades_in_range(session, start_ms, end_ms)

    events = recent_engine_events(session, limit=500)
    day_events = [e for e in events if start_ms <= e.ts <= end_ms]
    circuit_breaker_triggered = any(e.to_state == "PARADO_CIRCUIT_BREAKER" for e in day_events)

    return DailyReport(
        report_date=report_date,
        num_trades=len(trades),
        win_rate=win_rate(trades),
        total_pnl=sum(t.pnl for t in trades),
        circuit_breaker_triggered=circuit_breaker_triggered,
        findings=_find_underperforming_hours(trades) if trades else [],
    )


def render_markdown(report: DailyReport) -> str:
    lines = [
        f"# Learnings — {report.report_date.isoformat()}",
        "",
        "## Resumo do dia",
        f"- Trades executados: {report.num_trades}",
        f"- Win rate do dia: {report.win_rate:.0%}" if report.num_trades else "- Win rate do dia: N/A (sem trades)",
        f"- P&L do dia: {report.total_pnl:.2f}",
        f"- Estado do circuit breaker: {'acionado' if report.circuit_breaker_triggered else 'não acionado'}",
        "",
        "## Achados",
    ]

    if not report.findings:
        lines.append("Nenhum achado relevante hoje.")
    for i, finding in enumerate(report.findings, start=1):
        lines += [
            "",
            f"### Achado {i}: {finding.title}",
            f"- Observação: {finding.observation}",
            f"- Amostra: {finding.sample_size} trade(s)"
            + (" (preliminar — amostra pequena)" if finding.preliminary else ""),
        ]

    lines += [
        "",
        "## Divergência backtest vs. produção",
        "Não avaliado automaticamente nesta versão — comparação manual pendente.",
        "",
        "## Sugestões de investigação (não são mudanças aprovadas)",
    ]
    actionable = [f for f in report.findings if not f.preliminary]
    if actionable:
        for f in actionable:
            lines.append(f"- {f.title}: proposta de mudança gerada em `changes/` para revisão.")
    else:
        lines.append("Nenhum achado com amostra suficiente para propor mudança ainda.")

    return "\n".join(lines)


def write_daily_report(session, report_date: date_type) -> tuple[Path, DailyReport]:
    report = build_daily_report(session, report_date)
    LEARNINGS_DIR.mkdir(parents=True, exist_ok=True)
    path = LEARNINGS_DIR / f"{report.report_date.isoformat()}.md"
    path.write_text(render_markdown(report))
    return path, report
