"""Risk profile comparison — spec 13. Research tool, read-only: runs the exact same
walk-forward backtest already validated for BTCUSDT (specs/11) once per risk profile
(Segurança/Intermediário/Arrojado — model/risk_profiles.py) and reports folds_won/PF/
drawdown side by side. Never places orders, never promotes a profile automatically.

Usage:
    python scripts/run_risk_profile_comparison.py --days 90
"""

from __future__ import annotations

import argparse
import time

from tradingbot.ingestion.binance_rest import BinanceRestClient
from tradingbot.model.evaluation import evaluate_config
from tradingbot.model.risk_profiles import ALL_PROFILES, REFERENCE_HORIZON_MINUTES


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--min-trades", type=int, default=15)
    args = parser.parse_args()

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - args.days * 24 * 60 * 60 * 1000

    print(f"Buscando {args.symbol} 1m para os últimos {args.days} dia(s)...")
    client = BinanceRestClient()
    events = client.fetch_klines(args.symbol, "1m", start_ms, end_ms)
    print(f"{len(events)} candles buscados.\n")
    if not events:
        print("Sem dado retornado — abortando.")
        return

    print(
        f"{'perfil':<14} {'entry_pct':>9} {'stop_loss':>9} {'risco/trade':>11} "
        f"{'folds_won':>10} {'mean_pf':>8} {'min_pf':>8} {'max_dd':>8} {'label_rate':>10}"
    )
    for profile in ALL_PROFILES:
        evaluation = evaluate_config(
            events,
            horizon_minutes=REFERENCE_HORIZON_MINUTES,
            entry_percentile=profile.entry_percentile,
            n_splits=args.n_splits,
            min_trades=args.min_trades,
            use_regime_filter=False,
            stop_loss_pct=profile.stop_loss_pct,
            risk_config=profile.risk_config,
        )
        max_dd = max((f.max_drawdown_pct for f in evaluation.folds), default=0.0)
        print(
            f"{profile.name:<14} {profile.entry_percentile:>9.1f} {profile.stop_loss_pct:>8.1%} "
            f"{profile.risk_config.risk_per_trade_pct:>10.1%} "
            f"{evaluation.folds_won:>3}/{evaluation.folds_total:<6} {evaluation.mean_profit_factor:>8.2f} "
            f"{evaluation.min_profit_factor:>8.2f} {max_dd:>7.1%} {evaluation.label_rate:>9.1%}"
        )


if __name__ == "__main__":
    main()
