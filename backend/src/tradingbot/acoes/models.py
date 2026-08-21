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


class CotahistPrice(Base):
    """Um pregão de um ticker — spec 14, Seção 5.3. Preço **bruto normalizado por
    `FATCOT`**, nunca ajustado por evento corporativo (isso é responsabilidade da consulta
    point-in-time, cruzando com `CorporateEventFlag`, nunca da ingestão).

    Normalização por `FATCOT` verificada contra o próprio dado, não assumida do layout:
    `VOLTOT/QUATOT` (preço médio real, invariante a qualquer convenção de escala) bateu
    com `PREULT/FATCOT` tanto para `FATCOT=1000` (`FNAM11`, 2024-01-02: 0,34/1000 ≈
    0,00034 ≈ VOLTOT/QUATOT) quanto para `FATCOT=10` (`SMLL11`, 2024-10-16: 2033/10 = 203,3
    = VOLTOT/QUATOT exato) — um valor de `FATCOT` não documentado no layout oficial (só
    `1` e `1000` são descritos), mas presente no dado real e seguindo a mesma regra.
    """

    __tablename__ = "cotahist_prices"
    __table_args__ = (
        UniqueConstraint("ticker", "trade_date", name="uq_cotahist_prices_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    trade_date: Mapped[Date] = mapped_column(Date, index=True)
    especi_raw: Mapped[str] = mapped_column(String)  # campo ESPECI cru, ex. "ON  EB  NM"
    fatcot: Mapped[int] = mapped_column(Integer)  # fator de escala aplicado (1, 10, 1000...)
    open: Mapped[float] = mapped_column(Float)  # normalizados (raw / fatcot)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    avg: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer)  # QUATOT — não precisa de normalização
    financial_volume: Mapped[float] = mapped_column(Float)  # VOLTOT (R$) — idem


class CorporateEventFlag(Base):
    """Evento societário **detectado** (tipo + data), derivado da transição do sufixo
    "ex-" em `ESPECI` — spec 14, Seção 5.3. Nunca tem magnitude (valor de provento, razão
    de bonificação/grupamento) porque a COTAHIST não carrega esse dado; existe para marcar
    onde a série de preço bruto tem uma quebra conhecida, não para permitir ajuste
    numérico.

    `is_level_break=True` só para sufixos que mudam quantidade de ações sem
    contrapartida em caixa (`EB`=bonificação, `EG`=grupamento — confirmado contra dado
    real: `BBAS3` caiu -50,57% em 2024-04-16, dia do `EB`, e o volume financeiro
    diário não mudou de ordem de grandeza, consistente com bonificação, não com queda de
    mercado). Sufixos de distribuição em caixa (`ED`/`EJ`/`ER`/`ES` e combinações) ficam
    `False` — o preço bruto nesses dias é um movimento de mercado real, não uma
    descontinuidade artificial (confirmado: `EJ` e `EDJ` reais do `BBAS3` em 2024
    mostraram variação de +0,65% e -3,53%, dentro do normal, nunca perto de -50%).

    `EX` aparece no dado real sem estar documentado na tabela oficial de `ESPECI` — o tipo
    exato fica como item aberto, registrado como não documentado em vez de adivinhado.
    **Medidas as 73 ocorrências reais em 2010-2026, população inteira, não amostra**:
    67,1% dentro de ±5% (ruído/distribuição em caixa normal), mas 4 casos (`CEBR6`/
    `CEBR3`/`CEBR5`, mesmo dia, e `VIVT3`) caem a -80,96%/-80,35%/-80,12%/-50,08% — quebra
    de nível real. Distribuição nem uniformemente ruído nem limpamente bimodal (20 casos
    intermediários entre 5% e 33%), mas com um vão real na cauda entre -22,54% e -50,08%
    sem nenhum caso no meio. Tratamento conservador adotado: `is_level_break` de `EX` é
    decidido **caso a caso** pelo retorno do próprio dia (`|retorno| >=
    EX_LEVEL_BREAK_THRESHOLD = 0,33`, dentro do vão real, não escolhido por conveniência),
    não um valor fixo para o sufixo — diferente de `EB`/`EG`, que são estruturais.
    """

    __tablename__ = "corporate_event_flags"
    __table_args__ = (
        UniqueConstraint(
            "ticker", "event_date", "ex_suffix", name="uq_corporate_event_flags_identity"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    event_date: Mapped[Date] = mapped_column(Date, index=True)
    ex_suffix: Mapped[str] = mapped_column(String)  # "EB" | "EJ" | "ED" | "EG" | "EX" | ...
    is_level_break: Mapped[bool] = mapped_column()
    source: Mapped[str] = mapped_column(String, default="ESPECI_TRANSITION")


class CnpjTickerMap(Base):
    """Terceira consulta as-of da Fase 1 — spec 14, Seção 5.4/5.5/5.6. Costura
    identidade (CNPJ, de onde vem o fundamento) com ticker (de onde vem o preço).

    **Identidade e vigência vêm de fontes diferentes, nunca confundir**: `cnpj` vem do
    FCA (`fonte='fca'`), da propagação por raiz de ticker (`fonte='raiz_propagacao'`) ou
    de reconciliação por nome histórico (`fonte='reconciliacao_nome'` — a fonte com menor
    confiança, usada só quando as outras duas não resolvem). `data_inicio_vigencia`/
    `data_fim_vigencia` vêm sempre da COTAHIST (primeira/última data de pregão do ticker,
    com tolerância de 180 dias sem pregão antes de fechar vigência) — nunca do FCA, cujos
    campos de data medem admissão da classe de ação, não vigência do código (achado da
    Seção 5.6, caso real: `Data_Inicio_Negociacao` do FCA para `COGN3` ficou em 2012 nos
    dois filings, quando o código real só passou a ser `COGN3` em 2019-10-11 — confirmado
    contra `COTAHIST_A2019.ZIP`). A COTAHIST sozinha nunca decide identidade — só fornece
    as bordas de um intervalo já rotulado por uma das três fontes acima.

    Append-only: `UniqueConstraint(ticker, data_inicio_vigencia)` — uma reatribuição ou
    troca de código fecha a vigência antiga (`data_fim_vigencia`) e abre uma linha nova,
    nunca sobrescreve.
    """

    __tablename__ = "cnpj_ticker_map"
    __table_args__ = (
        UniqueConstraint(
            "ticker", "data_inicio_vigencia", name="uq_cnpj_ticker_map_identity"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cnpj: Mapped[str] = mapped_column(String, index=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    data_inicio_vigencia: Mapped[Date] = mapped_column(Date, index=True)
    data_fim_vigencia: Mapped[Date | None] = mapped_column(Date, nullable=True, index=True)
    fonte: Mapped[str] = mapped_column(String)  # "fca" | "raiz_propagacao" | "reconciliacao_nome"
    data_coleta: Mapped[Date] = mapped_column(Date)


class UnresolvedTicker(Base):
    """Ticker que passou o filtro de liquidez (Seção 6) mas não resolveu para nenhum
    CNPJ — nem FCA, nem propagação por raiz, nem reconciliação por nome. Exclusão
    **contável**, nunca silenciosa (Seção 5.6/8: mesmo tratamento já usado para histórico
    insuficiente, dado faltante de fator e perda de liquidez) — é o que impede o
    survivorship de voltar pela porta dos fundos quando a identidade falha em vez da
    liquidez."""

    __tablename__ = "unresolved_tickers"
    __table_args__ = (
        UniqueConstraint("ticker", "checked_year", name="uq_unresolved_tickers_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    checked_year: Mapped[int] = mapped_column(Integer, index=True)
    reason: Mapped[str] = mapped_column(String)
