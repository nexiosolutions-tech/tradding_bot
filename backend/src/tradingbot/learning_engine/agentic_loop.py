"""Loop controller — spec 09. Drives the reasoning model through an iterative
investigate-decide-act cycle, bounded by a fixed iteration budget, over the tools in
`learning_engine.tools`. The only thing this module is allowed to write is a `changes/*.md`
file with **Status: pendente** — it never marks a proposal `aprovada`/`aplicada`, never
touches `main`, and (spec 09's isolation invariant) never imports `tradingbot.execution`.

`ReasoningClient` is a Protocol so the loop itself — budget enforcement, dedup against
past experiments, proposal drafting — is fully unit-testable with a scripted fake, without
needing a live Anthropic API key. `AnthropicReasoningClient` is the real implementation;
it has not been exercised against the live API in this codebase yet (no key configured in
this environment) — validate it end to end before relying on it for a real cycle.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import date as date_type
from pathlib import Path
from typing import Protocol

from tradingbot.ingestion.schema import MarketEvent
from tradingbot.learning_engine.experiment_log import (
    DEFAULT_EXPERIMENTS_PATH,
    OUTCOME_BUDGET_EXHAUSTED,
    OUTCOME_NO_FINDING,
    OUTCOME_PROPOSAL_DRAFTED,
    ExperimentRecord,
    already_tried,
    append_experiment,
    load_experiments,
)
from tradingbot.learning_engine.tools import CHANGES_DIR, Tool, build_tools

DEFAULT_MAX_ITERATIONS = 10


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict


@dataclass(frozen=True)
class ProposalDraft:
    title: str
    evidence: str
    proposal_text: str
    validation_summary: str
    risk_classification: str


@dataclass(frozen=True)
class ReasoningStep:
    """What the reasoning model decided to do this turn. Either `tool_call` is set (keep
    investigating) or it's None and `stop_reason`/`proposal` describe how the cycle ends."""

    hypothesis: str
    tool_call: ToolCall | None = None
    stop_reason: str | None = None
    proposal: ProposalDraft | None = None


class ReasoningClient(Protocol):
    def start(self, context: str) -> None: ...
    def next_step(self) -> ReasoningStep: ...
    def report_tool_result(self, tool_name: str, result: dict) -> None: ...


@dataclass
class FakeReasoningClient:
    """Test double — plays back a scripted sequence of ReasoningSteps. Records the context
    it started with and every tool result it's given, so tests can assert on both."""

    steps: list[ReasoningStep]
    started_with: str | None = field(default=None, init=False)
    reported_results: list[tuple[str, dict]] = field(default_factory=list, init=False)
    _index: int = field(default=0, init=False)

    def start(self, context: str) -> None:
        self.started_with = context

    def next_step(self) -> ReasoningStep:
        step = self.steps[self._index]
        self._index += 1
        return step

    def report_tool_result(self, tool_name: str, result: dict) -> None:
        self.reported_results.append((tool_name, result))


SYSTEM_PROMPT = (
    "Você é o motor de aprendizado contínuo do tradding_bot (specs/09-aprendizado-continuo.md). "
    "Sua tarefa é investigar a performance da estratégia de trading e, se encontrar evidência "
    "estatisticamente sólida (specs/07-backtesting-e-validacao.md: amostra mínima, validação "
    "out-of-sample, sem vazamento entre calibração e fold de teste), redigir uma proposta "
    "completa e pronta para revisão. Você NUNCA aplica nada sozinho — sua única saída possível "
    "é uma entrada em changes/ com Status: pendente, para decisão humana explícita. Não repita "
    "um experimento já tentado com os mesmos parâmetros exatos (verifique a memória fornecida). "
    "Conclua com conclude_investigation assim que não houver mais o que testar de forma "
    "produtiva, mesmo sem achado — um ciclo sem descoberta é um resultado válido."
)


