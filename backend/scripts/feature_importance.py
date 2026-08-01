"""Fase 2 diagnostic (spec 04/11): SHAP feature importance for the walk-forward model —
motivated by six rounds of feature/target/threshold iteration (specs/11 roadmap) that
still haven't closed the gap to the promotion criteria (specs/07). Answers "what is the
model actually using?". CLI wrapper — the actual computation lives in
tradingbot.model.importance so the Fase 5 agentic loop (spec 09) can call it directly.

Usage:
    python scripts/feature_importance.py --symbol BTCUSDT --interval 1m --days 90 \
        --horizon-minutes 45
"""

from __future__ import annotations

import argparse
import time

from tradingbot.ingestion.binance_rest import BinanceRestClient
from tradingbot.model.importance import compute_feature_importance

MOVE_THRESHOLD_PCT = 0.008  # 2026-07-31 recalibration — held fixed, consistent with the other Fase 2 scripts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--horizon-minutes", type=int, default=45)
    parser.add_argument("--move-threshold-pct", type=float, default=MOVE_THRESHOLD_PCT)
    parser.add_argument("--testnet", action="store_true")
    args = parser.parse_args()

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - args.days * 24 * 60 * 60 * 1000

    print(f"Fetching {args.symbol} {args.interval} klines for the last {args.days} day(s)...")
    client = BinanceRestClient(testnet=args.testnet)
    events = client.fetch_klines(args.symbol, args.interval, start_ms, end_ms)
    print(f"Fetched {len(events)} closed klines.\n")
    if not events:
        print("No data returned — aborting.")
        return

    importances = compute_feature_importance(
        events,
        horizon_minutes=args.horizon_minutes,
        move_threshold_pct=args.move_threshold_pct,
        n_splits=args.n_splits,
    )

    print(f"{'feature':<22}{'|SHAP| médio':>14}{'direção (corr)':>16}")
    for imp in importances:
        print(f"{imp.name:<22}{imp.mean_abs_shap:>14.5f}{imp.direction_corr:>16.2f}")


if __name__ == "__main__":
    main()
