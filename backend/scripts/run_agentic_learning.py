"""Fase 5 agentic loop entry point (spec 09) — run once a day (Railway Cron Jobs or any
cron/scheduler), same cadence as run_daily_learning.py. Fetches recent historical klines
once, then lets the reasoning model investigate autonomously (hypothesis -> tool call ->
result -> repeat) up to --max-iterations times. The only thing it can produce is a
changes/*.md file with Status: pendente — never applies anything, never touches main.

Requires ANTHROPIC_API_KEY. This has not been exercised against the live Anthropic API in
this codebase yet — validate a real cycle end to end before relying on it unattended.

Usage:
    python scripts/run_agentic_learning.py --symbol BTCUSDT --interval 1m --days 90
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from dotenv import load_dotenv

from tradingbot.ingestion.binance_rest import BinanceRestClient
from tradingbot.learning_engine.agentic_loop import AnthropicReasoningClient, run_agentic_cycle
from tradingbot.learning_engine.experiment_log import OUTCOME_BUDGET_EXHAUSTED, OUTCOME_PROPOSAL_DRAFTED
from tradingbot.learning_engine.tools import build_tools

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--model", default="claude-sonnet-5")
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

    reasoning_client = AnthropicReasoningClient(tools=build_tools(events), model=args.model)
    result = run_agentic_cycle(reasoning_client, events, max_iterations=args.max_iterations)

    print(f"Ciclo encerrado após {result.iterations} iteração(ões) — outcome: {result.outcome}")
    if result.outcome == OUTCOME_PROPOSAL_DRAFTED:
        print(f"Proposta gerada: {result.proposal_path} (status: pendente — requer revisão humana)")
    elif result.outcome == OUTCOME_BUDGET_EXHAUSTED:
        print("Orçamento de iterações esgotado sem conclusão — revisar learnings/experiments.jsonl.")
    else:
        print("Nenhum achado acionável neste ciclo.")


if __name__ == "__main__":
    main()
