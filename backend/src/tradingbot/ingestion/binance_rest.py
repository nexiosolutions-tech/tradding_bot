"""REST backfill client — spec 02. Used for historical data and as a fallback when the WS
stream is down. Every method here is unauthenticated public market data (no order/account
endpoint, no API key) — confirmed 2026-08-18 (`backend/src/tradingbot/execution/client.py`
is the separate, structurally unrelated class that does real order execution)."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from tradingbot.ingestion.schema import AggTradePayload, DepthPayload, EventType, KlinePayload, MarketEvent

BINANCE_KLINES_LIMIT = 1000
BINANCE_AGG_TRADES_LIMIT = 1000
BINANCE_DEPTH_LIMIT = 100


@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    base_asset: str
    quote_asset: str
    status: str
    is_spot_trading_allowed: bool


@dataclass(frozen=True)
class Ticker24h:
    symbol: str
    quote_volume: float
    last_price: float


def _base_url(testnet: bool) -> str:
    # data-api.binance.vision, not api.binance.com (2026-08-18): confirmed via direct probe
    # (changes/2026-08-18-captura-aggtrade-fluxo-ordens.md) that api.binance.com/
    # stream.binance.com are geoblocked (HTTP 451) from this project's Railway region,
    # while data-api.binance.vision — the same public market-data routes, no auth — is
    # not. Every route this client calls is public market data, so this swap is safe for
    # 100% of its methods (confirmed: exchangeInfo/ticker/24hr respond identically there).
    return "https://testnet.binance.vision" if testnet else "https://data-api.binance.vision"


def _aggtrade_row_to_payload(row: dict) -> AggTradePayload:
    return AggTradePayload(
        agg_trade_id=int(row["a"]),
        price=float(row["p"]),
        quantity=float(row["q"]),
        first_trade_id=int(row["f"]),
        last_trade_id=int(row["l"]),
        trade_time=int(row["T"]),
        is_buyer_maker=bool(row["m"]),
    )


def _kline_row_to_payload(row: list, interval: str) -> KlinePayload:
    open_time, open_, high, low, close, volume, close_time = row[:7]
    return KlinePayload(
        open_time=int(open_time),
        close_time=int(close_time),
        interval=interval,
        open=float(open_),
        high=float(high),
        low=float(low),
        close=float(close),
        volume=float(volume),
        is_closed=True,
    )


class BinanceRestClient:
    """Sync REST client for historical klines. Kept separate from the async WS path per spec 02
    (ingestion critical path must not depend on this)."""

    def __init__(self, testnet: bool = False, timeout: float = 10.0):
        self._base_url = _base_url(testnet)
        self._timeout = timeout

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> list[MarketEvent]:
        """Fetches all closed klines in [start_ms, end_ms), paginated at the exchange limit."""
        events: list[MarketEvent] = []
        cursor = start_ms
        with httpx.Client(timeout=self._timeout) as client:
            while cursor < end_ms:
                resp = client.get(
                    f"{self._base_url}/api/v3/klines",
                    params={
                        "symbol": symbol,
                        "interval": interval,
                        "startTime": cursor,
                        "endTime": end_ms,
                        "limit": BINANCE_KLINES_LIMIT,
                    },
                )
                resp.raise_for_status()
                rows = resp.json()
                if not rows:
                    break

                for row in rows:
                    payload = _kline_row_to_payload(row, interval)
                    events.append(
                        MarketEvent(
                            symbol=symbol,
                            event_type=EventType.KLINE,
                            exchange_ts=payload.close_time,
                            local_ts=int(time.time() * 1000),
                            sequence_id=payload.open_time,
                            payload=payload.as_dict(),
                        )
                    )

                last_open_time = int(rows[-1][0])
                if last_open_time <= cursor:
                    break
                cursor = last_open_time + 1

                if len(rows) < BINANCE_KLINES_LIMIT:
                    break

        events.sort(key=lambda e: e.sequence_id)
        return events

    def fetch_agg_trades(
        self,
        symbol: str,
        from_id: int,
        to_id: int | None = None,
        limit: int = BINANCE_AGG_TRADES_LIMIT,
    ) -> list[MarketEvent]:
        """Backfills aggTrades starting at `from_id` (inclusive), paginated at the exchange
        limit, stopping once ids pass `to_id` (inclusive) if given. Used by
        run_aggtrade_capture.py to fill a gap detected by BinanceAggTradeStream's id
        sequence check — `to_id` is normally `found_id - 1`, the last id missing before the
        stream's next live message. Synchronous/blocking like fetch_klines; callers on an
        asyncio event loop must run this via asyncio.to_thread."""
        events: list[MarketEvent] = []
        cursor = from_id
        with httpx.Client(timeout=self._timeout) as client:
            while True:
                resp = client.get(
                    f"{self._base_url}/api/v3/aggTrades",
                    params={"symbol": symbol, "fromId": cursor, "limit": limit},
                )
                resp.raise_for_status()
                rows = resp.json()
                if not rows:
                    break

                reached_to_id = False
                for row in rows:
                    agg_trade_id = int(row["a"])
                    if to_id is not None and agg_trade_id > to_id:
                        reached_to_id = True
                        break
                    payload = _aggtrade_row_to_payload(row)
                    events.append(
                        MarketEvent(
                            symbol=symbol,
                            event_type=EventType.TRADE,
                            exchange_ts=payload.trade_time,
                            local_ts=int(time.time() * 1000),
                            sequence_id=payload.agg_trade_id,
                            payload=payload.as_dict(),
                        )
                    )
                if reached_to_id:
                    break

                last_id = int(rows[-1]["a"])
                if last_id < cursor:
                    break
                cursor = last_id + 1

                if (to_id is not None and cursor > to_id) or len(rows) < limit:
                    break

        events.sort(key=lambda e: e.sequence_id)
        return events

    def fetch_depth(self, symbol: str, limit: int = BINANCE_DEPTH_LIMIT) -> DepthPayload:
        """Order book snapshot — spec 02, 2026-08-18. `limit` chosen at the call site should
        match whatever depth was previously captured, so a switch of data source doesn't
        silently shift the feature's meaning (run_depth_capture.py uses 20, matching the
        `@depth20@1000ms` WS stream it replaced). Synchronous/blocking like fetch_klines;
        callers on an asyncio event loop must run this via asyncio.to_thread."""
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(f"{self._base_url}/api/v3/depth", params={"symbol": symbol, "limit": limit})
            resp.raise_for_status()
            data = resp.json()
        return DepthPayload(
            last_update_id=int(data["lastUpdateId"]),
            bids=[(float(p), float(q)) for p, q in data["bids"]],
            asks=[(float(p), float(q)) for p, q in data["asks"]],
        )

    def fetch_exchange_info(self) -> list[SymbolInfo]:
        """Spec 12 — universe of tradable symbols, used by the coin screening tool."""
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(f"{self._base_url}/api/v3/exchangeInfo")
            resp.raise_for_status()
            data = resp.json()
        return [
            SymbolInfo(
                symbol=s["symbol"],
                base_asset=s["baseAsset"],
                quote_asset=s["quoteAsset"],
                status=s["status"],
                is_spot_trading_allowed=bool(s["isSpotTradingAllowed"]),
            )
            for s in data["symbols"]
        ]

    def fetch_24h_tickers(self) -> list[Ticker24h]:
        """Spec 12 — 24h volume/price for every symbol in a single call, used by the coin
        screening tool's liquidity/price floor filter."""
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(f"{self._base_url}/api/v3/ticker/24hr")
            resp.raise_for_status()
            data = resp.json()
        return [
            Ticker24h(symbol=t["symbol"], quote_volume=float(t["quoteVolume"]), last_price=float(t["lastPrice"]))
            for t in data
        ]
