"""Change-proposal drafting — spec 09. Turns a learning finding with enough sample size
into a draft in changes/, following the template in changes/README.md. This is the entire
extent of what the learning engine is allowed to do automatically: draft a document. A
human decides Aprovado/Rejeitado — see CLAUDE.md rule 6. Nothing here ever edits a spec or
touches risk/execution code.
"""

from __future__ import annotations

import re
from datetime import date as date_type
from pathlib import Path

from tradingbot.learning_engine.daily_report import MIN_SAMPLE_SIZE_FOR_CONFIDENT_FINDING, DailyReport, Finding

CHANGES_DIR = Path(__file__).resolve().parents[3] / "changes"


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:50]


def _render_proposal(report_date: date_type, finding: Finding) -> str:
    learnings_ref = f"learnings/{report_date.isoformat()}.md"
    return "\n".join(
        [
            f"# Change Proposal — {report_date.isoformat()} — {finding.title}",
            "",
            "**Status:** pendente",
            "",
            "## Evidência (origem)",
            f"- Ligada a: {learnings_ref}",
            f"- {finding.observation}",
            "",
            "## Proposta",
            f'- Investigar se a condição associada a "{finding.title}" deve levar a ajuste '
            "de threshold de entrada ou filtro de horário.",
            "- Esta proposta não altera nenhum parâmetro por si só — é um ponto de partida "
            "para revisão humana.",
            "",
            "## Classificação de risco da mudança",
            "- [x] Parâmetro de risco/execução (requer revisão humana obrigatória)",
            "",
            "## Validação proposta",
            "- Revalidar em backtest walk-forward (specs/07-backtesting-e-validacao.md) "
            "antes de qualquer aplicação.",
            "",
            "## Decisão",
            "- Aprovado/rejeitado por: ",
            "- Data: ",
            "- Justificativa: ",
            "",
        ]
    )


def draft_change_proposals(report_date: date_type, report: DailyReport) -> list[Path]:
    written: list[Path] = []
    actionable = [f for f in report.findings if f.sample_size >= MIN_SAMPLE_SIZE_FOR_CONFIDENT_FINDING]
    if not actionable:
        return written

    CHANGES_DIR.mkdir(parents=True, exist_ok=True)
    for finding in actionable:
        filename = f"{report_date.isoformat()}-{_slugify(finding.title)}.md"
        path = CHANGES_DIR / filename
        path.write_text(_render_proposal(report_date, finding))
        written.append(path)
    return written
