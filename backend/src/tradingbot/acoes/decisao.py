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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradingbot.acoes.fatores import (
    FactorInput,
    FactorResult,
    PesoFator,
    _extrair_da,
    _extrair_divida_liquida,
    _extrair_ebit,
    _extrair_eps,
    _extrair_lucro_liquido_controladores,
    _extrair_patrimonio_liquido_controladores,
    compute_demeaned_percentiles,
    compute_score_composto,
    divida_liquida_ebitda_raw,
    earnings_yield_raw,
    fator_divida_liquida_ebitda_aplicavel,
    roe_raw,
)
from tradingbot.acoes.models import CotahistPrice, UniversoElegivel
from tradingbot.acoes.pointintime import get_latest_filing_as_of_lote, get_line_items_lote
from tradingbot.acoes.universo_elegivel import UniversoElegivelStats, build_universo_elegivel

FATOR_EARNINGS_YIELD = "earnings_yield"
FATOR_DIVIDA_LIQUIDA_EBITDA = "divida_liquida_ebitda"
FATOR_ROE = "roe"

PESOS_PADRAO = (
    PesoFator(FATOR_EARNINGS_YIELD, 1.0),
    PesoFator(FATOR_DIVIDA_LIQUIDA_EBITDA, 1.0),
    PesoFator(FATOR_ROE, 1.0),
)


def preco_as_of(session: Session, ticker: str, data_decisao: date) -> float | None:
    """Fechamento mais recente com `trade_date <= data_decisao` — mesma fronteira
    inclusiva de todo o resto da spec. Pública (não só uso interno de `build_decisao`)
    porque `backtest.py` (Seção 9) precisa da mesma consulta point-in-time para marcar
    posições a mercado mês a mês — nunca reimplementada lá.

    **Segura para avaliação point-in-time (uma razão numa única data — earnings yield,
    por exemplo), nunca para calcular retorno entre duas datas sem checar
    `backtest.tem_quebra_de_nivel` primeiro.** `CotahistPrice.close` é bruto, nunca
    ajustado por evento societário (Seção 5.3) — dividir dois valores desta função
    direto pode transformar um grupamento/bonificação em retorno de centenas de por
    cento (achado real, Seção 9.5: um único evento inflou um backtest de 119% para
    931%). O nome da função não avisa essa armadilha, por isso o aviso está aqui."""
    stmt = (
        select(CotahistPrice.close)
        .where(CotahistPrice.ticker == ticker, CotahistPrice.trade_date <= data_decisao)
        .order_by(CotahistPrice.trade_date.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def preco_as_of_lote(session: Session, tickers: list[str], data_decisao: date) -> dict[str, float | None]:
    """Mesma consulta de `preco_as_of`, para todos os `tickers` de uma vez — parte da
    reescrita em lote (2026-08-29). Mesmo aviso de uso: seguro para avaliação
    point-in-time numa única data, nunca para retorno entre datas sem checar
    `backtest.tem_quebra_de_nivel` primeiro."""
    if not tickers:
        return {}
    rn = (
        func.row_number()
        .over(partition_by=CotahistPrice.ticker, order_by=CotahistPrice.trade_date.desc())
        .label("rn")
    )
    subq = (
        select(CotahistPrice.ticker, CotahistPrice.close, rn)
        .where(CotahistPrice.ticker.in_(tickers), CotahistPrice.trade_date <= data_decisao)
        .subquery()
    )
    stmt = select(subq.c.ticker, subq.c.close).where(subq.c.rn == 1)
    precos: dict[str, float | None] = {ticker: None for ticker in tickers}
    for ticker, close in session.execute(stmt).all():
        precos[ticker] = close
    return precos


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
    volume_mediano: float


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
    2. Resolve, em lote, o preço e o filing/itens financeiros de cada empresa
       sobrevivente — uma consulta por tipo de dado para o universo inteiro, não uma por
       empresa (reescrita em lote, 2026-08-29: a versão anterior fazia até 4 consultas
       repetidas do mesmo filing por empresa, uma por fator que precisava dele — achado
       da Fase 1 de medição, ver `changes/`).
    3. Para cada empresa sobrevivente, computa os três fatores brutos (Seção 7.1-7.3) a
       partir do dado já em memória, respeitando a matriz de aplicabilidade (dívida
       líquida/EBITDA nunca entra na lista de bancos — inaplicável é uma categoria
       diferente de faltante, nunca vira `None` para ser imputado por engano).
    4. Um `compute_demeaned_percentiles` por fator, sobre o universo inteiro que
       participa daquele fator.
    5. `compute_score_composto` por empresa — nunca reimplementado aqui.
    """
    universo_stats = build_universo_elegivel(session, data_decisao, setor_by_cnpj, **kwargs_universo)

    linhas = (
        session.execute(
            select(UniversoElegivel).where(UniversoElegivel.data_decisao == data_decisao)
        )
        .scalars()
        .all()
    )

    tickers = [linha.ticker for linha in linhas]
    cnpjs = list({linha.cnpj for linha in linhas})

    precos = preco_as_of_lote(session, tickers, data_decisao)
    filing_por_cnpj = get_latest_filing_as_of_lote(session, cnpjs, "DFP", data_decisao)
    filing_encontrado = {cnpj: f for cnpj, f in filing_por_cnpj.items() if f is not None}
    linhas_financeiras_por_cnpj = get_line_items_lote(session, filing_encontrado)

    earnings_yield_inputs: list[FactorInput] = []
    divida_liquida_ebitda_inputs: list[FactorInput] = []
    roe_inputs: list[FactorInput] = []

    for linha in linhas:
        bucket = (linha.segmento_b3, linha.subsetor_b3, linha.setor_b3)
        linhas_financeiras = linhas_financeiras_por_cnpj.get(linha.cnpj, [])

        preco = precos.get(linha.ticker)
        eps = _extrair_eps(linha.ticker, linhas_financeiras)
        earnings_yield = (
            earnings_yield_raw(eps, preco) if eps is not None and preco else None
        )
        earnings_yield_inputs.append(FactorInput(linha.ticker, earnings_yield, *bucket))

        if fator_divida_liquida_ebitda_aplicavel(linha.subsetor_b3):
            ebit = _extrair_ebit(linhas_financeiras)
            da = _extrair_da(linhas_financeiras)
            ebitda = ebit + da if ebit is not None and da is not None else None
            divida_liquida = _extrair_divida_liquida(linhas_financeiras)
            dle = (
                divida_liquida_ebitda_raw(divida_liquida, ebitda)
                if divida_liquida is not None and ebitda is not None
                else None
            )
            divida_liquida_ebitda_inputs.append(FactorInput(linha.ticker, dle, *bucket))

        lucro = _extrair_lucro_liquido_controladores(linhas_financeiras)
        patrimonio = _extrair_patrimonio_liquido_controladores(linhas_financeiras)
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
                volume_mediano=linha.volume_mediano,
            )
        )

    return DecisaoResultado(data_decisao=data_decisao, universo_stats=universo_stats, empresas=empresas)
