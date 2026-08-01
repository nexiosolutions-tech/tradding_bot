from tradingbot.learning_engine.experiment_log import (
    OUTCOME_NO_FINDING,
    OUTCOME_PROPOSAL_DRAFTED,
    ExperimentRecord,
    already_tried,
    append_experiment,
    load_experiments,
)


def test_append_and_load_round_trip(tmp_path):
    path = tmp_path / "experiments.jsonl"
    record = ExperimentRecord(
        ts=1000,
        hypothesis="horizon maior melhora PF",
        tool="evaluate_strategy_config",
        params={"horizon_minutes": 45, "entry_percentile": 99.0},
        result_summary={"mean_pf": 0.73, "folds_won": 2},
        outcome=OUTCOME_NO_FINDING,
    )
    append_experiment(record, path)

    loaded = load_experiments(path)
    assert loaded == [record]


def test_load_experiments_from_missing_file_returns_empty_list(tmp_path):
    assert load_experiments(tmp_path / "does-not-exist.jsonl") == []


def test_append_is_additive_across_multiple_calls(tmp_path):
    path = tmp_path / "experiments.jsonl"
    append_experiment(ExperimentRecord(ts=1, hypothesis="a", tool="t1", params={}), path)
    append_experiment(ExperimentRecord(ts=2, hypothesis="b", tool="t2", params={}), path)

    loaded = load_experiments(path)
    assert [r.hypothesis for r in loaded] == ["a", "b"]


def test_already_tried_matches_on_exact_tool_and_params():
    experiments = [
        ExperimentRecord(ts=1, hypothesis="h", tool="evaluate_strategy_config", params={"horizon_minutes": 45}),
    ]
    assert already_tried(experiments, "evaluate_strategy_config", {"horizon_minutes": 45}) is True
    assert already_tried(experiments, "evaluate_strategy_config", {"horizon_minutes": 30}) is False
    assert already_tried(experiments, "analyze_feature_importance", {"horizon_minutes": 45}) is False


def test_experiment_record_carries_changes_file_when_proposal_drafted():
    record = ExperimentRecord(
        ts=1,
        hypothesis="h",
        tool="evaluate_strategy_config",
        outcome=OUTCOME_PROPOSAL_DRAFTED,
        changes_file="changes/2026-08-02-exemplo.md",
    )
    assert record.changes_file == "changes/2026-08-02-exemplo.md"
