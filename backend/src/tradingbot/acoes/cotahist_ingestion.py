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

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tradingbot.acoes.models import CorporateEventFlag, CotahistPrice

# Tamanho de lote para o INSERT de preço — não é o gargalo em si (medido: parsing puro é
# ~7s/ano, savepoint-por-linha some o resto do tempo em overhead de transação, não em
# I/O de disco por commit — SQLite só faz fsync no commit externo, não por SAVEPOINT).
# Lote em vez de um commit por arquivo inteiro porque uma linha ruim no meio de ~65-75k
# não pode derrubar o ano inteiro sem diagnóstico — só o lote em que ela caiu refaz por
# linha (ver `_flush_price_batch`).
PRICE_BATCH_SIZE = 2000


class IngestionCountMismatchError(RuntimeError):
    """Contagem de preços persistidos (lida do banco após o commit) não bate com a
    contagem de chaves `(ticker, trade_date)` distintas obtidas do parsing do arquivo.

    Existe para pegar dois modos de falha, não um: truncamento silencioso (linha nunca
    chega a virar `INSERT`) e falha parcial de lote (uma exceção durante o lote derruba
    ou pula linhas que deveriam ter sido persistidas). Deliberadamente lê do banco, não
    de um contador incrementado no laço — um contador em memória mentiria exatamente no
    caso que esta asserção existe para pegar."""

EQUITY_ESPECI_PREFIXES = ("ON", "PN", "PR", "OR")
EQUITY_ESPECI_EXACT = {"UNT"}

# Sufixos "ex-" que mudam quantidade de ações sem contrapartida em caixa — confirmado
# contra dado real (BBAS3, 2024-04-16, EB: -50,57%; EJ e EDJ do mesmo ticker, mesmo ano,
# ficaram entre -3,53% e +0,65%, nunca perto de uma quebra de nível).
_LEVEL_BREAK_MARKERS = ("B", "G")  # bonificação, grupamento

# "EX" não está em nenhuma linha da tabela oficial de ESPECI — rótulo ambíguo, confirmado
# medindo as 73 ocorrências reais em 2010-2026: 67,1% dentro de ±5% (ruído/distribuição em
# caixa normal), mas 4 (CEBR6/CEBR3/CEBR5 no mesmo dia, VIVT3) caem a -80,96%/-80,35%/
# -80,12%/-50,08% — quebra de nível real. Vão real na distribuição entre -22,54% e
# -50,08%, sem nenhum caso no meio — o limiar abaixo fica dentro desse vão, não escolhido
# por conveniência.
EX_LEVEL_BREAK_THRESHOLD = 0.33


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


def _is_level_break(ex_suffix: str, pct_change: float | None) -> bool:
    """`B`/`G` (bonificação/grupamento) são quebra de nível sempre — estrutural, decidido
    só pelo sufixo. `EX` é ambíguo — decidido caso a caso pelo retorno do próprio dia
    (`EX_LEVEL_BREAK_THRESHOLD`), porque o rótulo sozinho cobre tanto ruído/distribuição
    em caixa (67% dos casos medidos) quanto quebra de nível real (o resto). Demais
    sufixos (ED/EJ/ER/ES e combinações sem B/G) seguem `False` — distribuição em caixa
    real, não quebra artificial (medido para EJ/EDJ contra BBAS3/2024, não para todos)."""
    if any(marker in ex_suffix for marker in _LEVEL_BREAK_MARKERS):
        return True
    if ex_suffix == "EX":
        return pct_change is not None and abs(pct_change) >= EX_LEVEL_BREAK_THRESHOLD
    return False


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


def _flush_price_batch(
    session: Session, batch: list[CotahistPrice], stats: CotahistIngestStats
) -> None:
    """Tenta o lote inteiro numa savepoint só (caminho comum: nenhuma duplicata, todo o
    lote entra num único `INSERT` em lote). Só se o lote falhar — uma duplicata real de
    reingestão, ou qualquer outra violação de integridade — refaz aquele lote específico
    linha por linha, isolando exatamente a(s) linha(s) problemática(s) sem pagar o custo
    de savepoint-por-linha no caso comum, e sem nunca descartar uma linha em silêncio."""
    if not batch:
        return
    try:
        with session.begin_nested():
            session.add_all(batch)
    except IntegrityError:
        for price in batch:
            try:
                with session.begin_nested():
                    session.add(price)
            except IntegrityError:
                stats.prices_rejected_duplicate += 1
            else:
                stats.prices_inserted += 1
    else:
        stats.prices_inserted += len(batch)
    batch.clear()


