"""Fase 5 entry point (spec 09) — run once a day (Railway Cron Jobs or any cron/scheduler).
Read-only over the persistence layer. Writes learnings/AAAA-MM-DD.md and, for findings with
enough sample size, drafts a changes/ proposal. Never applies anything on its own.

Usage:
    python scripts/run_daily_learning.py [--date AAAA-MM-DD]
"""

from __future__ import annotations

import argparse
import os
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from tradingbot.learning_engine.change_proposals import draft_change_proposals
from tradingbot.learning_engine.daily_report import write_daily_report
from tradingbot.learning_engine.github_publish import maybe_publish
from tradingbot.persistence.db import get_session_factory

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="AAAA-MM-DD (default: ontem, UTC)")
    args = parser.parse_args()

    report_date = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)

    session_factory = get_session_factory(os.environ.get("DATABASE_URL"))
    session = session_factory()

    path, report = write_daily_report(session, report_date)
    print(
        f"Relatório salvo em {path} ({report.num_trades} trades, "
        f"win rate líquido {report.net_win_rate:.0%}, P&L líquido {report.net_total_pnl:.2f})"
    )

    proposals = draft_change_proposals(report_date, report)
    if not proposals:
        print("Nenhuma proposta de mudança gerada hoje.")
    for proposal_path in proposals:
        print(f"Proposta gerada: {proposal_path} (status: pendente — requer revisão humana)")

    # 2026-08-15: containers de cron do Railway são efêmeros — sem publicar num branch, o
    # arquivo acima não sobrevive nem fica visível a ninguém (specs/09).
    result = maybe_publish(
        files=[path, *proposals],
        branch_suffix=report_date.isoformat(),
        commit_message=f"Aprendizado diário {report_date.isoformat()}",
        pr_title=f"Aprendizado diário — {report_date.isoformat()}",
        pr_body="Gerado automaticamente por run_daily_learning.py (specs/09). "
        "Nenhuma mudança é aplicada sozinha — revisão humana decide.",
    )
    if result is None:
        print("GITHUB_TOKEN não configurado — arquivo(s) só gravado(s) localmente.")
    else:
        print(f"Publicado em {result.branch}: {result.pr_url}")


if __name__ == "__main__":
    main()
