"""Índice mestre de filings da CVM — spec 14, Seção 5.1/5.2.

`DT_RECEB` (data_publicacao) só existe no arquivo-índice, não nos arquivos de item
financeiro — toda linha de fundamento futura faz join com esta tabela por
`(cnpj_cia, dt_refer, versao, categ_doc)` para herdar a data de publicação real.
"""

from __future__ import annotations

from sqlalchemy import Date, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tradingbot.acoes.persistence import Base


class CvmFiling(Base):
    """Uma linha do arquivo-índice (`dfp_cia_aberta_AAAA.csv` / `itr_cia_aberta_AAAA.csv`).

    Append-only por desenho, não por convenção: uma retificação chega como
    `(cnpj_cia, dt_refer, versao+1, dt_receb_nova)`, nunca sobrescrevendo a linha da
    versão anterior. `UniqueConstraint` abaixo é a garantia estrutural — rejeita
    `INSERT` duplicado de `(cnpj_cia, dt_refer, versao, categ_doc)` em vez de aceitar um
    `UPDATE` que apagaria a versão antiga e quebraria a consulta point-in-time em
    silêncio (spec 14, Seção 5.1).
    """

    __tablename__ = "cvm_filings"
    __table_args__ = (
        UniqueConstraint(
            "cnpj_cia", "dt_refer", "versao", "categ_doc", name="uq_cvm_filings_identity"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cnpj_cia: Mapped[str] = mapped_column(String, index=True)
    dt_refer: Mapped[Date] = mapped_column(Date, index=True)
    versao: Mapped[int] = mapped_column(Integer)
    categ_doc: Mapped[str] = mapped_column(String)  # "DFP" | "ITR"
    denom_cia: Mapped[str] = mapped_column(String)
    cd_cvm: Mapped[str] = mapped_column(String)
    id_doc: Mapped[str] = mapped_column(String)
    dt_receb: Mapped[Date] = mapped_column(Date, index=True)
    link_doc: Mapped[str] = mapped_column(String)


class CvmFinancialLineItem(Base):
    """Uma linha de um arquivo de item financeiro (`dfp_cia_aberta_DRE_con_AAAA.csv` e
    equivalentes). **Escopo desta rodada: só o suficiente para provar o contrato
    point-in-time contra dado real (spec 14, Seção 5.2, teste de `ORDEM_EXERC`)** — não é
    a ingestão genérica de todos os tipos de demonstração (BPA/BPP/DRE/DFC/DMPL/DRA/DVA,
    con/ind), que fica para quando o resto do fundamento (Fase 2) for construído.

    `ordem_exerc` é o campo que a Seção 5.1 identificou como armadilha: cada filing traz
    o exercício atual (`ÚLTIMO`) e o comparativo do ano anterior (`PENÚLTIMO`) na mesma
    linha de dado, possivelmente com valor reapresentado. Só `ÚLTIMO` é fato point-in-time
    primário — `PENÚLTIMO` nunca é fonte de fator, existe só para detecção de
    reapresentação (não implementada nesta rodada).
    """

    __tablename__ = "cvm_financial_line_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cnpj_cia: Mapped[str] = mapped_column(String, index=True)
    dt_refer: Mapped[Date] = mapped_column(Date, index=True)
    versao: Mapped[int] = mapped_column(Integer)
    ordem_exerc: Mapped[str] = mapped_column(String)  # "ÚLTIMO" | "PENÚLTIMO"
    cd_conta: Mapped[str] = mapped_column(String, index=True)
    ds_conta: Mapped[str] = mapped_column(String)
    vl_conta: Mapped[float] = mapped_column(Float)
