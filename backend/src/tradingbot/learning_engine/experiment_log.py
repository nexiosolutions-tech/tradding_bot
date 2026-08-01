"""Experiment memory — spec 09. One line per experiment the agentic loop ran (hypothesis,
tool invoked, params, result, outcome), append-only. Two purposes: the loop never repeats
an experiment it already has a result for, and a human can audit everything the loop tried
even on cycles where it produced no proposal.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# backend/src/tradingbot/learning_engine/experiment_log.py -> parents[4] is the repo root.
DEFAULT_EXPERIMENTS_PATH = Path(__file__).resolve().parents[4] / "learnings" / "experiments.jsonl"

OUTCOME_NO_FINDING = "sem_achado"
OUTCOME_PROPOSAL_DRAFTED = "proposta_redigida"
OUTCOME_BUDGET_EXHAUSTED = "orcamento_esgotado"


@dataclass(frozen=True)
class ExperimentRecord:
    ts: int
    hypothesis: str
    tool: str
    params: dict = field(default_factory=dict)
    result_summary: dict = field(default_factory=dict)
    outcome: str = OUTCOME_NO_FINDING
    changes_file: str | None = None


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


def already_tried(experiments: list[ExperimentRecord], tool: str, params: dict) -> bool:
    """A tool call is a repeat if the same tool was already invoked with the exact same
    parameters — a conservative, exact-match rule (spec 09: "nunca repete um experimento
    já registrado com o mesmo resultado")."""
    return any(e.tool == tool and e.params == params for e in experiments)
