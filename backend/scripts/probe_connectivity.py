"""One-off diagnostic — spec 02, 2026-08-18. Probes which Binance hostnames are reachable
from wherever this process runs, to map the exact scope of the geoblock found on
2026-08-18 (HTTP 451 on mainnet WS market data from this Railway project's region).
Not part of the running system — invoked manually as a temporary startCommand override,
never referenced by any service in normal operation. See
changes/2026-08-18-captura-aggtrade-fluxo-ordens.md.

Usage:
    python scripts/probe_connectivity.py
"""

from __future__ import annotations

import httpx

HOSTS = [
    ("stream.binance.com", "https://stream.binance.com:9443/api/v3/ping"),
    ("api.binance.com", "https://api.binance.com/api/v3/ping"),
    ("data-api.binance.vision", "https://data-api.binance.vision/api/v3/ping"),
    ("data.binance.vision", "https://data.binance.vision/"),
]


def main() -> None:
    print("=== Sondagem de conectividade Binance (2026-08-18) ===")
    for label, url in HOSTS:
        try:
            resp = httpx.get(url, timeout=10.0, follow_redirects=True)
            print(f"{label}: HTTP {resp.status_code}")
        except httpx.HTTPError as exc:
            print(f"{label}: ERRO DE REDE ({exc!r})")
    print("=== Fim da sondagem ===")


if __name__ == "__main__":
    main()
