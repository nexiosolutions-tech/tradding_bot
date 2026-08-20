"""Consulta point-in-time sobre o índice mestre de filings — spec 14, Seção 5.2.

"O que a CVM tinha publicado sobre a empresa X, como sabido na data D" — o contrato do
qual toda a camada de fundamento (Fase 2 em diante) depende.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.acoes.models import CvmFiling, CvmFinancialLineItem


def get_filing_as_of(
    session: Session,
    cnpj_cia: str,
    dt_refer: date,
    categ_doc: str,
    data_decisao: date,
) -> CvmFiling | None:
    """Devolve o filing de `(cnpj_cia, dt_refer, categ_doc)` como ele era conhecido em
    `data_decisao`: a **maior `versao`** cujo `dt_receb <= data_decisao`.

    Filtro primeiro por `dt_receb` (só filings já publicados até a data), *depois* máximo
    de `versao` entre os que sobraram — nunca o máximo de versão que existe hoje. Inverter
    essa ordem (pegar a versão mais recente e só then checar a data) devolveria uma
    retificação futura em relação a `data_decisao`, quebrando point-in-time em silêncio.

    Convenção de fronteira, decidida e testada (spec 14, Seção 5.2/13): `dt_receb ==
    data_decisao` **conta como disponível** (`<=`, não `<`) — um filing recebido pela CVM
    no mesmo dia da decisão é tratado como público a partir daquele dia, mesma convenção
    já usada para `data_publicacao <= data_decisão` em todo o resto da spec (Seção 5).
    """
    stmt = (
        select(CvmFiling)
        .where(
            CvmFiling.cnpj_cia == cnpj_cia,
            CvmFiling.dt_refer == dt_refer,
            CvmFiling.categ_doc == categ_doc,
            CvmFiling.dt_receb <= data_decisao,
        )
        .order_by(CvmFiling.versao.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def get_line_items_as_of(
    session: Session,
    cnpj_cia: str,
    dt_refer: date,
    categ_doc: str,
    data_decisao: date,
) -> list[CvmFinancialLineItem]:
    """Contrato completo da Seção 5.2: junta os itens financeiros à `versao` do filing
    visível em `data_decisao` (via `get_filing_as_of`) e filtra `ordem_exerc = 'ÚLTIMO'`
    — o comparativo `PENÚLTIMO` do mesmo filing nunca é devolvido como fato point-in-time
    primário (Seção 5.1). Lista vazia se não houver filing visível naquela data (mesmo
    caso do Banco do Brasil em `2025-02-18`, antes do `dt_receb` real)."""
    filing = get_filing_as_of(session, cnpj_cia, dt_refer, categ_doc, data_decisao)
    if filing is None:
        return []
    stmt = select(CvmFinancialLineItem).where(
        CvmFinancialLineItem.cnpj_cia == cnpj_cia,
        CvmFinancialLineItem.dt_refer == dt_refer,
        CvmFinancialLineItem.versao == filing.versao,
        CvmFinancialLineItem.ordem_exerc == "ÚLTIMO",
    )
    return list(session.execute(stmt).scalars().all())
