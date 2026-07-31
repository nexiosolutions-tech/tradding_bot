"""Dashboard API — spec 08. Serves backtest/model artifacts for the Performance/Modelo
views and, when Binance credentials are configured, runs the live Orchestrator in the
background so the Live view reflects a real (testnet) engine. Play/Pause/acknowledge
always go through the Orchestrator's own methods — this module never touches the database
or the exchange directly on the engine's behalf.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from tradingbot.execution.bootstrap import MissingCredentialsError, build_orchestrator
from tradingbot.ingestion.binance_ws import BinanceKlineStream
from tradingbot.persistence.db import get_session_factory
from tradingbot.persistence.repository import recent_engine_events, trades_in_range

RESULTS_DIR = Path(__file__).resolve().parents[4] / "results"
MODELS_DIR = RESULTS_DIR / "models"
LEARNINGS_DIR = Path(__file__).resolve().parents[4] / "learnings"
CHANGES_DIR = Path(__file__).resolve().parents[4] / "changes"


class CommandBody(BaseModel):
    by: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.session_factory = get_session_factory(os.environ.get("DATABASE_URL"))
    app.state.orchestrator = None
    app.state.engine_error = None
    app.state.ingestion_task = None

    try:
        orchestrator = build_orchestrator(session_factory=app.state.session_factory)
    except (MissingCredentialsError, RuntimeError) as exc:
        app.state.engine_error = str(exc)
    else:
        app.state.orchestrator = orchestrator
        stream = BinanceKlineStream(symbols=[orchestrator.symbol], interval="1m", testnet=True)

        async def _consume():
            async for event in stream:
                await orchestrator.on_event(event)

        app.state.ingestion_task = asyncio.create_task(_consume())

    yield

    if app.state.ingestion_task is not None:
        app.state.ingestion_task.cancel()


app = FastAPI(title="Trading Bot API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # `or` (not dict.get's default=) so an empty-but-set DASHBOARD_ORIGIN — e.g. left
    # blank in .env — falls back too, instead of producing a single empty allowed origin.
    allow_origins=(os.environ.get("DASHBOARD_ORIGIN") or "http://localhost:5173,http://127.0.0.1:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_orchestrator():
    if app.state.orchestrator is None:
        raise HTTPException(status_code=503, detail=app.state.engine_error or "engine não configurado")
    return app.state.orchestrator


def _verify_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Optional by design: if DASHBOARD_API_KEY isn't set (e.g. right after this deploy,
    before the operator configures it), commands stay open — same behavior as before this
    check existed. Once set, it's enforced on every command endpoint."""
    expected = os.environ.get("DASHBOARD_API_KEY")
    if not expected:
        return
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="chave de API ausente ou inválida")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/backtests")
def list_backtests():
    if not RESULTS_DIR.exists():
        return []
    runs = []
    for run_dir in sorted((p for p in RESULTS_DIR.iterdir() if p.is_dir() and p.name != "models"), reverse=True):
        report_path = run_dir / "report.json"
        if not report_path.exists():
            continue
        report = json.loads(report_path.read_text())
        runs.append(
            {
                "run_name": run_dir.name,
                "metrics": report["metrics"],
                "final_equity": report["final_equity"],
            }
        )
    return runs


@app.get("/api/backtests/{run_name}")
def get_backtest(run_name: str):
    report_path = (RESULTS_DIR / run_name / "report.json").resolve()
    if not report_path.is_relative_to(RESULTS_DIR.resolve()) or not report_path.exists():
        raise HTTPException(status_code=404, detail="backtest não encontrado")
    return json.loads(report_path.read_text())


@app.get("/api/models")
def list_models():
    if not MODELS_DIR.exists():
        return []
    versions = []
    for version_dir in sorted(MODELS_DIR.iterdir(), reverse=True):
        metadata_path = version_dir / "metadata.json"
        if metadata_path.exists():
            versions.append(json.loads(metadata_path.read_text()))
    return versions


@app.get("/api/models/{version}")
def get_model(version: str):
    metadata_path = (MODELS_DIR / version / "metadata.json").resolve()
    if not metadata_path.is_relative_to(MODELS_DIR.resolve()) or not metadata_path.exists():
        raise HTTPException(status_code=404, detail="versão de modelo não encontrada")
    return json.loads(metadata_path.read_text())


