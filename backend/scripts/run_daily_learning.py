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
    print(f"Relatório salvo em {path} ({report.num_trades} trades, win rate {report.win_rate:.0%})")

    proposals = draft_change_proposals(report_date, report)
    if not proposals:
        print("Nenhuma proposta de mudança gerada hoje.")
    for proposal_path in proposals:
        print(f"Proposta gerada: {proposal_path} (status: pendente — requer revisão humana)")


if __name__ == "__main__":
    main()
