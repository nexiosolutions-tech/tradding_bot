"""Tools the Fase 5 agentic loop (spec 09) can call. Each tool is read-only over historical
market data or the repo's own markdown files — none of this module ever imports
`tradingbot.execution` (spec 09's isolation invariant: the loop never has execution
credentials), and none of it writes anything except through `propose_change` below, which
only ever produces a `changes/*.md` file with **Status: pendente** — never `aprovada` or
`aplicada`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from tradingbot.ingestion.schema import MarketEvent
from tradingbot.model.evaluation import evaluate_config
from tradingbot.model.importance import compute_feature_importance

# backend/src/tradingbot/learning_engine/tools.py -> parents[4] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]
LEARNINGS_DIR = _REPO_ROOT / "learnings"
CHANGES_DIR = _REPO_ROOT / "changes"


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema, passed to the reasoning model as-is
    run: Callable[..., dict]


def _evaluate_strategy_config(events: list[MarketEvent], **kwargs) -> dict:
    result = evaluate_config(
        events,
        horizon_minutes=kwargs["horizon_minutes"],
        entry_percentile=kwargs["entry_percentile"],
        move_threshold_pct=kwargs.get("move_threshold_pct", 0.008),
        move_threshold_atr_multiple=kwargs.get("move_threshold_atr_multiple"),
        n_splits=kwargs.get("n_splits", 5),
        min_trades=kwargs.get("min_trades", 8),
        use_regime_filter=kwargs.get("use_regime_filter", True),
    )
    return {
        "horizon_minutes": result.horizon_minutes,
        "entry_percentile": result.entry_percentile,
        "move_threshold_atr_multiple": result.move_threshold_atr_multiple,
        "use_regime_filter": result.use_regime_filter,
        "label_rate": result.label_rate,
        "folds_won": result.folds_won,
        "folds_total": result.folds_total,
        "mean_profit_factor": result.mean_profit_factor,
        "min_profit_factor": result.min_profit_factor,
        "folds": [
            {
                "fold_index": f.fold_index,
                "profit_factor": f.profit_factor,
                "num_trades": f.num_trades,
                "max_drawdown_pct": f.max_drawdown_pct,
                "won": f.won,
                "reason": f.reason,
            }
            for f in result.folds
        ],
    }


def _analyze_feature_importance(events: list[MarketEvent], **kwargs) -> dict:
    importances = compute_feature_importance(
        events,
        horizon_minutes=kwargs["horizon_minutes"],
        move_threshold_pct=kwargs.get("move_threshold_pct", 0.008),
        move_threshold_atr_multiple=kwargs.get("move_threshold_atr_multiple"),
        n_splits=kwargs.get("n_splits", 5),
    )
    return {
        "features": [
            {"name": i.name, "mean_abs_shap": i.mean_abs_shap, "direction_corr": i.direction_corr}
            for i in importances
        ]
    }


def _list_recent_learnings(events: list[MarketEvent], **kwargs) -> dict:
    limit = kwargs.get("limit", 3)
    files = sorted(LEARNINGS_DIR.glob("*.md"), reverse=True)[:limit]
    return {"learnings": [{"filename": f.name, "content": f.read_text()} for f in files]}


def _list_pending_changes(events: list[MarketEvent], **kwargs) -> dict:
    entries = []
    for f in sorted(CHANGES_DIR.glob("*.md")):
        if f.name == "README.md":
            continue
        text = f.read_text()
        status_match = re.search(r"\*\*Status:\*\*\s*(\S+)", text)
        title_match = re.search(r"^#\s*(.+)$", text, re.MULTILINE)
        entries.append(
            {
                "filename": f.name,
                "status": status_match.group(1) if status_match else "desconhecido",
                "title": title_match.group(1) if title_match else f.name,
            }
        )
    return {"changes": entries}


def build_tools(events: list[MarketEvent]) -> list[Tool]:
    """Closes over the historical events fetched once at the start of a loop cycle — the
    reasoning model chooses configs to test, it never supplies market data itself."""
    return [
        Tool(
            name="evaluate_strategy_config",
            description=(
                "Roda o walk-forward completo (treino, calibração, avaliação por fold) para "
                "uma configuração de horizon_minutes/entry_percentile, igual ao que "
                "train_model.py faz. Retorna profit factor e trades por fold."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "horizon_minutes": {"type": "integer"},
                    "entry_percentile": {"type": "number"},
                    "move_threshold_pct": {
                        "type": "number",
                        "default": 0.008,
                        "description": "Distância fixa do take-profit. Ignorada se move_threshold_atr_multiple for informado.",
                    },
                    "move_threshold_atr_multiple": {
                        "type": "number",
                        "description": (
                            "Se informado, o take-profit vira este múltiplo do atr_pct da barra de "
                            "entrada em vez de um percentual fixo (specs/04, 2026-08-02) — testa se o "
                            "modelo depende de volatilidade em vez de sinal direcional real."
                        ),
                    },
                    "n_splits": {"type": "integer", "default": 5},
                    "min_trades": {"type": "integer", "default": 8},
                    "use_regime_filter": {"type": "boolean", "default": True},
                },
                "required": ["horizon_minutes", "entry_percentile"],
            },
            run=lambda **kw: _evaluate_strategy_config(events, **kw),
        ),
        Tool(
            name="analyze_feature_importance",
            description=(
                "Roda SHAP no fold final do walk-forward para uma dada horizon_minutes, "
                "retornando quais features o modelo realmente usa, ordenadas por importância."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "horizon_minutes": {"type": "integer"},
                    "move_threshold_pct": {"type": "number", "default": 0.008},
                    "move_threshold_atr_multiple": {
                        "type": "number",
                        "description": "Mesmo significado de evaluate_strategy_config — use para checar se isso reduz a dependência de atr_pct.",
                    },
                    "n_splits": {"type": "integer", "default": 5},
                },
                "required": ["horizon_minutes"],
            },
            run=lambda **kw: _analyze_feature_importance(events, **kw),
        ),
        Tool(
            name="list_recent_learnings",
            description="Lê os relatórios diários mais recentes de learnings/.",
            parameters={
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 3}},
                "required": [],
            },
            run=lambda **kw: _list_recent_learnings(events, **kw),
        ),
        Tool(
            name="list_pending_changes",
            description="Lista as entradas existentes em changes/ com seu status atual, para não duplicar uma proposta já feita.",
            parameters={"type": "object", "properties": {}, "required": []},
            run=lambda **kw: _list_pending_changes(events, **kw),
        ),
    ]
