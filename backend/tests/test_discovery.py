from __future__ import annotations

import pytest

from tradingbot.ingestion.binance_rest import SymbolInfo, Ticker24h
from tradingbot.model.evaluation import ConfigEvaluation, FoldSummary
from tradingbot.screening.discovery import (
    CandidateScore,
    candidate_score_from_evaluation,
    compute_correlation,
    filter_candidate_universe,
    rank_candidates,
)


def _symbol(symbol="ETHUSDT", base="ETH", quote="USDT", status="TRADING", spot=True):
    return SymbolInfo(symbol=symbol, base_asset=base, quote_asset=quote, status=status, is_spot_trading_allowed=spot)


def _ticker(symbol="ETHUSDT", quote_volume=50_000_000.0, last_price=3000.0):
    return Ticker24h(symbol=symbol, quote_volume=quote_volume, last_price=last_price)


def test_filter_candidate_universe_keeps_liquid_usdt_spot_symbols():
    symbols = [_symbol()]
    tickers = [_ticker()]
    result = filter_candidate_universe(symbols, tickers, min_quote_volume_24h=1_000_000, min_price=0.01)
    assert result == ["ETHUSDT"]


def test_filter_candidate_universe_excludes_non_trading_status():
    symbols = [_symbol(status="BREAK")]
    tickers = [_ticker()]
    result = filter_candidate_universe(symbols, tickers, min_quote_volume_24h=1_000_000, min_price=0.01)
    assert result == []


def test_filter_candidate_universe_excludes_non_spot():
    symbols = [_symbol(spot=False)]
    tickers = [_ticker()]
    result = filter_candidate_universe(symbols, tickers, min_quote_volume_24h=1_000_000, min_price=0.01)
    assert result == []


def test_filter_candidate_universe_excludes_non_usdt_quote():
    symbols = [_symbol(symbol="ETHBTC", quote="BTC")]
    tickers = [_ticker(symbol="ETHBTC")]
    result = filter_candidate_universe(symbols, tickers, min_quote_volume_24h=1_000_000, min_price=0.01)
    assert result == []


def test_filter_candidate_universe_excludes_leveraged_tokens():
    symbols = [_symbol(symbol="BTCUPUSDT", base="BTCUP")]
    tickers = [_ticker(symbol="BTCUPUSDT")]
    result = filter_candidate_universe(symbols, tickers, min_quote_volume_24h=1_000_000, min_price=0.01)
    assert result == []


def test_filter_candidate_universe_excludes_stablecoins():
    symbols = [_symbol(symbol="USDCUSDT", base="USDC")]
    tickers = [_ticker(symbol="USDCUSDT", quote_volume=500_000_000.0)]
    result = filter_candidate_universe(symbols, tickers, min_quote_volume_24h=1_000_000, min_price=0.01)
    assert result == []


def test_filter_candidate_universe_excludes_below_volume_floor():
    symbols = [_symbol()]
    tickers = [_ticker(quote_volume=100.0)]
    result = filter_candidate_universe(symbols, tickers, min_quote_volume_24h=1_000_000, min_price=0.01)
    assert result == []


def test_filter_candidate_universe_excludes_below_price_floor():
    symbols = [_symbol()]
    tickers = [_ticker(last_price=0.0001)]
    result = filter_candidate_universe(symbols, tickers, min_quote_volume_24h=1_000_000, min_price=0.01)
    assert result == []


def test_filter_candidate_universe_excludes_symbols_missing_ticker_data():
    symbols = [_symbol()]
    result = filter_candidate_universe(symbols, tickers=[], min_quote_volume_24h=1_000_000, min_price=0.01)
    assert result == []


def test_compute_correlation_perfectly_correlated_series():
    prices = [100.0, 101.0, 102.0, 101.0, 103.0]
    assert compute_correlation(prices, prices) == pytest.approx(1.0)


def test_compute_correlation_inversely_correlated_series():
    candidate = [100.0, 101.0, 102.0, 101.0]
    btc = [100.0, 99.0, 98.0, 99.0]
    correlation = compute_correlation(candidate, btc)
    assert correlation is not None
    assert correlation < -0.9


def test_compute_correlation_none_for_mismatched_length():
    assert compute_correlation([1.0, 2.0, 3.0], [1.0, 2.0]) is None


def test_compute_correlation_none_for_too_short_series():
    assert compute_correlation([1.0, 2.0], [1.0, 2.0]) is None


def test_compute_correlation_none_for_constant_series():
    assert compute_correlation([100.0, 100.0, 100.0, 100.0], [1.0, 2.0, 3.0, 4.0]) is None


def _evaluation(folds_won_flags, profit_factors):
    folds = tuple(
        FoldSummary(fold_index=i, profit_factor=pf, num_trades=20, max_drawdown_pct=0.05, won=won, reason="")
        for i, (won, pf) in enumerate(zip(folds_won_flags, profit_factors))
    )
    return ConfigEvaluation(
        horizon_minutes=45,
        entry_percentile=99.0,
        move_threshold_pct=0.008,
        move_threshold_atr_multiple=None,
        use_regime_filter=False,
        label_rate=0.04,
        folds=folds,
    )


def test_candidate_score_from_evaluation_extracts_fold_metrics():
    evaluation = _evaluation([True, True, False, False, False], [1.5, 1.2, 0.8, 0.5, 0.3])
    score = candidate_score_from_evaluation("ETHUSDT", 50_000_000.0, 0.6, evaluation)

    assert score.symbol == "ETHUSDT"
    assert score.folds_won == 2
    assert score.folds_total == 5
    assert score.min_profit_factor == 0.3


def test_rank_candidates_orders_by_folds_won_then_mean_pf():
    fewer_folds_higher_pf = CandidateScore(
        "A", 1.0, 0.5, folds_won=1, folds_total=5, mean_profit_factor=2.0, min_profit_factor=0.1, label_rate=0.04
    )
    most_folds_won = CandidateScore(
        "B", 1.0, 0.5, folds_won=3, folds_total=5, mean_profit_factor=0.5, min_profit_factor=0.1, label_rate=0.04
    )
    fewer_folds_lower_pf = CandidateScore(
        "C", 1.0, 0.5, folds_won=1, folds_total=5, mean_profit_factor=1.5, min_profit_factor=0.1, label_rate=0.04
    )

    ranked = rank_candidates([fewer_folds_higher_pf, most_folds_won, fewer_folds_lower_pf])

    # B wins on folds_won (the primary criterion, same as the real promotion gate); among
    # the tied A/C, higher mean_profit_factor (the tiebreak) comes first.
    assert [c.symbol for c in ranked] == ["B", "A", "C"]
