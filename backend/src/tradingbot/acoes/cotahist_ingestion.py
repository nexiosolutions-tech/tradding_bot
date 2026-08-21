"""Ingestão de preço bruto B3 (COTAHIST) — spec 14, Seção 4.2/5.3.

Arquivo real: `COTAHIST_AAAA.ZIP`, um `.TXT` de largura fixa (245 bytes/registro) dentro,
`https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_AAAA.ZIP`. Layout oficial
confirmado via `SeriesHistoricas_Layout.pdf` (B3), não assumido.

Preço bruto normalizado por `FATCOT` na ingestão (nunca ajustado por evento corporativo —
isso é responsabilidade da consulta, cruzando com `CorporateEventFlag`). Eventos
societários detectados pela transição do sufixo "ex-" em `ESPECI`, tipo + data apenas,
nunca magnitude (a COTAHIST não carrega valor de provento nem razão de
bonificação/grupamento/desdobramento).
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tradingbot.acoes.models import CorporateEventFlag, CotahistPrice

EQUITY_ESPECI_PREFIXES = ("ON", "PN", "PR", "OR")
EQUITY_ESPECI_EXACT = {"UNT"}

# Sufixos "ex-" que mudam quantidade de ações sem contrapartida em caixa — confirmado
# contra dado real (BBAS3, 2024-04-16, EB: -50,57%; EJ e EDJ do mesmo ticker, mesmo ano,
# ficaram entre -3,53% e +0,65%, nunca perto de uma quebra de nível).
_LEVEL_BREAK_MARKERS = ("B", "G")  # bonificação, grupamento


@dataclass(frozen=True)
class RawPriceRow:
    ticker: str
    trade_date: date
    especi_raw: str
    ex_suffix: str | None
    fatcot: int
    open: float
    high: float
    low: float
    avg: float
    close: float
    quantity: int
    financial_volume: float


def _is_equity(especi_raw: str) -> bool:
    base = especi_raw.split()[0] if especi_raw.split() else ""
    return base.startswith(EQUITY_ESPECI_PREFIXES) or base in EQUITY_ESPECI_EXACT


def _parse_ex_suffix(especi_raw: str) -> str | None:
    """`ESPECI` crua tokeniza por espaço: classe, sufixo "ex-" opcional (sempre começa
    com "E"), tag de segmento opcional (ex. "NM") — confirmado por inspeção de byte a
    byte contra dado real (`'ON  EB  NM'` → `['ON', 'EB', 'NM']`), não por posição fixa
    dentro do campo, porque a tag de segmento desloca onde o sufixo apareceria."""
    tokens = especi_raw.split()
    if len(tokens) >= 2 and tokens[1].startswith("E") and tokens[1] != especi_raw:
        return tokens[1]
    return None


def _is_level_break(ex_suffix: str) -> bool:
    return any(marker in ex_suffix for marker in _LEVEL_BREAK_MARKERS)


def normalize_price(raw_price_cents: int, fatcot: int) -> float:
    """`raw_price_cents` é o valor cru do campo (`N(13)V99`, 2 casas decimais
    implícitas). Verificado contra dado real, não assumido do layout — `VOLTOT/QUATOT`
    (preço médio real, invariante a qualquer convenção de escala) bate com
    `PREULT/FATCOT` tanto para `FATCOT=1000` quanto para o valor `FATCOT=10` (não
    documentado no layout oficial, só presente no dado real)."""
    return raw_price_cents / 100 / fatcot


def parse_cotahist_year(zip_path: Path, *, equity_only: bool = True) -> Iterator[RawPriceRow]:
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.upper().endswith(".TXT")]
        with zf.open(names[0]) as f:
            for raw in f:
                line = raw.decode("latin-1")
                if line[0:2] != "01" or line[10:12] != "02" or line[24:27] != "010":
                    continue
                especi_raw = line[39:49]
                if equity_only and not _is_equity(especi_raw):
                    continue
                trade_date = date(int(line[2:6]), int(line[6:8]), int(line[8:10]))
                fatcot = int(line[210:217])
                yield RawPriceRow(
                    ticker=line[12:24].strip(),
                    trade_date=trade_date,
                    especi_raw=especi_raw,
                    ex_suffix=_parse_ex_suffix(especi_raw),
                    fatcot=fatcot,
                    open=normalize_price(int(line[56:69]), fatcot),
                    high=normalize_price(int(line[69:82]), fatcot),
                    low=normalize_price(int(line[82:95]), fatcot),
                    avg=normalize_price(int(line[95:108]), fatcot),
                    close=normalize_price(int(line[108:121]), fatcot),
                    quantity=int(line[152:170]),
                    financial_volume=int(line[170:188]) / 100,
                )


@dataclass
class CotahistIngestStats:
    prices_inserted: int = 0
    prices_rejected_duplicate: int = 0
    events_inserted: int = 0
    events_rejected_duplicate: int = 0


def ingest_cotahist_year(session: Session, zip_path: Path) -> CotahistIngestStats:
    """Preço: um `INSERT` por linha, savepoint própria, duplicata rejeitada pela
    `UniqueConstraint(ticker, trade_date)` — mesmo padrão de `cvm_ingestion.py`.

    Eventos: detectados por transição — o `ex_suffix` do dia comparado ao do pregão
    anterior do mesmo ticker (não por posição fixa no arquivo, que já vem ordenado por
    ticker e depois por data). Só a **primeira** data de uma nova sequência de sufixo
    gera evento; a mesma sequência persistindo por vários pregões (confirmado no dado
    real — `ON EJ` do BBAS3 durou ~8 pregões seguidos) não gera eventos repetidos.
    """
    stats = CotahistIngestStats()
    last_suffix_by_ticker: dict[str, str | None] = {}

    for raw in parse_cotahist_year(zip_path):
        price = CotahistPrice(
            ticker=raw.ticker,
            trade_date=raw.trade_date,
            especi_raw=raw.especi_raw,
            fatcot=raw.fatcot,
            open=raw.open,
            high=raw.high,
            low=raw.low,
            avg=raw.avg,
            close=raw.close,
            quantity=raw.quantity,
            financial_volume=raw.financial_volume,
        )
        try:
            with session.begin_nested():
                session.add(price)
        except IntegrityError:
            stats.prices_rejected_duplicate += 1
        else:
            stats.prices_inserted += 1

        previous_suffix = last_suffix_by_ticker.get(raw.ticker)
        last_suffix_by_ticker[raw.ticker] = raw.ex_suffix
        if raw.ex_suffix is not None and raw.ex_suffix != previous_suffix:
            event = CorporateEventFlag(
                ticker=raw.ticker,
                event_date=raw.trade_date,
                ex_suffix=raw.ex_suffix,
                is_level_break=_is_level_break(raw.ex_suffix),
                source="ESPECI_TRANSITION",
            )
            try:
                with session.begin_nested():
                    session.add(event)
            except IntegrityError:
                stats.events_rejected_duplicate += 1
            else:
                stats.events_inserted += 1

    session.commit()
    return stats
