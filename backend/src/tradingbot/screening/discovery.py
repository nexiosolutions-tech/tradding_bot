"""Coin screening — spec 12. Pure filtering/correlation/ranking logic; the orchestration
(fetching klines, calling evaluate_config per candidate) lives in
scripts/run_coin_discovery.py, so this module stays testable without network access —
same split model/evaluation.py already uses.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from tradingbot.ingestion.binance_rest import SymbolInfo, Ticker24h
from tradingbot.model.evaluation import ConfigEvaluation

# Leveraged tokens (3x/5x long-short pairs) decay structurally by design — not comparable
# to the spot, no-margin architecture this system already validates (spec 06).
LEVERAGED_TOKEN_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")

# 2026-08-15: found empirically running the script against real Binance data — USDCUSDT
# passed every other filter and ranked #1 by volume (stablecoins trade enormous nominal
# volume against USDT), wasting a full walk-forward backtest on a pair with ~zero
# volatility by design. No clean API flag for "is a stablecoin", so this is a curated
# denylist of the major ones on Binance, same pattern as LEVERAGED_TOKEN_SUFFIXES.
STABLECOIN_BASE_ASSETS = {"USDC", "FDUSD", "TUSD", "DAI", "USDP", "BUSD", "EUR", "GBP", "AEUR"}


def _is_leveraged_token(base_asset: str) -> bool:
    return base_asset.endswith(LEVERAGED_TOKEN_SUFFIXES)


def _is_stablecoin(base_asset: str) -> bool:
    return base_asset in STABLECOIN_BASE_ASSETS


def filter_candidate_universe(
    symbols: list[SymbolInfo],
    tickers: list[Ticker24h],
    min_quote_volume_24h: float,
    min_price: float,
    quote_asset: str = "USDT",
) -> list[str]:
    """Deterministic universe filter, not a scoring step — spec 12. Returns symbol names
    passing status/quote-asset/leveraged-token/volume/price checks."""
    tickers_by_symbol = {t.symbol: t for t in tickers}
    candidates = []
    for s in symbols:
        if s.status != "TRADING" or not s.is_spot_trading_allowed:
            continue
        if s.quote_asset != quote_asset:
            continue
        if _is_leveraged_token(s.base_asset):
            continue
        if _is_stablecoin(s.base_asset):
            continue
        ticker = tickers_by_symbol.get(s.symbol)
        if ticker is None:
            continue
        if ticker.quote_volume < min_quote_volume_24h:
            continue
        if ticker.last_price < min_price:
            continue
        candidates.append(s.symbol)
    return candidates


def compute_correlation(candidate_closes: list[float], btc_closes: list[float]) -> float | None:
    """Pearson correlation of candle-to-candle returns — spec 12's context for
    superexposure-to-BTC risk, not an automatic exclusion filter. None when either series
    is too short or constant to define a correlation (e.g. a newly-listed coin)."""
    if len(candidate_closes) != len(btc_closes) or len(candidate_closes) < 3:
        return None
    candidate = np.asarray(candidate_closes, dtype=float)
    btc = np.asarray(btc_closes, dtype=float)
    candidate_returns = np.diff(candidate) / candidate[:-1]
    btc_returns = np.diff(btc) / btc[:-1]
    if np.std(candidate_returns) == 0 or np.std(btc_returns) == 0:
        return None
    return float(np.corrcoef(candidate_returns, btc_returns)[0, 1])


@dataclass(frozen=True)
class CandidateScore:
    symbol: str
    quote_volume_24h: float
    btc_correlation: float | None
    folds_won: int
    folds_total: int
    mean_profit_factor: float
    min_profit_factor: float
    label_rate: float


def candidate_score_from_evaluation(
    symbol: str,
    quote_volume_24h: float,
    btc_correlation: float | None,
    evaluation: ConfigEvaluation,
) -> CandidateScore:
    return CandidateScore(
        symbol=symbol,
        quote_volume_24h=quote_volume_24h,
        btc_correlation=btc_correlation,
        folds_won=evaluation.folds_won,
        folds_total=evaluation.folds_total,
        mean_profit_factor=evaluation.mean_profit_factor,
        min_profit_factor=evaluation.min_profit_factor,
        label_rate=evaluation.label_rate,
    )


def rank_candidates(scores: list[CandidateScore]) -> list[CandidateScore]:
    """folds_won first — the same criterion as the real promotion gate (spec 07) — then
    mean_profit_factor as tiebreak. No new ML scoring model: reuses the exact evaluation
    already validated for BTCUSDT (spec 12)."""
    return sorted(scores, key=lambda c: (c.folds_won, c.mean_profit_factor), reverse=True)
