"""Backtest report generation — spec 07. Persists a run so it's reviewable later, and so the
dashboard's "Modelo" view (spec 08) has something to read from a future version of this."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from tradingbot.backtesting.engine import BacktestEngine
from tradingbot.backtesting.metrics import BacktestMetrics, compute_metrics


def build_report(engine: BacktestEngine) -> tuple[BacktestMetrics, dict]:
    metrics = compute_metrics(engine.trades, engine.equity_curve)
    raw = {
        "metrics": asdict(metrics),
        "trades": [asdict(t) for t in engine.trades],
        "equity_curve": engine.equity_curve,
        "rejected_signals": engine.rejected_signals,
        "final_equity": engine.equity,
        "circuit_breaker_triggered": engine.risk.circuit_breaker_triggered,
        "circuit_breaker_triggered_at": engine.risk.circuit_breaker_triggered_at,
    }
    return metrics, raw


def _render_markdown(run_name: str, metrics: BacktestMetrics, raw: dict) -> str:
    lines = [
        f"# Backtest Report — {run_name}",
        "",
        "## Métricas",
        f"- Trades: {metrics.num_trades}",
        f"- Win rate: {metrics.win_rate:.1%}",
        f"- Profit factor: {metrics.profit_factor:.2f}",
        f"- P&L total: {metrics.total_pnl:.2f}",
        f"- Taxas pagas: {metrics.total_fees:.2f}",
        f"- Drawdown máximo: {metrics.max_drawdown_pct:.1%}",
        f"- Capital final: {raw['final_equity']:.2f}",
        f"- Sinais rejeitados (sem stop-loss): {len(raw['rejected_signals'])}",
        f"- Circuit breaker acionado: {raw['circuit_breaker_triggered']}",
        "",
        "## P&L por hora (UTC)",
    ]
    for hour in sorted(metrics.pnl_by_hour):
        lines.append(f"- {hour:02d}h: {metrics.pnl_by_hour[hour]:.2f}")
    lines.append("")
    lines.append(
        "_Este relatório é um artefato de engenharia de validação de estratégia, não "
        "recomendação de investimento (ver specs/00-visao-geral-e-objetivos.md)._"
    )
    return "\n".join(lines)


def save_report(engine: BacktestEngine, output_dir: Path, run_name: str) -> Path:
    run_dir = output_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    metrics, raw = build_report(engine)

    (run_dir / "report.json").write_text(json.dumps(raw, indent=2, default=str))
    (run_dir / "report.md").write_text(_render_markdown(run_name, metrics, raw))

    return run_dir
