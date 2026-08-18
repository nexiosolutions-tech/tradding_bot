"""Production trade analysis — spec 09, 2026-08-17. Formalizes the fee-corrected,
day-by-day consolidated view that had been run by hand as an ad-hoc script every time this
project's production data needed a real look (the same correction `daily_report.py` now
applies automatically per day) — this is the multi-day version, for when a single day
isn't the question. Read-only.

Usage:
    DATABASE_URL=<postgres url> python scripts/analyze_production.py --days 30
"""

from __future__ import annotations

import argparse
import os
import time
from collections import defaultdict
from datetime import datetime, timezone

from tradingbot.backtesting.costs import net_trade_pnl
from tradingbot.persistence.db import get_session_factory
from tradingbot.persistence.repository import (
    latest_unacknowledged_circuit_breaker,
    trades_in_range,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - args.days * 24 * 60 * 60 * 1000

    session = get_session_factory(os.environ.get("DATABASE_URL"))()
    trades = trades_in_range(session, start_ms, end_ms)

    print(f"Total de trades no período ({args.days} dia(s)): {len(trades)}")
    if not trades:
        return

    by_day = defaultdict(list)
    by_reason = defaultdict(list)
    for t in trades:
        day = datetime.fromtimestamp(t.exit_ts / 1000, tz=timezone.utc).date().isoformat()
        by_day[day].append(t)
        by_reason[t.exit_reason].append(t)

    print(f"\n{'dia':<12} {'trades':>6} {'win% bruto':>11} {'pnl bruto':>10} {'pnl líquido':>12} {'win% líquido':>13}")
    total_trades = 0
    total_raw = 0.0
    total_net = 0.0
    total_wins_raw = 0
    total_wins_net = 0
    for day, day_trades in sorted(by_day.items()):
        raw_pnl = sum(t.pnl for t in day_trades)
        net_pnls = [net_trade_pnl(t) for t in day_trades]
        net_pnl = sum(net_pnls)
        wins_raw = sum(1 for t in day_trades if t.pnl > 0)
        wins_net = sum(1 for p in net_pnls if p > 0)
        n = len(day_trades)
        print(f"{day:<12} {n:>6} {wins_raw / n:>10.0%} {raw_pnl:>10.2f} {net_pnl:>12.2f} {wins_net / n:>12.0%}")
        total_trades += n
        total_raw += raw_pnl
        total_net += net_pnl
        total_wins_raw += wins_raw
        total_wins_net += wins_net

    print(
        f"{'TOTAL':<12} {total_trades:>6} {total_wins_raw / total_trades:>10.0%} {total_raw:>10.2f} "
        f"{total_net:>12.2f} {total_wins_net / total_trades:>12.0%}"
    )

    print("\n=== Por motivo de saída ===")
    for reason, reason_trades in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        net = sum(net_trade_pnl(t) for t in reason_trades)
        print(f"  {reason}: {len(reason_trades)} trades, pnl bruto {sum(t.pnl for t in reason_trades):.2f}, pnl líquido {net:.2f}")

    print("\n=== Circuit breaker ===")
    pending = latest_unacknowledged_circuit_breaker(session)
    if pending is None:
        print("  Nenhum evento pendente de reconhecimento no momento.")
    else:
        ts_str = datetime.fromtimestamp(pending.triggered_at / 1000, tz=timezone.utc).isoformat()
        print(f"  Acionado em {ts_str}, equity={pending.equity_at_trigger:.2f}, drawdown={pending.drawdown_pct:.1%} — aguardando reconhecimento humano.")

    symbols = {t.symbol for t in trades}
    print(f"\nSímbolos operados: {symbols}")


if __name__ == "__main__":
    main()
