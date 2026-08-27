"""Experiment memory — spec 09. One line per experiment the agentic loop ran (hypothesis,
tool invoked, params, result, outcome), append-only. Two purposes: the loop never repeats
an experiment it already has a result for, and a human can audit everything the loop tried
even on cycles where it produced no proposal.

Shared component across modules (spec 14, Seção 9.2 — "mesmo componente, campo de
domínio na entrada, contadores separados por módulo"): the *code* is reused, the *log
file* per domain is not — each module points `path`/`DEFAULT_EXPERIMENTS_PATH_*` at its
own file, so a domain's selection bias (and its DSR N) never mixes with another's,
matching CLAUDE.md's "fundação de engenharia compartilhada, nunca estado ou dado".
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# backend/src/tradingbot/learning_engine/experiment_log.py -> parents[4] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_EXPERIMENTS_PATH = _REPO_ROOT / "learnings" / "experiments.jsonl"
DEFAULT_EXPERIMENTS_PATH_ACOES = _REPO_ROOT / "learnings" / "experiments_acoes.jsonl"

OUTCOME_NO_FINDING = "sem_achado"
OUTCOME_PROPOSAL_DRAFTED = "proposta_redigida"
OUTCOME_BUDGET_EXHAUSTED = "orcamento_esgotado"

DOMAIN_BOT = "bot"
DOMAIN_ACOES = "acoes"


@dataclass(frozen=True)
class ExperimentRecord:
    ts: int
    hypothesis: str
    tool: str
    params: dict = field(default_factory=dict)
    result_summary: dict = field(default_factory=dict)
    outcome: str = OUTCOME_NO_FINDING
    changes_file: str | None = None
    domain: str = DOMAIN_BOT  # default preserva leitura de linhas antigas sem o campo


def append_experiment(record: ExperimentRecord, path: Path = DEFAULT_EXPERIMENTS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(asdict(record)) + "\n")


def load_experiments(path: Path = DEFAULT_EXPERIMENTS_PATH) -> list[ExperimentRecord]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(ExperimentRecord(**json.loads(line)))
    return records


def already_tried(
    experiments: list[ExperimentRecord], tool: str, params: dict, domain: str = DOMAIN_BOT
) -> bool:
    """A tool call is a repeat if the same tool was already invoked with the exact same
    parameters **within the same domain** — a conservative, exact-match rule (spec 09:
    "nunca repete um experimento já registrado com o mesmo resultado"). Domain-scoped
    (spec 14, Seção 9.2) so a coincidental tool/params match across modules never
    suppresses a genuinely new attempt in the other domain."""
    return any(e.domain == domain and e.tool == tool and e.params == params for e in experiments)


def contar_experimentos_por_dominio(experiments: list[ExperimentRecord], domain: str) -> int:
    """N de tentativas registradas para um domínio — insumo direto do DSR (spec 14,
    Seção 9.2/10 critério 4): cada configuração testada deflaciona o resultado final, e
    o N tem que ser específico do domínio — tentativas do bot não podem inflar, nem ser
    infladas por, o viés de seleção do módulo de ações."""
    return sum(1 for e in experiments if e.domain == domain)
