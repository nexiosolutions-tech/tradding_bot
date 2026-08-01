"""Shared wiring for anything that needs a live Orchestrator — the standalone worker
script (scripts/run_live.py) and the API service's background task (spec 08) both call
this, so there is exactly one definition of "which strategy is active right now."
"""

from __future__ import annotations

import glob
import os
import time
from pathlib import Path

from dotenv import load_dotenv

from tradingbot.backtesting.strategy import RsiBollingerPlaceholderStrategy
from tradingbot.execution.client import BinanceTestnetClient
from tradingbot.execution.orchestrator import Orchestrator
from tradingbot.model.strategy import ModelStrategy, RegimeFilteredStrategy
from tradingbot.model.versioning import load_metadata, load_model
from tradingbot.persistence import repository
from tradingbot.persistence.db import get_session_factory
from tradingbot.risk.manager import RiskConfig

# backend/src/tradingbot/execution/bootstrap.py -> parents[4] is the repo root, where
# results/, learnings/ and changes/ actually live (not backend/, one level short of it).
_REPO_ROOT = Path(__file__).resolve().parents[4]
MODELS_DIR = _REPO_ROOT / "results" / "models"
PLACEHOLDER_STOP_LOSS_PCT = 0.015

load_dotenv(_REPO_ROOT / "backend" / ".env")


def load_active_strategy():
    """Falls back to the Fase 1 placeholder if no model has been promoted yet — spec 11's
    roadmap explicitly allows shipping the placeholder while Fase 2 iterates."""
    candidates = sorted(glob.glob(str(MODELS_DIR / "*")), reverse=True)
    for version_dir in candidates:
        metadata_path = Path(version_dir) / "metadata.json"
        if not metadata_path.exists():
            continue
        metadata = load_metadata(Path(version_dir))
        model = load_model(Path(version_dir))
        strategy = ModelStrategy(
            model=model,
            entry_threshold=metadata["entry_threshold"],
            exit_threshold=metadata["exit_threshold"],
            stop_loss_pct=metadata["stop_loss_pct"],
        )
        return strategy, metadata["version"]

    return RsiBollingerPlaceholderStrategy(stop_loss_pct=PLACEHOLDER_STOP_LOSS_PCT), "placeholder-fase1"


class MissingCredentialsError(Exception):
    pass


def build_orchestrator(symbol: str | None = None, session_factory=None) -> Orchestrator:
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    if not api_key or not api_secret:
        raise MissingCredentialsError(
            "BINANCE_API_KEY / BINANCE_API_SECRET não configuradas. Gere chaves em "
            "testnet.binance.vision e exporte as duas variáveis de ambiente."
        )

    testnet = os.environ.get("BINANCE_TESTNET", "true").lower() != "false"
    if not testnet:
        raise RuntimeError(
            "BINANCE_TESTNET=false pediria execução em mainnet — bloqueado (CLAUDE.md regra 1/6). "
            "Isso exige confirmação humana explícita fora deste código."
        )

    strategy, strategy_version = load_active_strategy()
    # Long-only limitation (spec 06) applies to whatever is live, model or placeholder —
    # gate entries the same way the backtest/promotion pipeline does (spec 04, 2026-07-31).
    strategy = RegimeFilteredStrategy(inner=strategy)
    exchange = BinanceTestnetClient(api_key, api_secret, testnet=True)
    if session_factory is None:
        session_factory = get_session_factory(os.environ.get("DATABASE_URL"))

    resolved_symbol = symbol or os.environ.get("SYMBOL", "BTCUSDT")
    base_equity = float(os.environ.get("INITIAL_EQUITY", "1000"))
    # A restart (local reload, redeploy, crash) must never silently wipe P&L already
    # booked from real trades — reconstruct from persisted history instead of always
    # starting fresh from the config value (2026-07-31, real gap found in production).
    with session_factory() as session:
        realized_pnl = repository.sum_realized_pnl(session, resolved_symbol)

    return Orchestrator(
        symbol=resolved_symbol,
        strategy=strategy,
        risk_config=RiskConfig(),
        exchange=exchange,
        session_factory=session_factory,
        initial_equity=base_equity + realized_pnl,
        strategy_version=strategy_version,
        now_fn=lambda: int(time.time() * 1000),
    )
