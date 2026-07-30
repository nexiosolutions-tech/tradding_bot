"""Idempotent client order IDs — spec 05 rule 5 / spec 06: a WebSocket reconnect or a
network retry must never place a duplicate order. Generating the same ID for the same
logical intent means a retry collides with itself on the exchange side (Binance rejects a
reused newClientOrderId) instead of creating a second position.
"""

from __future__ import annotations

import hashlib


def make_client_order_id(symbol: str, purpose: str, signal_ts: int, attempt: int = 0) -> str:
    raw = f"{symbol}:{purpose}:{signal_ts}:{attempt}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:20]
    return f"tb-{digest}"
