"""Coin screening — spec 12. Research tool, read-only: filters the tradable USDT universe
by liquidity/price, ranks the most liquid candidates against the exact walk-forward
backtest already validated for BTCUSDT (specs/11, 9ª/10ª rodadas), and reports correlation
to BTC for context. Never places orders, never touches risk/execution, never promotes a
symbol automatically — a good result here is input to a human decision, not an action.

Usage:
    python scripts/run_coin_discovery.py --days 90 --top-by-volume 10
"""

from __future__ import annotations

import argparse
import time

from tradingbot.ingestion.binance_rest import BinanceRestClient
from tradingbot.model.evaluation import evaluate_config
from tradingbot.screening.discovery import (
    candidate_score_from_evaluation,
    compute_correlation,
    filter_candidate_universe,
    rank_candidates,
)

# Same reference config validated for BTCUSDT — specs/11, 9ª/10ª rodadas. Not re-tuned per
# candidate: the point is testing whether the same, already-validated setup transfers, not
# fitting a new config per coin (that would be a much larger, unvalidated search).
HORIZON_MINUTES = 45
ENTRY_PERCENTILE = 99.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--min-quote-volume-24h", type=float, default=10_000_000.0)
    parser.add_argument("--min-price", type=float, default=0.01)
    parser.add_argument("--top-by-volume", type=int, default=10, help="candidates backtested, most liquid first")
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--min-trades", type=int, default=15)
    args = parser.parse_args()

    client = BinanceRestClient()

    print("Buscando universo negociável (exchangeInfo + ticker 24h)...")
    symbols = client.fetch_exchange_info()
    tickers = client.fetch_24h_tickers()
    candidates = filter_candidate_universe(
        symbols, tickers, min_quote_volume_24h=args.min_quote_volume_24h, min_price=args.min_price
    )
    candidates = [c for c in candidates if c != "BTCUSDT"]

    tickers_by_symbol = {t.symbol: t for t in tickers}
    candidates.sort(key=lambda s: tickers_by_symbol[s].quote_volume, reverse=True)
    candidates = candidates[: args.top_by_volume]
    print(f"{len(candidates)} candidatos após filtro de universo (top {args.top_by_volume} por volume): {candidates}")

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - args.days * 24 * 60 * 60 * 1000

    print("Buscando klines de BTCUSDT (referência de correlação e baseline do ranking)...")
    btc_events = client.fetch_klines("BTCUSDT", "1m", start_ms, end_ms)
    btc_closes = [float(e.payload["close"]) for e in btc_events]
    btc_evaluation = evaluate_config(
        btc_events,
        horizon_minutes=HORIZON_MINUTES,
        entry_percentile=ENTRY_PERCENTILE,
        n_splits=args.n_splits,
        min_trades=args.min_trades,
        use_regime_filter=False,
    )
    btc_volume = tickers_by_symbol["BTCUSDT"].quote_volume if "BTCUSDT" in tickers_by_symbol else 0.0
    scores = [candidate_score_from_evaluation("BTCUSDT", btc_volume, 1.0, btc_evaluation)]

    for symbol in candidates:
        print(f"Buscando klines e rodando backtest para {symbol}...")
        events = client.fetch_klines(symbol, "1m", start_ms, end_ms)
        if not events:
            print(f"  sem dado retornado para {symbol}, pulando.")
            continue
        closes = [float(e.payload["close"]) for e in events]
        correlation = compute_correlation(closes, btc_closes)
        evaluation = evaluate_config(
            events,
            horizon_minutes=HORIZON_MINUTES,
            entry_percentile=ENTRY_PERCENTILE,
            n_splits=args.n_splits,
            min_trades=args.min_trades,
            use_regime_filter=False,
        )
        scores.append(
            candidate_score_from_evaluation(symbol, tickers_by_symbol[symbol].quote_volume, correlation, evaluation)
        )

    ranked = rank_candidates(scores)
    print("\n=== Ranking (folds_won desc, mean_pf desc) ===")
    print(f"{'symbol':<12} {'vol24h':>15} {'corr_btc':>9} {'folds_won':>10} {'mean_pf':>8} {'min_pf':>8} {'label_rate':>10}")
    for c in ranked:
        corr_str = f"{c.btc_correlation:.2f}" if c.btc_correlation is not None else "n/a"
        print(
            f"{c.symbol:<12} {c.quote_volume_24h:>15,.0f} {corr_str:>9} "
            f"{c.folds_won:>3}/{c.folds_total:<6} {c.mean_profit_factor:>8.2f} {c.min_profit_factor:>8.2f} {c.label_rate:>9.1%}"
        )


if __name__ == "__main__":
    main()
