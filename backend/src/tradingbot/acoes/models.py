"""Índice mestre de filings da CVM — spec 14, Seção 5.1/5.2.

`DT_RECEB` (data_publicacao) só existe no arquivo-índice, não nos arquivos de item
financeiro — toda linha de fundamento futura faz join com esta tabela por
`(cnpj_cia, dt_refer, versao, categ_doc)` para herdar a data de publicação real.
"""

from __future__ import annotations

from sqlalchemy import Date, Float, Index, Integer, String, UniqueConstraint
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
    equivalentes — DRE, DFC, BPA, BPP, cada demonstração com seu próprio namespace de
    `cd_conta` pelo padrão CVM: `1.x`=BPA, `2.x`=BPP, `3.x`=DRE, `6.x`=DFC — não colidem
    entre si, então uma linha de qualquer demonstração cabe na mesma tabela). **Escopo:
    só o suficiente para os contratos point-in-time já provados (Seção 5.2) e os fatores
    já implementados (Seção 7)** — não a ingestão genérica de todo tipo de demonstração
    para toda empresa, que fica para quando o resto do fundamento (Fase 2) for
    construído.

    `ordem_exerc` é o campo que a Seção 5.1 identificou como armadilha: cada filing traz
    o exercício atual (`ÚLTIMO`) e o comparativo do ano anterior (`PENÚLTIMO`) na mesma
    linha de dado, possivelmente com valor reapresentado. Só `ÚLTIMO` é fato point-in-time
    primário — `PENÚLTIMO` nunca é fonte de fator, existe só para detecção de
    reapresentação (não implementada nesta rodada).

    `base` (`"con"` consolidado | `"ind"` individual) é convenção fixa, não escolha por
    fator — consolidado é o padrão de mercado. Achado da Seção 7.2: misturar EBIT
    consolidado com D&A individual (ou vice-versa) produziria um EBITDA sem sentido
    econômico, silenciosamente — este campo existe para que a consulta de cada fator
    filtre pela mesma base sempre, por construção, nunca por confiança na disciplina de
    quem ingeriu.

    `ST_CONTA_FIXA='S'` no arquivo real **não garante o mesmo significado entre planos de
    contas diferentes** — achado real (Seção 7.2): `CD_CONTA "3.05"` é `ST_CONTA_FIXA='S'`
    tanto para Petrobras (`"Resultado Antes do Resultado Financeiro e dos Tributos"`,
    EBIT) quanto para Itaú (`"Resultado Antes dos Tributos sobre o Lucro"`, lucro
    pré-imposto) — instituição financeira usa um plano de contas DRE inteiramente
    diferente, fixo *dentro* da própria variante, não *entre* variantes. Toda consulta de
    fator que depende de `cd_conta` verifica `ds_conta` antes de aceitar o valor.

    **Índice composto `(cnpj_cia, dt_refer, versao)`** (spec 14, Seção 6.2/10) — toda
    consulta de fator em `fatores.py` filtra pelas três colunas juntas (mais
    `ordem_exerc`/`cd_conta`), nunca por uma isolada; os índices de coluna única já
    existentes obrigam o SQLite a escanear ou fazer merge de três índices por consulta,
    em vez de um lookup composto direto — relevante na escala do backtest completo
    (~130 datas de decisão × universo elegível de cada data).
    """

    __tablename__ = "cvm_financial_line_items"
    __table_args__ = (
        Index("ix_cvm_financial_line_items_as_of", "cnpj_cia", "dt_refer", "versao"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cnpj_cia: Mapped[str] = mapped_column(String, index=True)
    dt_refer: Mapped[Date] = mapped_column(Date, index=True)
    versao: Mapped[int] = mapped_column(Integer)
    ordem_exerc: Mapped[str] = mapped_column(String)  # "ÚLTIMO" | "PENÚLTIMO"
    base: Mapped[str] = mapped_column(String, default="con")  # "con" | "ind"
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


class UniversoElegivel(Base):
    """Universo elegível materializado por data de decisão — spec 14, Seção 6. Primeiro
    artefato que junta as três fundações point-in-time (identidade via `cnpj_ticker_map`,
    preço via `CotahistPrice`, publicação via `CvmFiling`) numa única data.

    Materializado, nunca recalculado retroativamente (mesmo princípio da janela fixa do
    bot): uma vez gravado para `(data_decisao, ticker)`, o registro não muda mesmo que a
    lógica do filtro mude depois — reprodutibilidade exige que o universo de uma data
    passada continue sendo o que foi calculado naquele momento. `UniqueConstraint` é a
    garantia estrutural, não uma checagem de aplicação.

    **Dois setores lado a lado, de propósito.** `setor_ativ` (CVM, granular, cobertura
    de 100% sobre empresa com CNPJ resolvido) e `setor_b3`/`subsetor_b3`/`segmento_b3`
    (B3, taxonomia de produção, só cobre empresa listada hoje — Seção 6.2) — a Seção 7
    decide qual usar e como cair de um para o outro quando o B3 não cobrir; a Seção 6 só
    materializa o que é conhecido de cada fonte, nunca escolhe por ela.
    """

    __tablename__ = "universo_elegivel"
    __table_args__ = (
        UniqueConstraint("data_decisao", "ticker", name="uq_universo_elegivel_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data_decisao: Mapped[Date] = mapped_column(Date, index=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    cnpj: Mapped[str] = mapped_column(String, index=True)
    setor_ativ: Mapped[str | None] = mapped_column(String, nullable=True)
    setor_b3: Mapped[str | None] = mapped_column(String, nullable=True)
    subsetor_b3: Mapped[str | None] = mapped_column(String, nullable=True)
    segmento_b3: Mapped[str | None] = mapped_column(String, nullable=True)
    volume_mediano: Mapped[float] = mapped_column(Float)


class UniversoExclusao(Base):
    """Quem ficou de fora do universo elegível numa data de decisão, e por quê — tão
    parte do artefato da Seção 6 quanto `UniversoElegivel`. Exclusão sempre **contável**,
    nunca silenciosa (mesmo mecanismo já usado em `UnresolvedTicker` e em toda a spec):
    é o que prova, meses depois, que o survivorship está controlado.

    `motivo` segue a ordem de precedência explícita de `universo_elegivel.py`
    (`iliquido` → `classe_secundaria` → `identidade_nao_resolvida` →
    `recuperacao_judicial` → `historico_insuficiente`) — um ticker só chega a um motivo
    posterior se sobreviveu a todos os anteriores, então nunca há ambiguidade sobre qual
    motivo registrar quando mais de um se aplicaria.
    """

    __tablename__ = "universo_exclusao"
    __table_args__ = (
        UniqueConstraint("data_decisao", "ticker", name="uq_universo_exclusao_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data_decisao: Mapped[Date] = mapped_column(Date, index=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    motivo: Mapped[str] = mapped_column(String)


class B3IndustryClassification(Base):
    """Classificação setorial real da B3 (`setor econômico / subsetor / segmento`,
    endpoint `GetDetail` do `listedCompaniesProxy`) — spec 14, Seção 6.1/13. Chave de
    junção é o **CNPJ diretamente** (vem no próprio payload), não precisa passar por
    `cnpj_ticker_map`.

    **Atributo quase-estático, não point-in-time real**: a fonte só cobre empresas
    listadas *hoje* — confirmado empiricamente consultando o `codeCVM` antigo do Itaú
    (pré-reestruturação, cancelado) e o Banco Cruzeiro do Sul (falido, deslistado), ambos
    devolvendo payload vazio, contra o `codeCVM` atual do Itaú, que devolve classificação
    completa. Empresa deslistada antes da data de coleta não tem classificação B3
    disponível por este caminho — cai em exclusão contável ou fallback para `SETOR_ATIV`
    da CVM (Seção 6), nunca em adivinhação. Reclassificação setorial ao longo do tempo
    (setor de hoje aplicado a uma decisão histórica) é vazamento de baixo impacto,
    aceito e declarado, não escondido — mesmo tratamento dado pelo `data_coleta` já usado
    em `CnpjTickerMap`.
    """

    __tablename__ = "b3_industry_classification"
    __table_args__ = (
        UniqueConstraint("cnpj", "data_coleta", name="uq_b3_industry_classification_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cnpj: Mapped[str] = mapped_column(String, index=True)
    code_cvm: Mapped[str] = mapped_column(String)
    setor: Mapped[str] = mapped_column(String)
    subsetor: Mapped[str] = mapped_column(String)
    segmento: Mapped[str] = mapped_column(String)
    data_coleta: Mapped[Date] = mapped_column(Date, index=True)


class IpcaIndice(Base):
    """Número-índice IPCA encadeado a partir da variação mensal — spec 14, Seção 6.3.
    Existe para deflacionar o piso de liquidez (nominal, Seção 6.1) ao longo de uma
    série que atravessa mais de uma década de inflação acumulada — sem isso, o piso
    afrouxa sozinho conforme o tempo passa, sem nenhuma decisão de desenho pedindo isso.

    `data_referencia` é sempre o primeiro dia do mês (convenção do BCB SGS 433). Base
    100 no primeiro mês da série ingerida — arbitrária, cancela na razão usada por
    `deflacionar_piso`, nunca comparada em valor absoluto fora deste módulo.
    """

    __tablename__ = "ipca_indice"
    __table_args__ = (
        UniqueConstraint("data_referencia", name="uq_ipca_indice_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data_referencia: Mapped[Date] = mapped_column(Date, index=True)
    numero_indice: Mapped[float] = mapped_column(Float)


class CdiTaxa(Base):
    """Taxa CDI diária — spec 14, Seção 9 (benchmark 4: custo de oportunidade real).

    Fonte: Banco Central — SGS, série 12 (CDI, taxa diária, % ao dia) — mesma fonte já
    declarada para IPCA/Selic/câmbio (Seção 4.3). Guardada como taxa diária bruta, não
    como número-índice — `cdi.py` encadeia a partir daqui sob demanda, para o intervalo
    exato de cada curva de equity simulada, em vez de fixar uma base arbitrária aqui.
    """

    __tablename__ = "cdi_taxa"
    __table_args__ = (
        UniqueConstraint("data_referencia", name="uq_cdi_taxa_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data_referencia: Mapped[Date] = mapped_column(Date, index=True)
    taxa_diaria_pct: Mapped[float] = mapped_column(Float)