def _tool_to_anthropic_schema(tool: Tool) -> dict:
    schema = dict(tool.parameters)
    properties = dict(schema.get("properties", {}))
    properties["_hypothesis"] = {
        "type": "string",
        "description": "O que você está testando com esta chamada, em uma frase.",
    }
    schema["properties"] = properties
    required = list(schema.get("required", []))
    if "_hypothesis" not in required:
        required.append("_hypothesis")
    schema["required"] = required
    return {"name": tool.name, "description": tool.description, "input_schema": schema}


CONCLUDE_TOOL_NAME = "conclude_investigation"

_CONCLUDE_TOOL_SCHEMA = {
    "name": CONCLUDE_TOOL_NAME,
    "description": (
        "Encerra o ciclo de investigação. Use stop_reason='sem_achado' quando não houver "
        "achado acionável, ou stop_reason='proposta_redigida' com 'proposal' preenchido "
        "quando tiver evidência suficiente para uma proposta completa."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "hypothesis": {"type": "string", "description": "Resumo da conclusão do ciclo."},
            "stop_reason": {"type": "string", "enum": [OUTCOME_NO_FINDING, OUTCOME_PROPOSAL_DRAFTED]},
            "proposal": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "evidence": {"type": "string"},
                    "proposal_text": {"type": "string"},
                    "validation_summary": {"type": "string"},
                    "risk_classification": {"type": "string"},
                },
            },
        },
        "required": ["hypothesis", "stop_reason"],
    },
}


class AnthropicReasoningClient:
    """Real implementation, driving Claude's tool-use API. Requires exactly one tool call
    (including `conclude_investigation`) per turn — the loop controller feeds the result
    back and asks for the next step, rather than letting the model batch several calls in
    one turn, so every experiment is individually logged and dedup-checked."""

    def __init__(self, tools: list[Tool], api_key: str | None = None, model: str = "claude-sonnet-5"):
        import anthropic  # imported lazily so the rest of this module works without the SDK installed

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._anthropic_tools = [_tool_to_anthropic_schema(t) for t in tools] + [_CONCLUDE_TOOL_SCHEMA]
        self._messages: list[dict] = []
        self._pending_tool_use_id: str | None = None

    def start(self, context: str) -> None:
        self._messages = [{"role": "user", "content": context}]

    def next_step(self) -> ReasoningStep:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=self._messages,
            tools=self._anthropic_tools,
        )
        self._messages.append({"role": "assistant", "content": response.content})

        tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_use_block is None:
            raise RuntimeError(
                "Modelo de raciocínio não chamou nenhuma ferramenta nem concluiu com "
                "conclude_investigation — resposta inesperada, ciclo não pode continuar."
            )
        self._pending_tool_use_id = tool_use_block.id

        if tool_use_block.name == CONCLUDE_TOOL_NAME:
            raw = dict(tool_use_block.input)
            proposal = ProposalDraft(**raw["proposal"]) if raw.get("proposal") else None
            return ReasoningStep(hypothesis=raw.get("hypothesis", ""), stop_reason=raw.get("stop_reason"), proposal=proposal)

        raw = dict(tool_use_block.input)
        hypothesis = raw.pop("_hypothesis", "")
        return ReasoningStep(hypothesis=hypothesis, tool_call=ToolCall(name=tool_use_block.name, arguments=raw))

    def report_tool_result(self, tool_name: str, result: dict) -> None:
        self._messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": self._pending_tool_use_id, "content": json.dumps(result)}
                ],
            }
        )


@dataclass(frozen=True)
class LoopResult:
    iterations: int
    outcome: str
    proposal_path: Path | None = None


def _now_ms() -> int:
    return int(time.time() * 1000)


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:50]


