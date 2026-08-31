"""Fatores — spec 14, Seção 7. Primeira camada de **decisão de modelagem** da Fase 2: as
Seções 5/6 verificaram dado contra a realidade (bate com a fonte?); aqui o rigor é outro —
a transformação tem justificativa econômica ou é mineração? Nenhum fator entra sem
justificativa registrada na spec.

Este módulo tem duas partes deliberadamente separadas:

1. **Mecânica genérica de normalização** (`winsorize`, `compute_demeaned_percentiles`) —
   reutilizável por qualquer fator futuro, não específica de earnings yield. Winsoriza as
   caudas antes de qualquer média (outlier em bucket de 3 empresas desloca a média e
   contamina as outras duas — rotina em fatores, não opcional com bucket pequeno). Depois
   demeans pela média do bucket setorial mais fino que ainda tem população mínima,
   subindo a hierarquia B3 (`segmento` → `subsetor` → `setor`) quando o nível mais fino
   é pequeno demais — a hierarquia que a Seção 6.2 já materializa é a ferramenta natural
   para isso. Sem nenhum nível com população mínima, cai no universo inteiro (sem
   neutralização setorial específica), nunca descarta a empresa.

2. **Earnings yield** (`get_eps_as_of`, `earnings_yield_raw`) — primeiro fator
   implementado ponta a ponta, família Valor. Lucro por ação, não P/L bruto: empresa
   deficitária tem earnings yield negativo e cai corretamente no fundo do ranking, sem
   tratamento especial (P/L bruto inverteria o sinal — erro clássico de fator de valor).
   Fonte verificada, não presumida: a DRE consolidada da CVM já reporta `CD_CONTA
   "3.99.01.01"`/`"3.99.01.02"` = Lucro Básico por Ação, separado por classe (ON/PN) —
   não precisa derivar via ações em circulação, que exigiria uma fonte de dado nova
   (capital social) não verificada nesta rodada.

3. **Dívida líquida/EBITDA** (`get_ebitda_as_of`, `get_divida_liquida_as_of`,
   `divida_liquida_ebitda_raw`) — segundo fator, família Saúde financeira, o primeiro a
   exercitar a matriz de aplicabilidade de verdade (`fator_divida_liquida_ebitda_
   aplicavel`) e o point-in-time de múltiplas demonstrações (DRE para EBIT, DFC para
   D&A, BP para dívida e caixa — três fontes, todas resolvidas pelo mesmo
   `get_latest_filing_as_of`, mesma `base` consolidada nas três). EBITDA não vem pronto
   da CVM como o EPS veio — é derivado, e a derivação escondia duas armadilhas reais
   (Seção 7.2): D&A não está na DRE (só na DFC, método indireto, posição não fixa dentro
   do grupo de reconciliação); e o mesmo `CD_CONTA` de EBIT (`"3.05"`) tem significado
   diferente em instituição financeira (lucro pré-imposto, não EBIT) mesmo sendo marcado
   `ST_CONTA_FIXA='S'` nas duas — por isso toda consulta que depende de `cd_conta`
   verifica `ds_conta` antes de aceitar o valor, nunca confia no código sozinho.

**Três categorias de ausência, nunca confundidas** — cada uma um ramo de código
diferente, porque misturá-las produz o mesmo tipo de erro silencioso que motivou o
earnings yield e a normalização com winsorização:

- **Inaplicável** (`fator_divida_liquida_ebitda_aplicavel` devolve `False`) — decisão
  determinística por subsetor B3, vem da matriz. Banco não entra no cálculo, ponto —
  não é ausência de dado, é o fator não fazer sentido econômico para aquele negócio.
- **Faltante** (`get_ebitda_as_of`/`get_divida_liquida_as_of` devolvem `None` por linha
  ausente ou ambígua) — a empresa deveria ter o dado e não tem (não reportou, campo
  ausente, ou mais de um candidato onde só um era esperado). Regra declarada:
  `compute_demeaned_percentiles` imputa pela mediana do universo, nunca exclui.
- **Indefinido** (`divida_liquida_ebitda_raw` devolve `None` quando `ebitda <= 0`) — o
  dado *existe*, mas o múltiplo não tem significado econômico ali (mesmo problema do P/L
  com lucro negativo, do lado do denominador). Mecanicamente tratado como faltante pela
  camada de normalização (imputação pela mediana), mas semanticamente distinto — vale a
  pena registrar por quê, não só o quê, para auditoria futura.

**Composto renormaliza pesos sobre fatores aplicáveis** (`compute_score_composto`) — sem
isso, a matriz criaria um viés setorial escondido na aritmética: banco com um fator a
menos (inaplicável) teria o score puxado para baixo só por contar menos parcelas, não por
desempenho pior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.acoes.models import CvmFinancialLineItem
from tradingbot.acoes.pointintime import get_latest_filing_as_of

MIN_BUCKET_SIZE = 3
WINSORIZE_LOWER_PCT = 0.01
WINSORIZE_UPPER_PCT = 0.99

# Lucro Básico por Ação, plano de contas padrão DFP DRE - CD_CONTA por classe de acao.
_CD_CONTA_EPS_BASICO = {"ON": "3.99.01.01", "PN": "3.99.01.02"}
_TICKER_SUFFIX_TO_CLASSE = {"3": "ON", "4": "PN"}


def _classe_da_acao(ticker: str) -> str | None:
    sufixo = ticker[-1]
    return _TICKER_SUFFIX_TO_CLASSE.get(sufixo)


def get_eps_as_of(session: Session, cnpj: str, ticker: str, data_decisao: date) -> float | None:
    """Lucro por ação básico, como conhecido em `data_decisao` — usa o último balanço
    público (`get_latest_filing_as_of`, mesma consulta da Seção 6.1) e busca o
    `CD_CONTA` correspondente à classe do ticker (`ON`/`PN`, pelo sufixo numérico).
    `None` se não houver filing visível, se a classe do ticker não for ON/PN (ex. UNIT,
    fora de escopo desta rodada), ou se o `CD_CONTA` não existir no filing — os três
    casos são "dado faltante", tratados no mesmo ramo pela camada de normalização."""
    filing = get_latest_filing_as_of(session, cnpj, "DFP", data_decisao)
    if filing is None:
        return None

    classe = _classe_da_acao(ticker)
    if classe is None:
        return None
    cd_conta = _CD_CONTA_EPS_BASICO[classe]

    stmt = select(CvmFinancialLineItem).where(
        CvmFinancialLineItem.cnpj_cia == cnpj,
        CvmFinancialLineItem.dt_refer == filing.dt_refer,
        CvmFinancialLineItem.versao == filing.versao,
        CvmFinancialLineItem.ordem_exerc == "ÚLTIMO",
        CvmFinancialLineItem.cd_conta == cd_conta,
    )
    linha = _unica_por_conteudo(session.execute(stmt).scalars().all())
    return linha.vl_conta if linha else None


EARNINGS_YIELD_IMPLAUSIVEL_LIMIAR = 10.0

# Limiar derivado da distribuição real, mesmo método que fechou o EX (Seção 5.3): toda
# a série 2015-2026 tem earnings yield com |razão| > 10 (1000%) em 11 pontos, e o vão
# entre eles e o resto da distribuição é real, não escolhido por conveniência — o maior
# salto entre valores consecutivos ordenados por módulo é de 3,52x, exatamente entre
# |23,93| (ainda plausível — companhia em distress real) e |6,80| (claramente
# plausível), contra saltos de 1,0-1,3x em todo o resto da cauda. Achado real (Seção
# 13, 2026-08-27): a interface expôs earnings yield de 25.067% para uma empresa real
# (EVEN3) — investigação encontrou **múltiplas causas distintas**, não uma só: valor
# bruto corrompido na própria fonte CVM (`AMAR3`, `MEAL3` — nenhuma correção de escala
# resolve, só exclusão), e erro de escala ~1000x num item por ação que não deveria
# escalar (`ITUB4`, `EVEN3`, `MOSI3` — confirmado cruzando `lucro_controladores/eps`
# contra o número de ações implícito nos outros anos da mesma empresa, que cai por
# ~1000x só nos anos contaminados). Com mais de uma causa, o limiar não é rede de
# segurança de uma correção única — é o que faz o trabalho, então fica conservador
# (nunca filtra ROE, que não tem vão limpo — distribuição contínua, distress real).


def earnings_yield_raw(eps: float, preco: float) -> float | None:
    """Lucro por ação / preço — o inverso do P/L. Deficitária (`eps < 0`) fica com yield
    negativo, corretamente no fundo do ranking; P/L bruto de deficitária ficaria negativo
    e apareceria como "a mais barata" num ranking ingênuo, sinal invertido.

    `None` (indefinido) quando `|resultado| > EARNINGS_YIELD_IMPLAUSIVEL_LIMIAR` — dado
    de EPS implausível na fonte (ver constante acima), nunca inventa correção de
    escala (achado real mostrou que nem toda causa é a mesma, e "dividir por 1000"
    quebraria os casos que já estavam certos)."""
    resultado = eps / preco
    if abs(resultado) > EARNINGS_YIELD_IMPLAUSIVEL_LIMIAR:
        return None
    return resultado


# ------------------------------------------------------------- divida liquida / EBITDA

# DRE, padrao empresas nao-financeiras: "Resultado Antes do Resultado Financeiro e dos
# Tributos" (EBIT). ST_CONTA_FIXA='S', mas achado real (Secao 7.2): o mesmo CD_CONTA em
# banco (Itau, real) e "Resultado Antes dos Tributos sobre o Lucro" (lucro pre-imposto,
# NAO EBIT) - instituicao financeira usa plano de contas DRE inteiramente diferente, fixo
# so DENTRO da propria variante. Nunca aceitar o valor sem checar DS_CONTA.
_CD_CONTA_EBIT = "3.05"
_DS_CONTA_EBIT_ESPERADO = "Resultado Antes do Resultado Financeiro e dos Tributos"

# DFC metodo indireto, grupo de reconciliacao do lucro liquido (6.01.01.*) - o codigo
# exato do D&A dentro desse grupo NAO e fixo (ST_CONTA_FIXA='N', achado real: Petrobras
# usa 6.01.01.04, outra empresa pode usar posicao diferente ou nao ter a linha) - busca
# por conteudo de DS_CONTA, nunca por CD_CONTA literal.
_CD_CONTA_DFC_RECONCILIACAO_PREFIXO = "6.01.01."
_DA_KEYWORDS = ("DEPRECIA", "AMORTIZ", "EXAUST")

_CD_CONTA_CAIXA_E_EQUIVALENTES = "1.01.01"
_CD_CONTA_DIVIDA_CIRCULANTE = "2.01.04"
_CD_CONTA_DIVIDA_NAO_CIRCULANTE = "2.02.01"

EBITDA_INDEFINIDO_LIMIAR = 0.0


def _extrair_eps(ticker: str, linhas: list[CvmFinancialLineItem]) -> float | None:
    """Mesma regra de `get_eps_as_of`, operando sobre linhas já em memória — parte da
    reescrita em lote (2026-08-29): a versão single-item busca `linhas` do banco por
    empresa; a versão em lote busca todas as empresas de uma vez (`pointintime.
    get_line_items_lote`) e chama este extrator para cada uma, sem voltar ao banco.
    Nunca filtra por `base` — mesmo comportamento de `get_eps_as_of`, que também não
    filtra (achado de que o EPS não distingue consolidado/individual nesta rodada)."""
    classe = _classe_da_acao(ticker)
    if classe is None:
        return None
    cd_conta = _CD_CONTA_EPS_BASICO[classe]
    candidatas = [linha for linha in linhas if linha.cd_conta == cd_conta]
    linha = _unica_por_conteudo(candidatas)
    return linha.vl_conta if linha else None


def _extrair_ebit(linhas: list[CvmFinancialLineItem], base: str = "con") -> float | None:
    """Mesma regra de `get_ebit_as_of` — ver docstring lá para a armadilha do `CD_CONTA`
    de banco. Operando sobre linhas já em memória (reescrita em lote, 2026-08-29)."""
    candidatas = [linha for linha in linhas if linha.base == base and linha.cd_conta == _CD_CONTA_EBIT]
    linha = _unica_por_conteudo(candidatas)
    if linha is None or linha.ds_conta.strip() != _DS_CONTA_EBIT_ESPERADO:
        return None
    return linha.vl_conta


def _extrair_da(linhas: list[CvmFinancialLineItem], base: str = "con") -> float | None:
    """Mesma regra de `get_depreciacao_amortizacao_as_of` — busca por palavra-chave em
    `DS_CONTA`, nunca por `CD_CONTA` fixo (posição não é fixa dentro do grupo de
    reconciliação, Seção 7.2). Operando sobre linhas já em memória (reescrita em lote,
    2026-08-29)."""
    candidatas = [
        linha for linha in linhas
        if linha.base == base
        and linha.cd_conta.startswith(_CD_CONTA_DFC_RECONCILIACAO_PREFIXO)
        and any(kw in linha.ds_conta.upper() for kw in _DA_KEYWORDS)
    ]
    linha = _unica_por_conteudo(candidatas)
    return linha.vl_conta if linha else None


def _extrair_divida_liquida(linhas: list[CvmFinancialLineItem], base: str = "con") -> float | None:
    """Mesma regra de `get_divida_liquida_as_of`. Operando sobre linhas já em memória
    (reescrita em lote, 2026-08-29)."""
    caixa = _unica_por_conteudo(
        [l for l in linhas if l.base == base and l.cd_conta == _CD_CONTA_CAIXA_E_EQUIVALENTES]
    )
    divida_circulante = _unica_por_conteudo(
        [l for l in linhas if l.base == base and l.cd_conta == _CD_CONTA_DIVIDA_CIRCULANTE]
    )
    divida_nao_circulante = _unica_por_conteudo(
        [l for l in linhas if l.base == base and l.cd_conta == _CD_CONTA_DIVIDA_NAO_CIRCULANTE]
    )
    if caixa is None or divida_circulante is None or divida_nao_circulante is None:
        return None
    return (divida_circulante.vl_conta + divida_nao_circulante.vl_conta) - caixa.vl_conta


def _extrair_lucro_liquido_controladores(linhas: list[CvmFinancialLineItem], base: str = "con") -> float | None:
    """Mesma regra de `get_lucro_liquido_controladores_as_of`. Operando sobre linhas já
    em memória (reescrita em lote, 2026-08-29)."""
    candidatas = [
        l for l in linhas
        if l.base == base and l.cd_conta.startswith("3.") and l.ds_conta == _DS_CONTA_LUCRO_LIQUIDO_CONTROLADORES
    ]
    linha = _unica_por_conteudo(candidatas)
    return linha.vl_conta if linha else None


def _extrair_patrimonio_liquido_controladores(linhas: list[CvmFinancialLineItem], base: str = "con") -> float | None:
    """Mesma regra de `get_patrimonio_liquido_controladores_as_of`. Operando sobre linhas
    já em memória (reescrita em lote, 2026-08-29)."""
    total = _unica_por_conteudo(
        [l for l in linhas if l.base == base and l.cd_conta.startswith("2.") and l.ds_conta == _DS_CONTA_PATRIMONIO_LIQUIDO_CONSOLIDADO]
    )
    nao_controladores = _unica_por_conteudo(
        [l for l in linhas if l.base == base and l.cd_conta.startswith("2.") and l.ds_conta == _DS_CONTA_PARTICIPACAO_NAO_CONTROLADORES]
    )
    if total is None or nao_controladores is None:
        return None
    return total.vl_conta - nao_controladores.vl_conta


def _unica_por_conteudo(linhas: list[CvmFinancialLineItem]) -> CvmFinancialLineItem | None:
    """Achado real (Seção 7.7): CVM às vezes repete a mesma linha idêntica várias vezes
    no arquivo bruto (2 empresas reais, FY2023, `CD_CONTA "3.99.01.01"` — mesmo
    `vl_conta`/`ds_conta` duplicado 2-3 vezes). Isso não é a mesma ambiguidade que já
    forçava `None` em todo o resto do módulo (candidatos com conteúdo *diferente*, onde
    adivinhar seria o erro) — é a mesma resposta repetida, então usar qualquer cópia dá
    o valor certo. Deduplica por `(vl_conta, ds_conta)`; só cai em `None` quando as
    cópias **divergem** de verdade."""
    if not linhas:
        return None
    distintas = {(l.vl_conta, l.ds_conta) for l in linhas}
    if len(distintas) != 1:
        return None
    return linhas[0]


def _linha_unica(session: Session, cnpj: str, filing, cd_conta: str, base: str = "con"):
    stmt = select(CvmFinancialLineItem).where(
        CvmFinancialLineItem.cnpj_cia == cnpj,
        CvmFinancialLineItem.dt_refer == filing.dt_refer,
        CvmFinancialLineItem.versao == filing.versao,
        CvmFinancialLineItem.ordem_exerc == "ÚLTIMO",
        CvmFinancialLineItem.base == base,
        CvmFinancialLineItem.cd_conta == cd_conta,
    )
    return _unica_por_conteudo(session.execute(stmt).scalars().all())


def get_ebit_as_of(session: Session, cnpj: str, data_decisao: date, base: str = "con") -> float | None:
    """EBIT como conhecido em `data_decisao`. `None` se não houver filing visível, se o
    `CD_CONTA` não existir, **ou se existir mas `DS_CONTA` não bater com o esperado** —
    o caso real de banco, onde o mesmo código numérico é outra conta inteiramente."""
    filing = get_latest_filing_as_of(session, cnpj, "DFP", data_decisao)
    if filing is None:
        return None
    linha = _linha_unica(session, cnpj, filing, _CD_CONTA_EBIT, base)
    if linha is None or linha.ds_conta.strip() != _DS_CONTA_EBIT_ESPERADO:
        return None
    return linha.vl_conta


def get_depreciacao_amortizacao_as_of(session: Session, cnpj: str, data_decisao: date, base: str = "con") -> float | None:
    """D&A do exercício, via reconciliação da DFC método indireto (não está na DRE —
    verificado contra dado real, Seção 7.2). `None` se a linha não existir (D&A ausente
    ≠ D&A zero — somar zero produziria um EBITDA falso com cara de válido) ou se mais de
    uma linha do grupo casar com as palavras-chave (ambíguo, mesma disciplina de nunca
    adivinhar entre candidatos)."""
    filing = get_latest_filing_as_of(session, cnpj, "DFP", data_decisao)
    if filing is None:
        return None

    stmt = select(CvmFinancialLineItem).where(
        CvmFinancialLineItem.cnpj_cia == cnpj,
        CvmFinancialLineItem.dt_refer == filing.dt_refer,
        CvmFinancialLineItem.versao == filing.versao,
        CvmFinancialLineItem.ordem_exerc == "ÚLTIMO",
        CvmFinancialLineItem.base == base,
        CvmFinancialLineItem.cd_conta.startswith(_CD_CONTA_DFC_RECONCILIACAO_PREFIXO),
    )
    candidatos = [
        row for row in session.execute(stmt).scalars().all()
        if any(kw in row.ds_conta.upper() for kw in _DA_KEYWORDS)
    ]
    linha = _unica_por_conteudo(candidatos)
    return linha.vl_conta if linha else None


def get_ebitda_as_of(session: Session, cnpj: str, data_decisao: date, base: str = "con") -> float | None:
    """EBIT + D&A, mesma `base` (consolidado por padrão) nas duas consultas — misturar
    consolidado com individual produziria um EBITDA sem sentido econômico (Seção 7.2).
    `None` se qualquer uma das duas partes for `None` (nunca soma parcial)."""
    ebit = get_ebit_as_of(session, cnpj, data_decisao, base)
    da = get_depreciacao_amortizacao_as_of(session, cnpj, data_decisao, base)
    if ebit is None or da is None:
        return None
    return ebit + da


def get_divida_liquida_as_of(session: Session, cnpj: str, data_decisao: date, base: str = "con") -> float | None:
    """Dívida bruta (empréstimos e financiamentos circulante + não circulante, BPP) menos
    caixa e equivalentes (BPA) — as três linhas do balanço patrimonial na data de
    decisão. `None` se qualquer uma faltar."""
    filing = get_latest_filing_as_of(session, cnpj, "DFP", data_decisao)
    if filing is None:
        return None

    caixa = _linha_unica(session, cnpj, filing, _CD_CONTA_CAIXA_E_EQUIVALENTES, base)
    divida_circulante = _linha_unica(session, cnpj, filing, _CD_CONTA_DIVIDA_CIRCULANTE, base)
    divida_nao_circulante = _linha_unica(session, cnpj, filing, _CD_CONTA_DIVIDA_NAO_CIRCULANTE, base)
    if caixa is None or divida_circulante is None or divida_nao_circulante is None:
        return None
    return (divida_circulante.vl_conta + divida_nao_circulante.vl_conta) - caixa.vl_conta


def divida_liquida_ebitda_raw(divida_liquida: float, ebitda: float) -> float | None:
    """`None` (indefinido) quando `ebitda <= 0` — terceira categoria, distinta de
    "faltante" (a empresa deveria ter o dado e não tem) e de "inaplicável" (o setor não
    comporta o fator, matriz abaixo). Aqui o dado *existe*, mas o múltiplo não tem
    significado econômico: EBITDA perto de zero faz o múltiplo explodir, EBITDA negativo
    inverteria o sinal (empresa endividada pareceria ótima) — o mesmo problema do P/L com
    lucro negativo que levou ao earnings yield, agora do lado do denominador."""
    if ebitda <= EBITDA_INDEFINIDO_LIMIAR:
        return None
    return divida_liquida / ebitda


# ------------------------------------------------------- matriz de aplicabilidade

# Por subsetor B3 (Seção 6.2), não por "setor financeiro sim/não" binário — o setor
# "Financeiro" da B3 não é homogêneo (banco, seguradora, bolsa, holding financeira são
# casos distintos). Escopo desta rodada: só o subsetor verificado contra dado real
# (bancos, Seção 7.2 — o próprio plano de contas DRE de banco não tem a conta de EBIT).
# Seguradoras/bolsa/holdings financeiras ficam pendentes até serem verificadas.
DIVIDA_LIQUIDA_EBITDA_SUBSETORES_INAPLICAVEIS = {
    "Intermediários Financeiros",  # justificativa: alavancagem é o próprio negócio do
    # banco (insumo de intermediação financeira), não um risco a medir — dívida líquida
    # não significa o mesmo que numa industrial. Confirmado estruturalmente: o plano de
    # contas da DRE de instituição financeira nem tem uma conta equivalente a EBIT
    # (Seção 7.2, achado real do CD_CONTA "3.05").
}


def fator_divida_liquida_ebitda_aplicavel(subsetor_b3: str | None) -> bool:
    """`False` só para subsetor explicitamente listado como inaplicável, com
    justificativa econômica registrada. Subsetor desconhecido (`None`, sem cobertura B3
    — Seção 6.2) não é tratado como inaplicável, que seria uma decisão determinística
    não tomada — fica aplicável por padrão, e a ausência de dado financeiro (se houver)
    aparece como faltante, não como decisão de matriz."""
    if subsetor_b3 is None:
        return True
    return subsetor_b3 not in DIVIDA_LIQUIDA_EBITDA_SUBSETORES_INAPLICAVEIS


# ------------------------------------------------------------------ score composto

@dataclass
class PesoFator:
    nome: str
    peso: float


def compute_score_composto(
    percentis_por_fator: dict[str, float | None], pesos: list[PesoFator]
) -> float | None:
    """Média ponderada dos percentis de fator, **renormalizando os pesos sobre os
    fatores aplicáveis** (percentil presente), não sobre um conjunto fixo — o mecanismo
    que a matriz de aplicabilidade precisa para não virar viés setorial escondido na
    aritmética. Sem renormalização, um banco com um fator a menos (`None` por
    inaplicabilidade) teria seu score puxado para baixo só por contar menos parcelas,
    não por desempenho pior — o mesmo banco, pontuando igual nos fatores que se aplicam
    a ele, ficaria com score menor que uma industrial só pela estrutura da matriz.
    `None` se nenhum fator for aplicável (situação degenerada, não esperada em produção)."""
    aplicaveis = [
        (p.peso, percentis_por_fator[p.nome])
        for p in pesos
        if percentis_por_fator.get(p.nome) is not None
    ]
    if not aplicaveis:
        return None
    soma_pesos = sum(peso for peso, _ in aplicaveis)
    return sum(peso * percentil for peso, percentil in aplicaveis) / soma_pesos


# ------------------------------------------------------------------------------- ROE

# Achado real (Seção 7.3, mesmo padrão do "3.05" — Seção 7.2): o CD_CONTA do lucro
# atribuído aos controladores muda de posição por empresa ("3.09.01" para banco,
# "3.11.01" para a Petrobras) dependendo de quantas linhas precedem na DRE de cada uma —
# mas o DS_CONTA é idêntico nas duas variantes de plano de contas. Busca sempre por
# DS_CONTA dentro do prefixo da demonstração certa ("3." = DRE, "2." = BPP), nunca por
# código.
_DS_CONTA_LUCRO_LIQUIDO_CONTROLADORES = "Atribuído a Sócios da Empresa Controladora"
_DS_CONTA_PATRIMONIO_LIQUIDO_CONSOLIDADO = "Patrimônio Líquido Consolidado"
_DS_CONTA_PARTICIPACAO_NAO_CONTROLADORES = "Participação dos Acionistas Não Controladores"

PATRIMONIO_INDEFINIDO_LIMIAR = 0.0


def _linha_por_ds_conta(session: Session, cnpj: str, filing, prefixo_cd_conta: str, ds_conta_esperado: str, base: str = "con"):
    stmt = select(CvmFinancialLineItem).where(
        CvmFinancialLineItem.cnpj_cia == cnpj,
        CvmFinancialLineItem.dt_refer == filing.dt_refer,
        CvmFinancialLineItem.versao == filing.versao,
        CvmFinancialLineItem.ordem_exerc == "ÚLTIMO",
        CvmFinancialLineItem.base == base,
        CvmFinancialLineItem.cd_conta.startswith(prefixo_cd_conta),
        CvmFinancialLineItem.ds_conta == ds_conta_esperado,
    )
    return _unica_por_conteudo(session.execute(stmt).scalars().all())


def get_lucro_liquido_controladores_as_of(session: Session, cnpj: str, data_decisao: date, base: str = "con") -> float | None:
    """Lucro líquido **atribuível aos controladores** — não o consolidado com
    participação de minoritários, que infla o numerador em relação ao patrimônio dos
    controladores (denominador). Busca por `DS_CONTA` dentro do prefixo `"3."` (DRE);
    `None` se a linha não existir."""
    filing = get_latest_filing_as_of(session, cnpj, "DFP", data_decisao)
    if filing is None:
        return None
    linha = _linha_por_ds_conta(session, cnpj, filing, "3.", _DS_CONTA_LUCRO_LIQUIDO_CONTROLADORES, base)
    return linha.vl_conta if linha else None


def get_patrimonio_liquido_controladores_as_of(session: Session, cnpj: str, data_decisao: date, base: str = "con") -> float | None:
    """Patrimônio líquido consolidado menos participação de acionistas não
    controladores — consistente com o numerador (lucro dos controladores). `None` se
    qualquer uma das duas linhas faltar (nunca assume participação de minoritários
    zero por ausência — faltante ≠ zero, mesma disciplina do D&A na Seção 7.2)."""
    filing = get_latest_filing_as_of(session, cnpj, "DFP", data_decisao)
    if filing is None:
        return None
    total = _linha_por_ds_conta(session, cnpj, filing, "2.", _DS_CONTA_PATRIMONIO_LIQUIDO_CONSOLIDADO, base)
    nao_controladores = _linha_por_ds_conta(session, cnpj, filing, "2.", _DS_CONTA_PARTICIPACAO_NAO_CONTROLADORES, base)
    if total is None or nao_controladores is None:
        return None
    return total.vl_conta - nao_controladores.vl_conta


def roe_raw(lucro_liquido_controladores: float, patrimonio_liquido_controladores: float) -> float | None:
    """`None` (indefinido) quando `patrimônio_líquido <= 0` — armadilha mais traiçoeira
    que a de `EBITDA <= 0` (Seção 7.2): empresa com prejuízo acumulado grande pode ter
    patrimônio líquido negativo, e aí o ROE inverte de forma perversa — prejuízo dividido
    por patrimônio negativo dá ROE **positivo**, empresa em situação terminal aparecendo
    no topo do ranking de qualidade. Confirma que a categoria "indefinido" generaliza:
    segundo gatilho independente (patrimônio, não EBITDA), mesmo tratamento mecânico
    (`None`, imputado pela mediana do universo), semanticamente distinto e registrado."""
    if patrimonio_liquido_controladores <= PATRIMONIO_INDEFINIDO_LIMIAR:
        return None
    return lucro_liquido_controladores / patrimonio_liquido_controladores


def pearson_correlation(xs: list[float], ys: list[float]) -> float:
    """Correlação de Pearson entre duas séries — usada para medir ortogonalidade entre
    fatores (Seção 7.3): se dois fatores rankeiam o universo de forma muito parecida,
    um deles adiciona pouca informação ao score composto. Implementação direta, sem
    dependência nova — a mesma disciplina de manter o módulo sem `numpy`/`scipy`."""
    n = len(xs)
    media_x = sum(xs) / n
    media_y = sum(ys) / n
    covariancia = sum((x - media_x) * (y - media_y) for x, y in zip(xs, ys))
    desvio_x = sum((x - media_x) ** 2 for x in xs) ** 0.5
    desvio_y = sum((y - media_y) ** 2 for y in ys) ** 0.5
    return covariancia / (desvio_x * desvio_y)


def winsorize(values: list[float], lower_pct: float = WINSORIZE_LOWER_PCT, upper_pct: float = WINSORIZE_UPPER_PCT) -> list[float]:
    """Corta as caudas nos percentis `lower_pct`/`upper_pct` antes de qualquer média
    setorial — outlier num bucket de 3 desloca a média e contamina as outras duas.

    Índice por arredondamento (`round`), não truncamento (`int`) — com `int`, `n=3` e
    `upper_pct=0.99` mapeia para o índice do meio (`int(0.99*2)=1`), não o máximo
    (`round(0.99*2)=2`), clipando incorretamente o maior valor de uma amostra pequena.
    Com `round`, amostra pequena (o caso comum na B3, Seção 6.2) não perde nada aos
    percentis 1/99 por construção — só corta cauda quando a amostra é grande o
    suficiente para o percentil não colapsar no extremo, comportamento correto."""
    if len(values) < 2:
        return list(values)
    ordenados = sorted(values)
    n = len(ordenados)
    idx_lower = min(max(round(lower_pct * (n - 1)), 0), n - 1)
    idx_upper = min(max(round(upper_pct * (n - 1)), 0), n - 1)
    piso, teto = ordenados[idx_lower], ordenados[idx_upper]
    return [max(piso, min(teto, v)) for v in values]


@dataclass
class FactorInput:
    ticker: str
    raw_value: float | None  # None = dado faltante (imputado pela mediana do grupo)
    segmento: str | None
    subsetor: str | None
    setor: str | None


@dataclass
class FactorResult:
    ticker: str
    raw_value: float
    bucket_usado: str  # "segmento" | "subsetor" | "setor" | "universo"
    demeaned: float
    percentil: float
    imputado: bool


def _preencher_faltantes(items: list[FactorInput]) -> list[FactorInput]:
    """Dado faltante -> mediana dos valores presentes no universo inteiro. Regra
    declarada e única (não por bucket, porque o bucket de uma empresa com dado faltante
    pode ser pequeno demais para ter mediana própria confiável — a mesma razão que motiva
    a hierarquia de fallback abaixo)."""
    presentes = [it.raw_value for it in items if it.raw_value is not None]
    if not presentes:
        return items
    mediana_universo = median(presentes)
    resultado = []
    for it in items:
        if it.raw_value is None:
            resultado.append(FactorInput(it.ticker, mediana_universo, it.segmento, it.subsetor, it.setor))
        else:
            resultado.append(it)
    return resultado


def _bucket_hierarquia(item: FactorInput) -> list[tuple[str, str]]:
    niveis = []
    if item.segmento:
        niveis.append(("segmento", item.segmento))
    if item.subsetor:
        niveis.append(("subsetor", item.subsetor))
    if item.setor:
        niveis.append(("setor", item.setor))
    return niveis


def compute_demeaned_percentiles(
    items: list[FactorInput],
    min_bucket_size: int = MIN_BUCKET_SIZE,
) -> list[FactorResult]:
    """Winsoriza -> demeans pelo bucket mais fino com população mínima **de dado real**,
    subindo `segmento` -> `subsetor` -> `setor` -> universo inteiro -> percentil da
    série demeaned sobre o universo elegível inteiro (não sobre o bucket).

    **Bucket (população e média) usa só valores reais, nunca imputados** — achado real
    (Seção 7.5): setor com alta incidência de dado faltante (bancos, no caso da
    limitação de versão retificada) pode ter a maioria dos membros imputados pela
    mediana do universo. Se a população/média do bucket contasse os imputados, a média
    "do setor" ficaria diluída em direção à mediana do universo inteiro — não reflete o
    setor real, e desloca o demeaned de *todas* as empresas do bucket, inclusive as com
    dado real. Um bucket com poucas empresas reais sobe a hierarquia mesmo que a
    contagem total (real + imputada) pareça suficiente."""
    preenchidos = _preencher_faltantes(items)
    imputados = {it.ticker for it, orig in zip(preenchidos, items) if orig.raw_value is None}

    valores_winsorizados = winsorize([it.raw_value for it in preenchidos])
    winsorizado_por_ticker = {
        it.ticker: v for it, v in zip(preenchidos, valores_winsorizados)
    }

    # agrupa por cada nivel de hierarquia usando so tickers com dado real
    grupos_reais: dict[tuple[str, str], list[float]] = {}
    for it in preenchidos:
        if it.ticker in imputados:
            continue
        for nivel, chave in _bucket_hierarquia(it):
            grupos_reais.setdefault((nivel, chave), []).append(winsorizado_por_ticker[it.ticker])

    valores_reais_winsorizados = [winsorizado_por_ticker[it.ticker] for it in preenchidos if it.ticker not in imputados]
    media_universo_real = (
        sum(valores_reais_winsorizados) / len(valores_reais_winsorizados)
        if valores_reais_winsorizados
        else sum(winsorizado_por_ticker.values()) / len(winsorizado_por_ticker)
    )

    demeaned_por_ticker: dict[str, float] = {}
    bucket_usado_por_ticker: dict[str, str] = {}
    for it in preenchidos:
        valor = winsorizado_por_ticker[it.ticker]
        for nivel, chave in _bucket_hierarquia(it):
            grupo = grupos_reais.get((nivel, chave), [])
            if len(grupo) >= min_bucket_size:
                demeaned_por_ticker[it.ticker] = valor - (sum(grupo) / len(grupo))
                bucket_usado_por_ticker[it.ticker] = nivel
                break
        else:
            demeaned_por_ticker[it.ticker] = valor - media_universo_real
            bucket_usado_por_ticker[it.ticker] = "universo"

    demeaned_ordenados = sorted(demeaned_por_ticker.values())
    n = len(demeaned_ordenados)

    def _percentil(valor: float) -> float:
        menores = sum(1 for v in demeaned_ordenados if v < valor)
        iguais = sum(1 for v in demeaned_ordenados if v == valor)
        return (menores + 0.5 * iguais) / n * 100

    return [
        FactorResult(
            ticker=it.ticker,
            raw_value=winsorizado_por_ticker[it.ticker],
            bucket_usado=bucket_usado_por_ticker[it.ticker],
            demeaned=demeaned_por_ticker[it.ticker],
            percentil=_percentil(demeaned_por_ticker[it.ticker]),
            imputado=it.ticker in imputados,
        )
        for it in preenchidos
    ]
