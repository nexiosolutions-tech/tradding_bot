import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/api-test.db")

    import tradingbot.api.app as api_app

    monkeypatch.setattr(api_app, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(api_app, "MODELS_DIR", tmp_path / "results" / "models")
    monkeypatch.setattr(api_app, "LEARNINGS_DIR", tmp_path / "learnings")
    monkeypatch.setattr(api_app, "CHANGES_DIR", tmp_path / "changes")

    with TestClient(api_app.app) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_engine_state_reports_unconfigured_without_credentials(client):
    response = client.get("/api/engine/state")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert "BINANCE_API_KEY" in body["error"]


def test_engine_commands_return_503_when_unconfigured(client):
    response = client.post("/api/engine/pause", json={"by": "brian"})
    assert response.status_code == 503


def test_engine_activity_returns_503_when_unconfigured(client):
    response = client.get("/api/engine/activity")
    assert response.status_code == 503


def test_engine_state_includes_empty_activity_key_when_unconfigured(client):
    response = client.get("/api/engine/state")
    assert response.json().get("activity") is None


def test_list_backtests_empty_when_no_results_dir(client):
    response = client.get("/api/backtests")
    assert response.status_code == 200
    assert response.json() == []


def test_list_backtests_reads_report_json_files(client, tmp_path):
    run_dir = tmp_path / "results" / "BTCUSDT_1m_7d"
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text(
        json.dumps({"metrics": {"num_trades": 3, "win_rate": 0.5}, "final_equity": 9800.0})
    )

    response = client.get("/api/backtests")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["run_name"] == "BTCUSDT_1m_7d"
    assert body[0]["final_equity"] == 9800.0


def test_get_backtest_detail_404_when_missing(client):
    response = client.get("/api/backtests/does-not-exist")
    assert response.status_code == 404


def test_list_models_reads_metadata_json_files(client, tmp_path):
    version_dir = tmp_path / "results" / "models" / "BTCUSDT_1m_123"
    version_dir.mkdir(parents=True)
    (version_dir / "metadata.json").write_text(json.dumps({"version": "BTCUSDT_1m_123", "entry_threshold": 0.7}))

    response = client.get("/api/models")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["version"] == "BTCUSDT_1m_123"


def test_trades_and_events_endpoints_work_against_empty_db(client):
    assert client.get("/api/trades").json() == []
    assert client.get("/api/engine/events").json() == []


def test_list_learnings_reads_markdown_files_excluding_readme(client, tmp_path):
    learnings_dir = tmp_path / "learnings"
    learnings_dir.mkdir(parents=True)
    (learnings_dir / "README.md").write_text("template")
    (learnings_dir / "2026-07-30.md").write_text("# Learnings\n\nTexto")

    response = client.get("/api/learnings")
    assert response.json() == ["2026-07-30.md"]

    detail = client.get("/api/learnings/2026-07-30.md")
    assert detail.status_code == 200
    assert "Texto" in detail.json()["content"]


def test_get_learning_rejects_path_traversal(client, tmp_path):
    (tmp_path / "secret.md").write_text("não deveria ser lido")
    response = client.get("/api/learnings/..%2Fsecret.md")
    assert response.status_code == 404


def test_engine_commands_stay_open_without_dashboard_api_key_configured(client):
    # No DASHBOARD_API_KEY set -> auth is a no-op, same behavior as before it existed.
    # Still 503 (engine unconfigured in this fixture), not 401 -> auth didn't block it.
    response = client.post("/api/engine/pause", json={"by": "brian"})
    assert response.status_code == 503


def test_engine_commands_require_api_key_once_configured(client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "s3cr3t")

    no_header = client.post("/api/engine/pause", json={"by": "brian"})
    assert no_header.status_code == 401

    wrong_header = client.post("/api/engine/pause", json={"by": "brian"}, headers={"X-API-Key": "nope"})
    assert wrong_header.status_code == 401

    correct_header = client.post("/api/engine/pause", json={"by": "brian"}, headers={"X-API-Key": "s3cr3t"})
    assert correct_header.status_code == 503  # passes auth; still 503 because engine is unconfigured


def test_resume_and_acknowledge_also_require_api_key_once_configured(client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "s3cr3t")

    assert client.post("/api/engine/resume", json={"by": "brian"}).status_code == 401
    assert client.post("/api/engine/acknowledge_circuit_breaker", json={"by": "brian"}).status_code == 401


def test_ws_engine_rejects_missing_or_wrong_key_once_configured(client, monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.setenv("DASHBOARD_API_KEY", "s3cr3t")

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/engine"):
            pass

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/engine?key=wrong"):
            pass

    with client.websocket_connect("/ws/engine?key=s3cr3t") as ws:
        ws.receive_json()  # connects and streams state once the key matches


def test_list_changes_extracts_status_field(client, tmp_path):
    changes_dir = tmp_path / "changes"
    changes_dir.mkdir(parents=True)
    (changes_dir / "2026-07-30-ajuste.md").write_text("# Change Proposal\n\n**Status:** pendente\n")

    response = client.get("/api/changes")
    body = response.json()
    assert body == [{"filename": "2026-07-30-ajuste.md", "status": "pendente"}]

    detail = client.get("/api/changes/2026-07-30-ajuste.md")
    assert detail.json()["status"] == "pendente"
