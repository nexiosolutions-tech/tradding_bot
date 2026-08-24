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

**Dado faltante vs. fator inaplicável — dois ramos diferentes, nunca confundidos.**
Inaplicável (ex. EV/EBITDA de banco) é decisão determinística por setor, vem de uma
matriz de aplicabilidade (Seção 7, ainda não implementada — earnings yield se aplica a
todo setor, não exercita este ramo). Faltante é uma empresa que deveria ter o dado e não
tem (não reportou, campo ausente) — aqui a regra declarada é imputação pela mediana do
grupo (não exclusão, que cria viés de seleção sistemático contra empresa de reporte mais
fraco) — mesma regra em backtest e produção, nunca implícita.
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

    stmt = select(CvmFinancialLineItem.vl_conta).where(
        CvmFinancialLineItem.cnpj_cia == cnpj,
        CvmFinancialLineItem.dt_refer == filing.dt_refer,
        CvmFinancialLineItem.versao == filing.versao,
        CvmFinancialLineItem.ordem_exerc == "ÚLTIMO",
        CvmFinancialLineItem.cd_conta == cd_conta,
    )
    return session.execute(stmt).scalar_one_or_none()


def earnings_yield_raw(eps: float, preco: float) -> float:
    """Lucro por ação / preço — o inverso do P/L. Deficitária (`eps < 0`) fica com yield
    negativo, corretamente no fundo do ranking; P/L bruto de deficitária ficaria negativo
    e apareceria como "a mais barata" num ranking ingênuo, sinal invertido."""
    return eps / preco


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
    """Winsoriza -> demeans pelo bucket mais fino com população mínima, subindo
    `segmento` -> `subsetor` -> `setor` -> universo inteiro -> percentil da série
    demeaned sobre o universo elegível inteiro (não sobre o bucket)."""
    preenchidos = _preencher_faltantes(items)
    imputados = {it.ticker for it, orig in zip(preenchidos, items) if orig.raw_value is None}

    valores_winsorizados = winsorize([it.raw_value for it in preenchidos])
    winsorizado_por_ticker = {
        it.ticker: v for it, v in zip(preenchidos, valores_winsorizados)
    }

    # agrupa por cada nivel de hierarquia, usando o valor ja winsorizado
    grupos: dict[tuple[str, str], list[float]] = {}
    for it in preenchidos:
        for nivel, chave in _bucket_hierarquia(it):
            grupos.setdefault((nivel, chave), []).append(winsorizado_por_ticker[it.ticker])

    media_universo = sum(winsorizado_por_ticker.values()) / len(winsorizado_por_ticker)

    demeaned_por_ticker: dict[str, float] = {}
    bucket_usado_por_ticker: dict[str, str] = {}
    for it in preenchidos:
        valor = winsorizado_por_ticker[it.ticker]
        for nivel, chave in _bucket_hierarquia(it):
            grupo = grupos[(nivel, chave)]
            if len(grupo) >= min_bucket_size:
                demeaned_por_ticker[it.ticker] = valor - (sum(grupo) / len(grupo))
                bucket_usado_por_ticker[it.ticker] = nivel
                break
        else:
            demeaned_por_ticker[it.ticker] = valor - media_universo
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
