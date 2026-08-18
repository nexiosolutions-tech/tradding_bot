"""One-off diagnostic — spec 02, 2026-08-18. Probes which Binance hostnames/routes are
reachable from wherever this process runs, and what's actually archived for spot in the
historical-data bucket. Grew out of the geoblock found on 2026-08-18 (HTTP 451 on mainnet
WS market data from this Railway project's region) — round 2 checks the *concrete* public
REST routes on data-api.binance.vision (not just its root) and lists what data types exist
for spot under data.binance.vision (root/ping alone doesn't say whether depth is archived).
Not part of the running system — invoked manually as a temporary startCommand override,
never referenced by any service in normal operation. See
changes/2026-08-18-captura-aggtrade-fluxo-ordens.md.

Usage:
    python scripts/probe_connectivity.py
"""

from __future__ import annotations

import httpx

PING_HOSTS = [
    ("stream.binance.com", "https://stream.binance.com:9443/api/v3/ping"),
    ("api.binance.com", "https://api.binance.com/api/v3/ping"),
]

# data-api.binance.vision claims to mirror api.binance.com's public market-data routes —
# check the routes this project actually needs, not just the root, since a 200 on root
# doesn't confirm the specific routes are live/unrestricted.
DATA_API_ROUTES = [
    ("GET /api/v3/depth", "https://data-api.binance.vision/api/v3/depth?symbol=BTCUSDT&limit=5"),
    ("GET /api/v3/aggTrades", "https://data-api.binance.vision/api/v3/aggTrades?symbol=BTCUSDT&limit=5"),
    ("GET /api/v3/klines", "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=5"),
]

# The human-facing data.binance.vision page is a client-side JS listing renderer reading
# from this underlying S3 bucket directly -- query the bucket's own list-objects endpoint
# (returns XML) to see what data types actually exist for spot, not the empty HTML shell.
SPOT_ARCHIVE_LISTING_URL = (
    "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/"
    "?delimiter=/&prefix=data/spot/daily/"
)


def main() -> None:
    print("=== Sondagem de conectividade Binance — rotas concretas (2026-08-18) ===\n")

    print("-- Hosts principais (.com) --")
    for label, url in PING_HOSTS:
        try:
            resp = httpx.get(url, timeout=10.0, follow_redirects=True)
            print(f"{label}: HTTP {resp.status_code}")
        except httpx.HTTPError as exc:
            print(f"{label}: ERRO DE REDE ({exc!r})")

    print("\n-- data-api.binance.vision, rotas concretas --")
    for label, url in DATA_API_ROUTES:
        try:
            resp = httpx.get(url, timeout=10.0, follow_redirects=True)
            body_preview = resp.text[:200].replace("\n", " ")
            print(f"{label}: HTTP {resp.status_code} — corpo: {body_preview}")
        except httpx.HTTPError as exc:
            print(f"{label}: ERRO DE REDE ({exc!r})")

    print("\n-- data.binance.vision, o que existe para spot/daily --")
    try:
        resp = httpx.get(SPOT_ARCHIVE_LISTING_URL, timeout=15.0, follow_redirects=True)
        print(f"listing: HTTP {resp.status_code}")
        print(resp.text[:3000])
    except httpx.HTTPError as exc:
        print(f"listing: ERRO DE REDE ({exc!r})")

    print("\n=== Fim da sondagem ===")


if __name__ == "__main__":
    main()
