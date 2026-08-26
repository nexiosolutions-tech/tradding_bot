"""Motor de decisão point-in-time — spec 14, Seção 7.6.

Uma função só, chamada uma vez por data de decisão pelo backtest (Seção 9) e pelo motor
de carteira (Seção 8) — infraestrutura de produção, não utilitário de medição. Assume
que preço (`cotahist_ingestion`), identidade (`cnpj_ticker_map`) e fundamento
(`cvm_ingestion`) já foram ingeridos; nunca faz I/O de rede, nunca lê o relógio real —
mesma entrada, mesma saída, sempre.

Nunca reimplementa a composição de pesos: chama `compute_score_composto` (Seção 7.2)
diretamente. Antes deste módulo, cada data de decisão era materializada por script ad
hoc — nada garantia que dois deles calculassem o score da mesma forma. Com o driver como
única chamada, `compute_score_composto` deixa de ser semente testada isoladamente e
passa a ser a fonte única de verdade.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.acoes.fatores import (
    FactorInput,
    FactorResult,
    PesoFator,
    compute_demeaned_percentiles,
    compute_score_composto,
    divida_liquida_ebitda_raw,
    earnings_yield_raw,
    fator_divida_liquida_ebitda_aplicavel,
    get_divida_liquida_as_of,
    get_ebitda_as_of,
    get_eps_as_of,
    get_lucro_liquido_controladores_as_of,
    get_patrimonio_liquido_controladores_as_of,
    roe_raw,
)
from tradingbot.acoes.models import CotahistPrice, UniversoElegivel
from tradingbot.acoes.universo_elegivel import UniversoElegivelStats, build_universo_elegivel

FATOR_EARNINGS_YIELD = "earnings_yield"
FATOR_DIVIDA_LIQUIDA_EBITDA = "divida_liquida_ebitda"
FATOR_ROE = "roe"

PESOS_PADRAO = (
    PesoFator(FATOR_EARNINGS_YIELD, 1.0),
    PesoFator(FATOR_DIVIDA_LIQUIDA_EBITDA, 1.0),
    PesoFator(FATOR_ROE, 1.0),
)


def _preco_as_of(session: Session, ticker: str, data_decisao: date) -> float | None:
    """Fechamento mais recente com `trade_date <= data_decisao` — mesma fronteira
    inclusiva de todo o resto da spec."""
    stmt = (
        select(CotahistPrice.close)
        .where(CotahistPrice.ticker == ticker, CotahistPrice.trade_date <= data_decisao)
        .order_by(CotahistPrice.trade_date.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


@dataclass
class DecisaoEmpresa:
    ticker: str
    cnpj: str
    setor_ativ: str | None
    setor_b3: str | None
    subsetor_b3: str | None
    segmento_b3: str | None
    earnings_yield_percentil: float | None
    divida_liquida_ebitda_percentil: float | None
    roe_percentil: float | None
    score_composto: float | None
    tem_fator_real: bool


@dataclass
class DecisaoResultado:
    data_decisao: date
    universo_stats: UniversoElegivelStats
    empresas: list[DecisaoEmpresa]

    @property
    def n_score_computavel(self) -> int:
        """Conta empresa com **pelo menos um fator de dado real** (não imputado pela
        mediana), não "score composto não-nulo" — `compute_score_composto` quase sempre
        devolve um número, porque a imputação por mediana (Seção 7, `_preencher_
        faltantes`) preenche todo fator faltante antes de gerar percentil. A métrica
        que decide se um ranking é confiável (Seção 7.5, piso de N≥100) é sobre dado
        real, não sobre "um número saiu no fim"."""
        return sum(1 for e in self.empresas if e.tem_fator_real)


def _resultado_por_ticker(resultados: list[FactorResult]) -> dict[str, FactorResult]:
    return {r.ticker: r for r in resultados}


def build_decisao(
    session: Session,
    data_decisao: date,
    setor_by_cnpj: dict[str, str],
    *,
    pesos: tuple[PesoFator, ...] = PESOS_PADRAO,
    **kwargs_universo,
) -> DecisaoResultado:
    """Data de decisão entra, universo materializado + score composto por empresa sai.

    1. Materializa o universo elegível (`build_universo_elegivel`, Seção 6 —
       `kwargs_universo` repassa piso de liquidez/janela/histórico mínimo direto para
       lá, sem reimplementar nem duplicar default).
    2. Para cada empresa sobrevivente, computa os três fatores brutos (Seção 7.1-7.3),
       respeitando a matriz de aplicabilidade (dívida líquida/EBITDA nunca entra na
       lista de bancos — inaplicável é uma categoria diferente de faltante, nunca vira
       `None` para ser imputado por engano).
    3. Um `compute_demeaned_percentiles` por fator, sobre o universo inteiro que
       participa daquele fator.
    4. `compute_score_composto` por empresa — nunca reimplementado aqui.
    """
    universo_stats = build_universo_elegivel(session, data_decisao, setor_by_cnpj, **kwargs_universo)

    linhas = (
        session.execute(
            select(UniversoElegivel).where(UniversoElegivel.data_decisao == data_decisao)
        )
        .scalars()
        .all()
    )

    earnings_yield_inputs: list[FactorInput] = []
    divida_liquida_ebitda_inputs: list[FactorInput] = []
    roe_inputs: list[FactorInput] = []

    for linha in linhas:
        bucket = (linha.segmento_b3, linha.subsetor_b3, linha.setor_b3)

        preco = _preco_as_of(session, linha.ticker, data_decisao)
        eps = get_eps_as_of(session, linha.cnpj, linha.ticker, data_decisao)
        earnings_yield = (
            earnings_yield_raw(eps, preco) if eps is not None and preco else None
        )
        earnings_yield_inputs.append(FactorInput(linha.ticker, earnings_yield, *bucket))

        if fator_divida_liquida_ebitda_aplicavel(linha.subsetor_b3):
            ebitda = get_ebitda_as_of(session, linha.cnpj, data_decisao)
            divida_liquida = get_divida_liquida_as_of(session, linha.cnpj, data_decisao)
            dle = (
                divida_liquida_ebitda_raw(divida_liquida, ebitda)
                if divida_liquida is not None and ebitda is not None
                else None
            )
            divida_liquida_ebitda_inputs.append(FactorInput(linha.ticker, dle, *bucket))

        lucro = get_lucro_liquido_controladores_as_of(session, linha.cnpj, data_decisao)
        patrimonio = get_patrimonio_liquido_controladores_as_of(session, linha.cnpj, data_decisao)
        roe = roe_raw(lucro, patrimonio) if lucro is not None and patrimonio is not None else None
        roe_inputs.append(FactorInput(linha.ticker, roe, *bucket))

    earnings_yield_por_ticker = _resultado_por_ticker(compute_demeaned_percentiles(earnings_yield_inputs))
    divida_liquida_ebitda_por_ticker = (
        _resultado_por_ticker(compute_demeaned_percentiles(divida_liquida_ebitda_inputs))
        if divida_liquida_ebitda_inputs
        else {}
    )
    roe_por_ticker = _resultado_por_ticker(compute_demeaned_percentiles(roe_inputs))

    empresas: list[DecisaoEmpresa] = []
    for linha in linhas:
        ey_resultado = earnings_yield_por_ticker.get(linha.ticker)
        dle_resultado = divida_liquida_ebitda_por_ticker.get(linha.ticker)
        roe_resultado = roe_por_ticker.get(linha.ticker)

        percentis = {
            FATOR_EARNINGS_YIELD: ey_resultado.percentil if ey_resultado else None,
            FATOR_DIVIDA_LIQUIDA_EBITDA: dle_resultado.percentil if dle_resultado else None,
            FATOR_ROE: roe_resultado.percentil if roe_resultado else None,
        }
        score = compute_score_composto(percentis, list(pesos))

        tem_fator_real = any(
            resultado is not None and not resultado.imputado
            for resultado in (ey_resultado, dle_resultado, roe_resultado)
        )

        empresas.append(
            DecisaoEmpresa(
                ticker=linha.ticker,
                cnpj=linha.cnpj,
                setor_ativ=linha.setor_ativ,
                setor_b3=linha.setor_b3,
                subsetor_b3=linha.subsetor_b3,
                segmento_b3=linha.segmento_b3,
                earnings_yield_percentil=percentis[FATOR_EARNINGS_YIELD],
                divida_liquida_ebitda_percentil=percentis[FATOR_DIVIDA_LIQUIDA_EBITDA],
                roe_percentil=percentis[FATOR_ROE],
                score_composto=score,
                tem_fator_real=tem_fator_real,
            )
        )

    return DecisaoResultado(data_decisao=data_decisao, universo_stats=universo_stats, empresas=empresas)
