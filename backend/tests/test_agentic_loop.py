import random
from datetime import date

from tradingbot.ingestion.schema import EventType, MarketEvent
from tradingbot.learning_engine.agentic_loop import (
    FakeReasoningClient,
    ProposalDraft,
    ReasoningStep,
    ToolCall,
    draft_change_proposal,
    run_agentic_cycle,
)
from tradingbot.learning_engine.experiment_log import (
    OUTCOME_BUDGET_EXHAUSTED,
    OUTCOME_NO_FINDING,
    OUTCOME_PROPOSAL_DRAFTED,
    load_experiments,
)


def _closed_kline(symbol, close, ts, high=None, low=None):
    return MarketEvent(
        symbol=symbol,
        event_type=EventType.KLINE,
        exchange_ts=ts,
        local_ts=ts,
        sequence_id=ts,
        payload={
            "open_time": ts - 60_000,
            "close_time": ts,
            "interval": "1m",
            "open": close,
            "high": close if high is None else high,
            "low": close if low is None else low,
            "close": close,
            "volume": 100.0,
            "is_closed": True,
        },
    )


def _synthetic_events(n=900, seed=0):
    rng = random.Random(seed)
    events = []
    price = 100.0
    for i in range(n):
        price += rng.uniform(-0.3, 0.35)
        high = price + abs(rng.uniform(0, 0.2))
        low = price - abs(rng.uniform(0, 0.2))
        events.append(_closed_kline("BTCUSDT", price, (i + 1) * 60_000, high=high, low=low))
    return events


def test_isolation_invariant_agentic_loop_never_imports_execution():
    """spec 09: the loop never has execution credentials — structural check on the real
    import statements of the controller module itself, not just its tools."""
    import ast
    import inspect

    from tradingbot.learning_engine import agentic_loop as loop_module

    tree = ast.parse(inspect.getsource(loop_module))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert not any(m == "tradingbot.execution" or m.startswith("tradingbot.execution.") for m in imported_modules)


def test_run_agentic_cycle_stops_with_no_finding_and_logs_one_experiment(tmp_path):
    experiments_path = tmp_path / "experiments.jsonl"
    changes_dir = tmp_path / "changes"
    client = FakeReasoningClient(steps=[ReasoningStep(hypothesis="nada de novo hoje", stop_reason=OUTCOME_NO_FINDING)])

    result = run_agentic_cycle(
        client, events=[], experiments_path=experiments_path, changes_dir=changes_dir, max_iterations=5
    )

    assert result.outcome == OUTCOME_NO_FINDING
    assert result.iterations == 1
    assert result.proposal_path is None
    assert not changes_dir.exists() or not list(changes_dir.glob("*.md"))

    experiments = load_experiments(experiments_path)
    assert len(experiments) == 1
    assert experiments[0].outcome == OUTCOME_NO_FINDING


def test_run_agentic_cycle_calls_tool_then_concludes_and_logs_both_steps(tmp_path):
    experiments_path = tmp_path / "experiments.jsonl"
    changes_dir = tmp_path / "changes"
    events = _synthetic_events(n=900)
    client = FakeReasoningClient(
        steps=[
            ReasoningStep(
                hypothesis="testar horizon 5min",
                tool_call=ToolCall(
                    name="evaluate_strategy_config",
                    arguments={
                        "horizon_minutes": 5,
                        "entry_percentile": 80.0,
                        "n_splits": 2,
                        "min_trades": 1,
                        "move_threshold_pct": 0.002,
                    },
                ),
            ),
            ReasoningStep(hypothesis="resultado não é forte o suficiente", stop_reason=OUTCOME_NO_FINDING),
        ]
    )

    result = run_agentic_cycle(
        client, events=events, experiments_path=experiments_path, changes_dir=changes_dir, max_iterations=5
    )

    assert result.iterations == 2
    assert result.outcome == OUTCOME_NO_FINDING

    experiments = load_experiments(experiments_path)
    assert len(experiments) == 2
    assert experiments[0].tool == "evaluate_strategy_config"
    assert experiments[1].outcome == OUTCOME_NO_FINDING

    assert client.reported_results[0][0] == "evaluate_strategy_config"
    assert "folds_total" in client.reported_results[0][1]


