from tradingbot.learning_engine.experiment_log import (
    DOMAIN_ACOES,
    DOMAIN_BOT,
    OUTCOME_NO_FINDING,
    OUTCOME_PROPOSAL_DRAFTED,
    ExperimentRecord,
    already_tried,
    append_experiment,
    contar_experimentos_por_dominio,
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


def test_domain_defaults_to_bot_para_linha_antiga_sem_o_campo(tmp_path):
    """Linha gravada antes do campo `domain` existir (spec 14, Seção 9.2) precisa
    continuar carregando sem erro, com domínio "bot" — o comportamento de antes desta
    mudança era implicitamente só o do bot."""
    path = tmp_path / "experiments.jsonl"
    path.write_text('{"ts": 1, "hypothesis": "h", "tool": "t", "params": {}, '
                     '"result_summary": {}, "outcome": "sem_achado", "changes_file": null}\n')
    loaded = load_experiments(path)
    assert loaded[0].domain == DOMAIN_BOT


def test_already_tried_e_isolado_por_dominio():
    """Mesmo tool/params em domínios diferentes não é a mesma tentativa — um match
    coincidente entre bot e ações nunca deve suprimir uma tentativa genuinamente nova no
    outro domínio (spec 14, Seção 9.2)."""
    experiments = [
        ExperimentRecord(ts=1, hypothesis="h", tool="mesmo_nome", params={"x": 1}, domain=DOMAIN_BOT),
    ]
    assert already_tried(experiments, "mesmo_nome", {"x": 1}, domain=DOMAIN_BOT) is True
    assert already_tried(experiments, "mesmo_nome", {"x": 1}, domain=DOMAIN_ACOES) is False


def test_contar_experimentos_por_dominio_nao_mistura_os_dois():
    """N do DSR (spec 14, Seção 9.2/10 critério 4) tem que ser específico do domínio —
    tentativas do bot não podem inflar, nem ser infladas por, o viés de seleção do
    módulo de ações."""
    experiments = [
        ExperimentRecord(ts=1, hypothesis="h1", tool="t", domain=DOMAIN_BOT),
        ExperimentRecord(ts=2, hypothesis="h2", tool="t", domain=DOMAIN_BOT),
        ExperimentRecord(ts=3, hypothesis="h3", tool="t", domain=DOMAIN_ACOES),
    ]
    assert contar_experimentos_por_dominio(experiments, DOMAIN_BOT) == 2
    assert contar_experimentos_por_dominio(experiments, DOMAIN_ACOES) == 1


def test_experiment_record_carries_changes_file_when_proposal_drafted():
    record = ExperimentRecord(
        ts=1,
        hypothesis="h",
        tool="evaluate_strategy_config",
        outcome=OUTCOME_PROPOSAL_DRAFTED,
        changes_file="changes/2026-08-02-exemplo.md",
    )
    assert record.changes_file == "changes/2026-08-02-exemplo.md"