def _list_markdown_docs(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    return sorted((p.name for p in directory.glob("*.md") if p.name != "README.md"), reverse=True)


def _extract_status(content: str) -> str | None:
    for line in content.splitlines():
        if line.strip().lower().startswith("**status:**"):
            return line.split(":", 1)[1].strip().strip("*").strip()
    return None


@app.get("/api/learnings")
def list_learnings():
    return _list_markdown_docs(LEARNINGS_DIR)


@app.get("/api/learnings/{filename}")
def get_learning(filename: str):
    path = (LEARNINGS_DIR / filename).resolve()
    if not path.is_relative_to(LEARNINGS_DIR.resolve()) or not path.exists() or path.suffix != ".md":
        raise HTTPException(status_code=404, detail="relatório não encontrado")
    return {"filename": filename, "content": path.read_text()}


@app.get("/api/changes")
def list_changes():
    names = _list_markdown_docs(CHANGES_DIR)
    result = []
    for name in names:
        content = (CHANGES_DIR / name).read_text()
        result.append({"filename": name, "status": _extract_status(content)})
    return result


@app.get("/api/changes/{filename}")
def get_change(filename: str):
    path = (CHANGES_DIR / filename).resolve()
    if not path.is_relative_to(CHANGES_DIR.resolve()) or not path.exists() or path.suffix != ".md":
        raise HTTPException(status_code=404, detail="proposta não encontrada")
    content = path.read_text()
    return {"filename": filename, "content": content, "status": _extract_status(content)}


def _engine_state_payload() -> dict:
    orchestrator = app.state.orchestrator
    if orchestrator is None:
        return {"configured": False, "error": app.state.engine_error}

    position = orchestrator.open_position
    return {
        "configured": True,
        "symbol": orchestrator.symbol,
        "state": orchestrator.state.value,
        "equity": orchestrator.equity,
        "strategy_version": orchestrator.strategy_version,
        "started_at": orchestrator.started_at,
        "position": None
        if position is None
        else {
            "entry_price": position.entry_price,
            "size": position.size,
            "stop_loss_price": position.stop_loss_price,
            "entry_ts": position.entry_ts,
        },
        "activity": [
            {"ts": a.ts, "level": a.level, "message": a.message} for a in orchestrator.recent_activity(50)
        ],
    }


@app.get("/api/engine/state")
def engine_state():
    return _engine_state_payload()


@app.get("/api/engine/activity")
def engine_activity(limit: int = 50):
    orchestrator = _require_orchestrator()
    return [{"ts": a.ts, "level": a.level, "message": a.message} for a in orchestrator.recent_activity(limit)]


@app.get("/api/engine/events")
def engine_events(limit: int = 50):
    with app.state.session_factory() as session:
        events = recent_engine_events(session, limit=limit)
    return [
        {
            "ts": e.ts,
            "from_state": e.from_state,
            "to_state": e.to_state,
            "reason": e.reason,
            "triggered_by_human": e.triggered_by_human,
        }
        for e in events
    ]


@app.get("/api/trades")
def list_trades(start_ts: int = 0, end_ts: int = 2**62):
    with app.state.session_factory() as session:
        trades = trades_in_range(session, start_ts, end_ts)
    return [
        {
            "symbol": t.symbol,
            "entry_ts": t.entry_ts,
            "exit_ts": t.exit_ts,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "size": t.size,
            "pnl": t.pnl,
            "fees_paid": t.fees_paid,
            "exit_reason": t.exit_reason,
            "strategy_version": t.strategy_version,
        }
        for t in trades
    ]


@app.post("/api/engine/pause", dependencies=[Depends(_verify_api_key)])
def pause_engine(body: CommandBody):
    orchestrator = _require_orchestrator()
    orchestrator.pause(by=body.by)
    return {"state": orchestrator.state.value}


@app.post("/api/engine/resume", dependencies=[Depends(_verify_api_key)])
def resume_engine(body: CommandBody):
    orchestrator = _require_orchestrator()
    try:
        orchestrator.resume(by=body.by)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"state": orchestrator.state.value}


@app.post("/api/engine/acknowledge_circuit_breaker", dependencies=[Depends(_verify_api_key)])
def acknowledge_circuit_breaker(body: CommandBody):
    orchestrator = _require_orchestrator()
    try:
        orchestrator.acknowledge_circuit_breaker(by=body.by)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"state": orchestrator.state.value}


@app.websocket("/ws/engine")
async def engine_ws(websocket: WebSocket, key: str | None = Query(default=None)):
    # Browsers can't set custom headers on a native WebSocket handshake, so the key
    # travels as a query param here instead of X-API-Key.
    expected = os.environ.get("DASHBOARD_API_KEY")
    if expected and key != expected:
        await websocket.close(code=1008)  # policy violation
        return
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(_engine_state_payload())
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
