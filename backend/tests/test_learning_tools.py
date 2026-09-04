import random

from tradingbot.ingestion.schema import EventType, MarketEvent
from tradingbot.learning_engine import tools as tools_module
from tradingbot.learning_engine.tools import build_tools


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


def test_isolation_invariant_tools_module_never_imports_execution():
    """spec 09: the loop never has execution credentials — structural check on the actual
    import statements (not a substring search, which would false-positive on this test's
    own docstrings), so it can't be satisfied by just not mentioning it in a comment."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(tools_module))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert not any(m == "tradingbot.execution" or m.startswith("tradingbot.execution.") for m in imported_modules)


def test_build_tools_returns_the_four_expected_tools():
    tools = build_tools(events=[])
    names = {t.name for t in tools}
    assert names == {
        "evaluate_strategy_config",
        "analyze_feature_importance",
        "list_recent_learnings",
        "list_pending_changes",
    }


def test_evaluate_strategy_config_tool_runs_against_closed_over_events():
    events = _synthetic_events(n=900)
    tools = {t.name: t for t in build_tools(events)}

    result = tools["evaluate_strategy_config"].run(horizon_minutes=5, entry_percentile=80.0, move_threshold_pct=0.002, n_splits=2, min_trades=1)

    assert result["horizon_minutes"] == 5
    assert 1 <= result["folds_total"] <= 2
    assert isinstance(result["folds"], list)


def test_evaluate_strategy_config_tool_exposes_pnl_aggregates_without_equity_curve():
    """total_pnl/gross_profit/gross_loss precisam chegar em result_summary (gap real,
    apontado como já resolvido no commit 2d0dc45 quando não estava) -- mas equity_curve
    (por barra, ~13k pontos/fold) fica fora de propósito: result_summary vai direto para
    o prompt do modelo de raciocínio a cada chamada e para o contexto dos próximos
    ciclos (agentic_loop.py), não só para o disco -- ver changes/2026-09-04."""
    events = _synthetic_events(n=900)
    tools = {t.name: t for t in build_tools(events)}

    result = tools["evaluate_strategy_config"].run(
        horizon_minutes=5, entry_percentile=80.0, move_threshold_pct=0.002, n_splits=2, min_trades=1
    )

    assert "total_pnl" in result
    assert "aggregate_profit_factor" in result
    assert isinstance(result["total_pnl"], (int, float))

    assert "equity_curve" not in result
    for fold in result["folds"]:
        assert "total_pnl" in fold
        assert "gross_profit" in fold
        assert "gross_loss" in fold
        assert "equity_curve" not in fold


def test_analyze_feature_importance_tool_returns_sorted_features():
    events = _synthetic_events(n=900)
    tools = {t.name: t for t in build_tools(events)}

    result = tools["analyze_feature_importance"].run(horizon_minutes=5, move_threshold_pct=0.002, n_splits=2)

    values = [f["mean_abs_shap"] for f in result["features"]]
    assert values == sorted(values, reverse=True)


def test_list_recent_learnings_reads_files_from_learnings_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tools_module, "LEARNINGS_DIR", tmp_path)
    (tmp_path / "2026-08-01.md").write_text("# Learnings — 2026-08-01\nconteudo")

    tools = {t.name: t for t in build_tools(events=[])}
    result = tools["list_recent_learnings"].run(limit=3)

    assert len(result["learnings"]) == 1
    assert result["learnings"][0]["filename"] == "2026-08-01.md"
    assert "conteudo" in result["learnings"][0]["content"]


def test_list_pending_changes_parses_status_and_title(tmp_path, monkeypatch):
    monkeypatch.setattr(tools_module, "CHANGES_DIR", tmp_path)
    (tmp_path / "README.md").write_text("# ignorado")
    (tmp_path / "2026-08-01-exemplo.md").write_text(
        "# Change Proposal — 2026-08-01 — Exemplo de achado\n\n**Status:** pendente\n"
    )

    tools = {t.name: t for t in build_tools(events=[])}
    result = tools["list_pending_changes"].run()

    assert len(result["changes"]) == 1
    entry = result["changes"][0]
    assert entry["status"] == "pendente"
    assert "Exemplo de achado" in entry["title"]
