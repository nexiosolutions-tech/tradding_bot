"""Ingestão do índice mestre de filings CVM (DFP/ITR) — spec 14, Seção 5.1.

Arquivo real: `dfp_cia_aberta_AAAA.csv` / `itr_cia_aberta_AAAA.csv`, dentro do zip
`https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{DFP,ITR}/DADOS/{dfp,itr}_cia_aberta_AAAA.zip`.
CSV `;`-delimitado, **latin-1** (não UTF-8) — confirmado por erro de decodificação direto
na Fase 1 (changes/2026-08-19-fase1-cvm-confirmada.md).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tradingbot.acoes.models import CvmFiling, CvmFinancialLineItem


@dataclass(frozen=True)
class RawFilingRow:
    cnpj_cia: str
    dt_refer: date
    versao: int
    categ_doc: str
    denom_cia: str
    cd_cvm: str
    id_doc: str
    dt_receb: date
    link_doc: str


def parse_master_index(csv_path: Path) -> Iterator[RawFilingRow]:
    with open(csv_path, encoding="latin-1", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            yield RawFilingRow(
                cnpj_cia=row["CNPJ_CIA"].strip(),
                dt_refer=date.fromisoformat(row["DT_REFER"].strip()),
                versao=int(row["VERSAO"]),
                categ_doc=row["CATEG_DOC"].strip(),
                denom_cia=row["DENOM_CIA"].strip(),
                cd_cvm=row["CD_CVM"].strip(),
                id_doc=row["ID_DOC"].strip(),
                dt_receb=date.fromisoformat(row["DT_RECEB"].strip()),
                link_doc=row["LINK_DOC"].strip(),
            )


@dataclass
class IngestStats:
    inserted: int = 0
    rejected_duplicate: int = 0


def ingest_master_index(session: Session, csv_path: Path) -> IngestStats:
    """Append-only: cada linha é um `INSERT` isolado numa savepoint própria, para que uma
    linha já presente (mesma `(cnpj_cia, dt_refer, versao, categ_doc)`, reprocessamento do
    mesmo arquivo ou re-ingestão de um ano já carregado) seja rejeitada pela
    `UniqueConstraint` do modelo sem derrubar as demais linhas do arquivo — a trava do
    banco decide, não uma checagem de existência em código que poderia ter um bug."""
    stats = IngestStats()
    for raw in parse_master_index(csv_path):
        filing = CvmFiling(
            cnpj_cia=raw.cnpj_cia,
            dt_refer=raw.dt_refer,
            versao=raw.versao,
            categ_doc=raw.categ_doc,
            denom_cia=raw.denom_cia,
            cd_cvm=raw.cd_cvm,
            id_doc=raw.id_doc,
            dt_receb=raw.dt_receb,
            link_doc=raw.link_doc,
        )
        try:
            with session.begin_nested():
                session.add(filing)
        except IntegrityError:
            stats.rejected_duplicate += 1
        else:
            stats.inserted += 1
    session.commit()
    return stats


def ingest_line_items_for_cnpj(
    session: Session, csv_path: Path, cnpj_cia: str
) -> IngestStats:
    """Carrega as linhas de um único CNPJ de um arquivo de item financeiro (ex.
    `dfp_cia_aberta_DRE_con_AAAA.csv`) — **escopo deliberadamente restrito**: existe só
    para provar o contrato point-in-time da Seção 5.2 contra dado real (teste de
    `ORDEM_EXERC`), não é a ingestão genérica de todos os tipos de demonstração para
    todas as empresas, que fica para a Fase 2. Sem trava de unicidade própria — cada
    execução re-carrega; não é o caminho de produção."""
    stats = IngestStats()
    with open(csv_path, encoding="latin-1", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            if row["CNPJ_CIA"].strip() != cnpj_cia:
                continue
            item = CvmFinancialLineItem(
                cnpj_cia=row["CNPJ_CIA"].strip(),
                dt_refer=date.fromisoformat(row["DT_REFER"].strip()),
                versao=int(row["VERSAO"]),
                ordem_exerc=row["ORDEM_EXERC"].strip(),
                cd_conta=row["CD_CONTA"].strip(),
                ds_conta=row["DS_CONTA"].strip(),
                vl_conta=float(row["VL_CONTA"]),
            )
            session.add(item)
            stats.inserted += 1
    session.commit()
    return stats