def ingest_cotahist_year(
    session: Session, zip_path: Path, *, batch_size: int = PRICE_BATCH_SIZE
) -> CotahistIngestStats:
    """Preço: `INSERT` em lote (`batch_size` linhas por savepoint), com fallback
    automático a linha por linha só no lote que falhar — ver `_flush_price_batch`.
    Duplicata (reingestão do mesmo ano, ou do mesmo arquivo) rejeitada pela
    `UniqueConstraint(ticker, trade_date)`, mesma garantia estrutural de sempre, banco
    decidindo, não checagem de existência em código.

    Eventos: mantidos em savepoint-por-linha — raros (algumas centenas por ano, não
    ~65-75 mil), não são o custo medido, não valia complicar o caminho comum para algo
    que não é o gargalo. Detectados por transição — o `ex_suffix` do dia comparado ao do
    pregão anterior do mesmo ticker (não por posição fixa no arquivo, que já vem
    ordenado por ticker e depois por data). Só a **primeira** data de uma nova sequência
    de sufixo gera evento; a mesma sequência persistindo por vários pregões (confirmado
    no dado real — `ON EJ` do BBAS3 durou ~8 pregões seguidos) não gera eventos
    repetidos.

    Depois do commit, `IngestionCountMismatchError` dispara se a contagem de preços
    persistidos no intervalo de datas do arquivo (lida do banco) não bater com a
    contagem de chaves `(ticker, trade_date)` distintas vistas no parsing — pega
    truncamento silencioso e falha parcial de lote, os dois modos de falha que a troca
    para lote introduz ou herda (spec 14, Seção 6.2).
    """
    stats = CotahistIngestStats()
    last_suffix_by_ticker: dict[str, str | None] = {}
    last_close_by_ticker: dict[str, float] = {}
    price_batch: list[CotahistPrice] = []
    expected_keys: set[tuple[str, date]] = set()
    min_date: date | None = None
    max_date: date | None = None

    for raw in parse_cotahist_year(zip_path):
        expected_keys.add((raw.ticker, raw.trade_date))
        min_date = raw.trade_date if min_date is None else min(min_date, raw.trade_date)
        max_date = raw.trade_date if max_date is None else max(max_date, raw.trade_date)

        price_batch.append(
            CotahistPrice(
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
        )
        if len(price_batch) >= batch_size:
            _flush_price_batch(session, price_batch, stats)

        previous_suffix = last_suffix_by_ticker.get(raw.ticker)
        previous_close = last_close_by_ticker.get(raw.ticker)
        last_suffix_by_ticker[raw.ticker] = raw.ex_suffix
        last_close_by_ticker[raw.ticker] = raw.close
        if raw.ex_suffix is not None and raw.ex_suffix != previous_suffix:
            pct_change = (
                (raw.close - previous_close) / previous_close
                if previous_close
                else None
            )
            event = CorporateEventFlag(
                ticker=raw.ticker,
                event_date=raw.trade_date,
                ex_suffix=raw.ex_suffix,
                is_level_break=_is_level_break(raw.ex_suffix, pct_change),
                source="ESPECI_TRANSITION",
            )
            try:
                with session.begin_nested():
                    session.add(event)
            except IntegrityError:
                stats.events_rejected_duplicate += 1
            else:
                stats.events_inserted += 1

    _flush_price_batch(session, price_batch, stats)
    session.commit()

    if expected_keys:
        persisted = session.execute(
            select(func.count())
            .select_from(CotahistPrice)
            .where(CotahistPrice.trade_date >= min_date, CotahistPrice.trade_date <= max_date)
        ).scalar_one()
        if persisted != len(expected_keys):
            raise IngestionCountMismatchError(
                f"{zip_path.name}: {len(expected_keys)} chaves (ticker, trade_date) "
                f"distintas no parsing, mas {persisted} linhas persistidas no banco para "
                f"o intervalo {min_date}..{max_date} — falha de ingestão, não reingestão "
                f"normal (duplicata seria rejeitada pela UniqueConstraint sem afetar a "
                f"contagem final)."
            )

    return stats
