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

from tradingbot.backtesting.costs import net_trade_pnl
from tradingbot.backtesting.metrics import win_rate
from tradingbot.persistence.repository import (
    count_agg_trade_buckets_in_range,
    count_order_book_snapshots_in_range,
    recent_engine_events,
    trades_in_range,
)

# backend/src/tradingbot/learning_engine/daily_report.py -> parents[4] is the repo root.
LEARNINGS_DIR = Path(__file__).resolve().parents[4] / "learnings"

MIN_SAMPLE_SIZE_FOR_CONFIDENT_FINDING = 10
HOUR_UNDERPERFORMANCE_WIN_RATE_THRESHOLD = 0.35

# Expected floors, not expected values — deliberately well below the theoretical max (1440
# for a 1/minute sampler, up to 86400 for a 1/second bucket that only emits when a trade
# actually occurred) so a brief redeploy/restart doesn't false-alarm. The failure mode this
# guards against (2026-08-18) is a collector dying silently for most/all of the day — that
# produces a near-zero count, not a slightly-low one — so a generous floor still catches it
# without crying wolf on routine restarts.
ORDER_BOOK_SNAPSHOT_DAILY_FLOOR = 500
AGG_TRADE_BUCKET_DAILY_FLOOR = 5_000

# (table label, environment each capture service currently targets, floor) — count is
# scoped to this one environment per table, not "any environment", so a healthy testnet
# capture can never mask a dead mainnet one or vice versa (2026-08-18 incident: depth is
# mainnet now via REST polling, aggtrade is still testnet pending its own conversion).
# Update the environment here when a capture service's target changes.
CAPTURE_FRESHNESS_TARGETS = [
    ("order_book_snapshots", "mainnet", ORDER_BOOK_SNAPSHOT_DAILY_FLOOR),
    ("agg_trade_buckets", "testnet", AGG_TRADE_BUCKET_DAILY_FLOOR),
]

# 2026-08-17: TradeRecord.pnl/fees_paid never reflect a real trading fee — fees_paid is
# hardcoded 0.0 at trade-close time (execution/orchestrator.py) because testnet genuinely
# charges none, but that means raw pnl systematically overstates what the same trade would
# net on mainnet (confirmed earlier this project: every real testnet fill reports
# commission "0.00000000"). Every finding/number in this report is corrected via
# backtesting.costs.net_trade_pnl (spec 07's own FeeModel) — this module's own docstring
# already promises "a day of live trading and a backtest run are judged by the same
# yardstick," which raw pnl broke silently until now.


def _net_win_rate(trades: list) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if net_trade_pnl(t) > 0)
    return wins / len(trades)


@dataclass(frozen=True)
class Finding:
    title: str
    observation: str
    sample_size: int
    preliminary: bool


@dataclass(frozen=True)
class CaptureFreshness:
    label: str
    environment: str
    count_last_24h: int
    expected_floor: int

    @property
    def ok(self) -> bool:
        return self.count_last_24h >= self.expected_floor


@dataclass(frozen=True)
class DailyReport:
    report_date: date_type
    num_trades: int
    win_rate: float
    total_pnl: float
    net_win_rate: float
    net_total_pnl: float
    circuit_breaker_triggered: bool
    findings: list[Finding] = field(default_factory=list)
    capture_freshness: list[CaptureFreshness] = field(default_factory=list)


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
        wr = _net_win_rate(hour_trades)
        if wr < HOUR_UNDERPERFORMANCE_WIN_RATE_THRESHOLD:
            sample = len(hour_trades)
            findings.append(
                Finding(
                    title=f"Win rate líquido baixo no horário {hour:02d}h UTC",
                    observation=(
                        f"win rate líquido (com taxa) de {wr:.0%} em {sample} trade(s), "
                        f"P&L líquido total {sum(net_trade_pnl(t) for t in hour_trades):.2f}"
                    ),
                    sample_size=sample,
                    preliminary=sample < MIN_SAMPLE_SIZE_FOR_CONFIDENT_FINDING,
                )
            )
    return findings


_CAPTURE_COUNT_FNS = {
    "order_book_snapshots": count_order_book_snapshots_in_range,
    "agg_trade_buckets": count_agg_trade_buckets_in_range,
}


def _capture_freshness(session, start_ms: int, end_ms: int) -> list[CaptureFreshness]:
    return [
        CaptureFreshness(
            label=label,
            environment=environment,
            count_last_24h=_CAPTURE_COUNT_FNS[label](session, start_ms, end_ms, environment),
            expected_floor=floor,
        )
        for label, environment, floor in CAPTURE_FRESHNESS_TARGETS
    ]


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
        net_win_rate=_net_win_rate(trades),
        net_total_pnl=sum(net_trade_pnl(t) for t in trades),
        circuit_breaker_triggered=circuit_breaker_triggered,
        findings=_find_underperforming_hours(trades) if trades else [],
        capture_freshness=_capture_freshness(session, start_ms, end_ms),
    )


def render_markdown(report: DailyReport) -> str:
    lines = [
        f"# Learnings — {report.report_date.isoformat()}",
        "",
        "## Resumo do dia",
        f"- Trades executados: {report.num_trades}",
        f"- Win rate do dia (bruto, sem taxa): {report.win_rate:.0%}"
        if report.num_trades
        else "- Win rate do dia: N/A (sem trades)",
        f"- P&L do dia (bruto, sem taxa): {report.total_pnl:.2f}",
        f"- **Win rate do dia (líquido, com taxa real): {report.net_win_rate:.0%}**"
        if report.num_trades
        else "- Win rate líquido: N/A (sem trades)",
        f"- **P&L do dia (líquido, com taxa real): {report.net_total_pnl:.2f}**",
        "  - testnet não cobra taxa real — o bruto acima superestima sistematicamente o "
        "resultado; o líquido usa o mesmo FeeModel do backtest (spec 07) e é o número que "
        "importa para qualquer decisão.",
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
        "## Frescor da captura de dados (order book / fluxo de ordens)",
        "Contagem de linhas gravadas nas últimas 24h por tabela de captura contínua — um "
        "coletor que parou de gravar não gera nenhum erro visível por conta própria, só "
        "silêncio; esta seção existe pra transformar esse silêncio num sinal (2026-08-18).",
    ]
    for freshness in report.capture_freshness:
        status = "OK" if freshness.ok else "**ALERTA — abaixo do piso esperado**"
        lines.append(
            f"- `{freshness.label}` ({freshness.environment}): {freshness.count_last_24h} "
            f"linha(s) nas últimas 24h (piso esperado: {freshness.expected_floor}) — {status}"
        )

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