def test_run_agentic_cycle_drafts_a_pendente_proposal_when_evidence_is_strong(tmp_path):
    experiments_path = tmp_path / "experiments.jsonl"
    changes_dir = tmp_path / "changes"
    proposal = ProposalDraft(
        title="Aumentar horizonte para 45min",
        evidence="PF médio melhora de 0.5 para 0.73 no cache de 90 dias.",
        proposal_text="Mudar horizon_minutes default para 45.",
        validation_summary="folds_won 2/5, mean_pf 0.73, min_pf 0.20.",
        risk_classification="Mudança de arquitetura/target do modelo (requer processo SDD completo)",
    )
    client = FakeReasoningClient(
        steps=[ReasoningStep(hypothesis="achado forte", stop_reason=OUTCOME_PROPOSAL_DRAFTED, proposal=proposal)]
    )

    result = run_agentic_cycle(
        client,
        events=[],
        experiments_path=experiments_path,
        changes_dir=changes_dir,
        max_iterations=5,
        report_date=date(2026, 8, 2),
    )

    assert result.outcome == OUTCOME_PROPOSAL_DRAFTED
    assert result.proposal_path is not None
    assert result.proposal_path.exists()
    text = result.proposal_path.read_text()
    assert "**Status:** pendente" in text
    assert "Aumentar horizonte para 45min" in text
    assert "folds_won 2/5" in text

    experiments = load_experiments(experiments_path)
    assert experiments[0].changes_file == str(result.proposal_path)


def test_run_agentic_cycle_never_marks_a_proposal_approved_or_applied(tmp_path):
    """The loop's only possible output status is 'pendente' — it structurally cannot mark
    its own proposal as approved or applied, since draft_change_proposal always writes the
    same fixed template regardless of what the reasoning model asks for."""
    experiments_path = tmp_path / "experiments.jsonl"
    changes_dir = tmp_path / "changes"
    proposal = ProposalDraft(
        title="Tentativa de auto-aprovação",
        evidence="e",
        proposal_text="p",
        validation_summary="v",
        risk_classification="r",
    )
    client = FakeReasoningClient(
        steps=[ReasoningStep(hypothesis="h", stop_reason=OUTCOME_PROPOSAL_DRAFTED, proposal=proposal)]
    )

    result = run_agentic_cycle(client, events=[], experiments_path=experiments_path, changes_dir=changes_dir, report_date=date(2026, 8, 2))

    text = result.proposal_path.read_text()
    assert "**Status:** pendente" in text
    assert "aprovada" not in text.lower()
    assert "aplicada" not in text.lower()


def test_run_agentic_cycle_dedup_skips_a_repeated_tool_call_without_running_it(tmp_path):
    """If the tool actually ran with these incomplete arguments it would KeyError (missing
    required entry_percentile) — the test passing at all proves dedup short-circuited
    before invoking the tool, exactly as spec 09 requires ('nunca repete um experimento já
    registrado')."""
    from tradingbot.learning_engine.experiment_log import ExperimentRecord, append_experiment

    experiments_path = tmp_path / "experiments.jsonl"
    changes_dir = tmp_path / "changes"
    repeated_args = {"horizon_minutes": 5}  # missing entry_percentile on purpose
    append_experiment(
        ExperimentRecord(ts=1, hypothesis="já tentei isso", tool="evaluate_strategy_config", params=repeated_args),
        experiments_path,
    )

    client = FakeReasoningClient(
        steps=[
            ReasoningStep(hypothesis="repetir", tool_call=ToolCall(name="evaluate_strategy_config", arguments=repeated_args)),
            ReasoningStep(hypothesis="desisto", stop_reason=OUTCOME_NO_FINDING),
        ]
    )

    result = run_agentic_cycle(
        client, events=[], experiments_path=experiments_path, changes_dir=changes_dir, max_iterations=5
    )

    assert result.outcome == OUTCOME_NO_FINDING
    assert "erro" in client.reported_results[0][1]


def test_run_agentic_cycle_stops_at_budget_when_model_never_concludes(tmp_path):
    experiments_path = tmp_path / "experiments.jsonl"
    changes_dir = tmp_path / "changes"
    steps = [
        ReasoningStep(hypothesis=f"tentativa {i}", tool_call=ToolCall(name="list_pending_changes", arguments={"marker": i}))
        for i in range(3)
    ]
    client = FakeReasoningClient(steps=steps)

    result = run_agentic_cycle(
        client, events=[], experiments_path=experiments_path, changes_dir=changes_dir, max_iterations=3
    )

    assert result.outcome == OUTCOME_BUDGET_EXHAUSTED
    assert result.iterations == 3
    assert result.proposal_path is None


def test_draft_change_proposal_writes_pendente_status_and_slugified_filename(tmp_path):
    proposal = ProposalDraft(title="Ajustar X", evidence="Y", proposal_text="Z", validation_summary="W", risk_classification="R")

    path = draft_change_proposal(proposal, date(2026, 8, 2), changes_dir=tmp_path)

    assert path.name == "2026-08-02-ajustar-x.md"
    text = path.read_text()
    assert "**Status:** pendente" in text
    assert "Ajustar X" in text
