"""REST backfill client — spec 02. Used for historical data and as a fallback when the WS stream is down."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from tradingbot.ingestion.schema import EventType, KlinePayload, MarketEvent

BINANCE_KLINES_LIMIT = 1000


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
    return "https://testnet.binance.vision" if testnet else "https://api.binance.com"


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
