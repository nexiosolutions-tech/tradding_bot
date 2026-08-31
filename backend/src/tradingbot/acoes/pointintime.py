"""Consulta point-in-time sobre o índice mestre de filings — spec 14, Seção 5.2.

"O que a CVM tinha publicado sobre a empresa X, como sabido na data D" — o contrato do
qual toda a camada de fundamento (Fase 2 em diante) depende.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select, tuple_
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


def get_latest_filing_as_of(
    session: Session,
    cnpj_cia: str,
    categ_doc: str,
    data_decisao: date,
) -> CvmFiling | None:
    """Generaliza `get_filing_as_of` para quando o `dt_refer` (exercício de referência)
    não é conhecido de antemão — o caso da Seção 6, que precisa do **último balanço
    público** antes de `data_decisao`, não de um exercício específico. Mesma disciplina de
    filtrar primeiro por `dt_receb <= data_decisao`, só depois ordenar — nunca pegar o
    `dt_refer` mais recente que existe hoje e checar a data depois, que vazaria um
    exercício ainda não publicado. Dentro do conjunto já visível, ordena por `dt_refer`
    (exercício mais recente primeiro) e, dentro do mesmo exercício, por `versao` (a
    retificação mais recente já visível) — mesma convenção de fronteira inclusiva de
    `get_filing_as_of`."""
    stmt = (
        select(CvmFiling)
        .where(
            CvmFiling.cnpj_cia == cnpj_cia,
            CvmFiling.categ_doc == categ_doc,
            CvmFiling.dt_receb <= data_decisao,
        )
        .order_by(CvmFiling.dt_refer.desc(), CvmFiling.versao.desc())
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


def get_latest_filing_as_of_lote(
    session: Session, cnpjs: list[str], categ_doc: str, data_decisao: date
) -> dict[str, CvmFiling | None]:
    """Mesma consulta de `get_latest_filing_as_of`, para todos os `cnpjs` de uma vez —
    parte da reescrita em lote (2026-08-29, achado da Fase 1: esta consulta sozinha é
    chamada até 4 vezes por empresa em `build_decisao`, uma por fator, sempre resolvendo
    o mesmo filing). `ROW_NUMBER() OVER (PARTITION BY cnpj_cia ORDER BY dt_refer DESC,
    versao DESC)` reproduz exatamente `ORDER BY dt_refer DESC, versao DESC LIMIT 1` por
    empresa, filtrado por `dt_receb <= data_decisao` antes de ordenar — mesma disciplina
    de nunca pegar o exercício mais recente que existe hoje e checar a data depois."""
    if not cnpjs:
        return {}
    rn = (
        func.row_number()
        .over(
            partition_by=CvmFiling.cnpj_cia,
            order_by=(CvmFiling.dt_refer.desc(), CvmFiling.versao.desc()),
        )
        .label("rn")
    )
    subq = (
        select(CvmFiling, rn)
        .where(
            CvmFiling.cnpj_cia.in_(cnpjs),
            CvmFiling.categ_doc == categ_doc,
            CvmFiling.dt_receb <= data_decisao,
        )
        .subquery()
    )
    stmt = select(subq).where(subq.c.rn == 1)
    por_cnpj: dict[str, CvmFiling | None] = {cnpj: None for cnpj in cnpjs}
    for row in session.execute(stmt).all():
        filing = CvmFiling(
            cnpj_cia=row.cnpj_cia, dt_refer=row.dt_refer, versao=row.versao,
            categ_doc=row.categ_doc, denom_cia=row.denom_cia, cd_cvm=row.cd_cvm,
            id_doc=row.id_doc, dt_receb=row.dt_receb, link_doc=row.link_doc,
        )
        por_cnpj[row.cnpj_cia] = filing
    return por_cnpj


def get_line_items_lote(
    session: Session, filing_por_cnpj: dict[str, CvmFiling]
) -> dict[str, list[CvmFinancialLineItem]]:
    """Busca, para todas as empresas de `filing_por_cnpj` de uma vez, todas as linhas
    `ordem_exerc='ÚLTIMO'` do filing já resolvido para cada uma — parte da reescrita em
    lote (2026-08-29). Nunca filtra por `cd_conta`/`base`: essa camada devolve tudo que
    existe para o filing, e cada extrator de fator (`fatores.py`) aplica seu próprio
    filtro em memória, exatamente como a consulta single-item de cada fator fazia —
    ver `fatores.py::_extrair_*` para onde cada regra específica vive agora."""
    if not filing_por_cnpj:
        return {}
    chaves = [
        (cnpj, filing.dt_refer, filing.versao) for cnpj, filing in filing_por_cnpj.items()
    ]
    stmt = select(CvmFinancialLineItem).where(
        tuple_(
            CvmFinancialLineItem.cnpj_cia,
            CvmFinancialLineItem.dt_refer,
            CvmFinancialLineItem.versao,
        ).in_(chaves),
        CvmFinancialLineItem.ordem_exerc == "ÚLTIMO",
    )
    linhas_por_cnpj: dict[str, list[CvmFinancialLineItem]] = {cnpj: [] for cnpj in filing_por_cnpj}
    for linha in session.execute(stmt).scalars().all():
        linhas_por_cnpj[linha.cnpj_cia].append(linha)
    return linhas_por_cnpj