def draft_change_proposal(proposal: ProposalDraft, report_date: date_type, changes_dir: Path = CHANGES_DIR) -> Path:
    changes_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{report_date.isoformat()}-{_slugify(proposal.title)}.md"
    path = changes_dir / filename
    text = "\n".join(
        [
            f"# Change Proposal — {report_date.isoformat()} — {proposal.title}",
            "",
            "**Status:** pendente",
            "",
            "## Evidência (origem)",
            "- Gerada pelo loop autônomo de aprendizado contínuo (specs/09-aprendizado-continuo.md).",
            proposal.evidence,
            "",
            "## Proposta",
            proposal.proposal_text,
            "",
            "## Classificação de risco da mudança",
            f"- {proposal.risk_classification}",
            "",
            "## Validação proposta",
            proposal.validation_summary,
            "",
            "## Decisão",
            "- Aprovado/rejeitado por: ",
            "- Data: ",
            "- Justificativa: ",
            "",
        ]
    )
    path.write_text(text)
    return path


def _build_context(experiments: list[ExperimentRecord]) -> str:
    lines = [
        f"Experimentos já registrados na memória: {len(experiments)}.",
    ]
    if experiments:
        lines.append("Últimos experimentos (não repita tool+params idênticos):")
        for e in experiments[-5:]:
            lines.append(f"- {e.tool}({e.params}) -> {e.outcome}: {e.result_summary}")
    return "\n".join(lines)


def _conclude(step: ReasoningStep, report_date: date_type, experiments_path: Path, changes_dir: Path, iterations: int) -> LoopResult:
    outcome = step.stop_reason or OUTCOME_NO_FINDING
    changes_file: str | None = None
    if outcome == OUTCOME_PROPOSAL_DRAFTED:
        if step.proposal is None:
            raise ValueError("reasoning client sinalizou proposta pronta sem preencher os dados da proposta")
        path = draft_change_proposal(step.proposal, report_date, changes_dir)
        changes_file = str(path)
    append_experiment(
        ExperimentRecord(ts=_now_ms(), hypothesis=step.hypothesis, tool="(conclusão)", outcome=outcome, changes_file=changes_file),
        experiments_path,
    )
    return LoopResult(iterations=iterations, outcome=outcome, proposal_path=Path(changes_file) if changes_file else None)


def run_agentic_cycle(
    reasoning_client: ReasoningClient,
    events: list[MarketEvent],
    experiments_path: Path = DEFAULT_EXPERIMENTS_PATH,
    changes_dir: Path = CHANGES_DIR,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    report_date: date_type | None = None,
) -> LoopResult:
    report_date = report_date or date_type.today()
    tools = build_tools(events)
    tools_by_name = {t.name: t for t in tools}
    experiments = load_experiments(experiments_path)

    reasoning_client.start(_build_context(experiments))

    for i in range(max_iterations):
        step = reasoning_client.next_step()

        if step.tool_call is None:
            return _conclude(step, report_date, experiments_path, changes_dir, iterations=i + 1)

        if already_tried(experiments, step.tool_call.name, step.tool_call.arguments):
            reasoning_client.report_tool_result(
                step.tool_call.name, {"erro": "já tentado com esses parâmetros exatos — tente algo diferente"}
            )
            continue

        tool = tools_by_name.get(step.tool_call.name)
        if tool is None:
            reasoning_client.report_tool_result(step.tool_call.name, {"erro": f"ferramenta desconhecida: {step.tool_call.name}"})
            continue

        result = tool.run(**step.tool_call.arguments)
        record = ExperimentRecord(
            ts=_now_ms(), hypothesis=step.hypothesis, tool=step.tool_call.name, params=step.tool_call.arguments, result_summary=result
        )
        append_experiment(record, experiments_path)
        experiments.append(record)
        reasoning_client.report_tool_result(step.tool_call.name, result)

    append_experiment(
        ExperimentRecord(ts=_now_ms(), hypothesis="(orçamento de iterações esgotado)", tool="(nenhuma)", outcome=OUTCOME_BUDGET_EXHAUSTED),
        experiments_path,
    )
    return LoopResult(iterations=max_iterations, outcome=OUTCOME_BUDGET_EXHAUSTED, proposal_path=None)
