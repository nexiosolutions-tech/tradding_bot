"""Classificação setorial real da B3 — spec 14, Seção 6.1/13.

Fonte verificada contra o dado real, não presumida do nome da página (a página HTML de
"Classificação setorial" não expõe nenhum arquivo de download — os dados vêm de uma API
JS por trás dela, `sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/
GetDetail/{params_base64}`, achada inspecionando o bundle carregado pela página, não
documentada publicamente).

**Schema confirmado por chamada real** (`GetDetail`, `codeCVM=9512`, Petrobras):
`industryClassification` é uma string de três níveis separados por `" / "` — setor
econômico / subsetor / segmento (`"Petróleo. Gás e Biocombustíveis / Petróleo. Gás e
Biocombustíveis / Exploração. Refino e Distribuição"`). O primeiro nível é o que a Seção
7 assume como "~10 setores" — confirmado contra o universo real de 2016: 11 setores
distintos (Seção 6.1).

**Chave de junção é o CNPJ direto** (`cnpj` vem no próprio payload, formato sem pontuação
— `_normalize_cnpj` converte para o formato pontuado usado no resto do módulo). Não
precisa passar por `cnpj_ticker_map` para esta junção específica.

**Cobertura confirmada empiricamente, não presumida**: só empresas listadas *hoje*.
`codeCVM=1279` (registro antigo do Itaú, cancelado numa reestruturação) e `codeCVM=20753`
(Banco Cruzeiro do Sul, falido) devolvem payload vazio (`{}`); `codeCVM=19348` (registro
atual do Itaú) devolve classificação completa. Medido sobre as 115 empresas reais do
universo de 2016-02-29: 98/115 (85%) têm classificação hoje — os 17 sem cobertura são
majoritariamente empresas que sofreram fusão/incorporação/falência/troca de ticker na
década seguinte (`LAME4`→Americanas pós-recuperação judicial, `FIBR3`→incorporada pela
Suzano, `SMLE3`→incorporada pela GOL, `QGEP3`→renomeada Enauta, entre outras) — não um bug
de junção.
"""

from __future__ import annotations

import base64
import json
import urllib.request
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tradingbot.acoes.models import B3IndustryClassification

_ENDPOINT = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetDetail/{params}"


def _normalize_cnpj(raw_cnpj: str) -> str:
    """`"33000167000101"` -> `"33.000.167/0001-01"` — formato pontuado usado no resto do
    módulo (`CnpjTickerMap`, `CvmFiling`)."""
    digits = raw_cnpj.strip()
    if len(digits) != 14 or not digits.isdigit():
        return digits
    return f"{digits[0:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:14]}"


def parse_industry_classification(raw: str) -> tuple[str, str, str] | None:
    """`"Setor / Subsetor / Segmento"` -> `(setor, subsetor, segmento)`. `None` se a
    string não tiver os três níveis (payload vazio de empresa sem cobertura, ou campo
    ausente)."""
    if not raw:
        return None
    partes = [p.strip() for p in raw.split(" / ")]
    if len(partes) != 3 or not all(partes):
        return None
    return partes[0], partes[1], partes[2]


def fetch_classification(code_cvm: str) -> dict | None:
    """Chamada real ao endpoint `GetDetail` — thin wrapper, não testado com rede real (a
    suíte usa `ingest_classification_snapshot` diretamente sobre respostas já capturadas,
    mesma separação já usada no resto do módulo entre parsing e I/O). Devolve `None` se a
    empresa não tem cobertura hoje (payload vazio) ou se `cnpj`/`industryClassification`
    vier ausente."""
    params = {"codeCVM": code_cvm, "language": "pt-br"}
    b64 = base64.b64encode(json.dumps(params).encode()).decode()
    url = _ENDPOINT.format(params=b64)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8")
    parsed = json.loads(body)
    inner = json.loads(parsed) if isinstance(parsed, str) else parsed
    if not inner or not inner.get("cnpj") or not inner.get("industryClassification"):
        return None
    return inner


def get_latest_b3_classification(session: Session, cnpj: str) -> B3IndustryClassification | None:
    """A classificação B3 é atributo quase-estático (Seção 6.2), não point-in-time — não
    existe conceito de "como era conhecida em `data_decisao`" aqui, só "a versão mais
    recente coletada". Devolve o snapshot de `data_coleta` mais recente para o CNPJ, ou
    `None` se a empresa nunca teve cobertura (deslistada antes de qualquer coleta, ou
    payload vazio em todas as tentativas)."""
    stmt = (
        select(B3IndustryClassification)
        .where(B3IndustryClassification.cnpj == cnpj)
        .order_by(B3IndustryClassification.data_coleta.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def get_latest_b3_classification_lote(
    session: Session, cnpjs: list[str]
) -> dict[str, B3IndustryClassification | None]:
    """Mesma consulta de `get_latest_b3_classification`, para todos os `cnpjs` de uma vez
    — parte da reescrita em lote (2026-08-29). Atributo quase-estático (não point-in-time,
    ver docstring da função single-item), então "mais recente" aqui é só `data_coleta`
    máxima por CNPJ, sem nenhum filtro de data de decisão envolvido."""
    if not cnpjs:
        return {}
    stmt = select(B3IndustryClassification).where(B3IndustryClassification.cnpj.in_(cnpjs))
    por_cnpj: dict[str, B3IndustryClassification | None] = {cnpj: None for cnpj in cnpjs}
    melhor_coleta: dict[str, date] = {}
    for row in session.execute(stmt).scalars().all():
        atual = melhor_coleta.get(row.cnpj)
        if atual is None or row.data_coleta > atual:
            melhor_coleta[row.cnpj] = row.data_coleta
            por_cnpj[row.cnpj] = row
    return por_cnpj


@dataclass
class B3ClassificationStats:
    inserted: int = 0
    rejected_duplicate: int = 0
    sem_cobertura: int = 0


def ingest_classification_snapshot(
    session: Session,
    raw_entries: list[dict],
    data_coleta: date,
) -> B3ClassificationStats:
    """Persiste um snapshot já coletado (lista de payloads de `GetDetail`, um por
    empresa) — append-only por `(cnpj, data_coleta)`, mesmo padrão de savepoint por linha
    do resto do módulo. Empresa sem `industryClassification` válido (sem cobertura hoje)
    é contada, não descartada em silêncio."""
    stats = B3ClassificationStats()
    for entry in raw_entries:
        cnpj_raw = entry.get("cnpj")
        classificacao = parse_industry_classification(entry.get("industryClassification", ""))
        if not cnpj_raw or classificacao is None:
            stats.sem_cobertura += 1
            continue

        setor, subsetor, segmento = classificacao
        row = B3IndustryClassification(
            cnpj=_normalize_cnpj(cnpj_raw),
            code_cvm=str(entry.get("codeCVM", "")),
            setor=setor,
            subsetor=subsetor,
            segmento=segmento,
            data_coleta=data_coleta,
        )
        try:
            with session.begin_nested():
                session.add(row)
        except IntegrityError:
            stats.rejected_duplicate += 1
        else:
            stats.inserted += 1

    session.commit()
    return stats
