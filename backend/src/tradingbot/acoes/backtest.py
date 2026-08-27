"""Motor de backtest — spec 14, Seção 9.

Simulação + validação da carteira mínima (Seção 8, preâmbulo) contra os benchmarks que
já têm fonte real verificada (Seção 9.4): CDI, equal-weight do universo elegível,
ponderada por liquidez do universo elegível, e a nuvem nula por permutação.
IBOV/IBrX-100/SMLL ficam fora até a fonte de índice ser verificada — o motor abaixo é
indiferente a quais séries o alimentam, então plugá-los depois liga uma fonte nova a um
motor pronto, não redesenha nada aqui (Seção 9, nota do benchmark 1).

Reimplementa a matemática de curva de equity nativamente (`total_return_pct`,
`volatility_pct`, `max_drawdown`, ...) em vez de importar `backtesting/metrics.py` do
bot — mesmo a matemática sendo conceitualmente próxima, os dois módulos nunca
compartilham runtime (`CLAUDE.md`: "nunca estado, dado, modelo ou runtime").
"""

from __future__ import annotations

import random
import time
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.acoes.decisao import (
    PESOS_PADRAO,
    DecisaoResultado,
    build_decisao,
    preco_as_of,
)
from tradingbot.acoes.fatores import PesoFator
from tradingbot.acoes.formacao_minima import N_PADRAO, formar_carteira_minima
from tradingbot.acoes.ipca import deflacionar_piso
from tradingbot.acoes.models import CorporateEventFlag
from tradingbot.acoes.universo_elegivel import (
    DATA_BASE_LIQUIDEZ,
    JANELA_PREGOES_PADRAO,
    MIN_VOLUME_MEDIANO_PADRAO,
    volume_mediano_as_of,
)
from tradingbot.learning_engine.experiment_log import (
    DEFAULT_EXPERIMENTS_PATH_ACOES,
    DOMAIN_ACOES,
    OUTCOME_NO_FINDING,
    ExperimentRecord,
    append_experiment,
)

# Datas de decisão da série já medida (Seção 7.7/7.8) — uma por ano, 2015-2026. A
# última nunca ganha um período de holding no backtest (Seção 9: nenhuma decisão é
# avaliada sem retorno futuro realizado — mesma disciplina de nunca usar dado não
# publicado, aplicada aqui ao próprio veredito da decisão, não só ao fundamento que a
# alimenta).
DATAS_DECISAO_SERIE = (
    date(2015, 2, 27), date(2016, 2, 29), date(2017, 2, 24), date(2018, 2, 28),
    date(2019, 2, 28), date(2020, 2, 28), date(2021, 2, 26), date(2022, 2, 25),
    date(2023, 2, 28), date(2024, 2, 29), date(2025, 2, 28), date(2026, 2, 27),
)


# ---------------------------------------------------------------------------
# Métricas de curva de equity — genéricas sobre list[tuple[date, float]]
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DrawdownResult:
    max_drawdown_pct: float
    max_drawdown_duration_dias: int


def total_return_pct(equity_curve: list[tuple[date, float]], capital_inicial: float) -> float:
    if not equity_curve or capital_inicial <= 0:
        return 0.0
    return (equity_curve[-1][1] - capital_inicial) / capital_inicial


def volatility_pct(equity_curve: list[tuple[date, float]]) -> float:
    """Desvio-padrão populacional do retorno mês a mês — mesma lógica de
    `backtesting/metrics.py` do bot (marco a marco em vez de barra a barra), nunca
    importada de lá (runtime não compartilhado, ver docstring do módulo)."""
    if len(equity_curve) < 2:
        return 0.0
    retornos = [
        (atual - anterior) / anterior
        for (_, anterior), (_, atual) in zip(equity_curve, equity_curve[1:])
        if anterior > 0
    ]
    if not retornos:
        return 0.0
    media = sum(retornos) / len(retornos)
    variancia = sum((r - media) ** 2 for r in retornos) / len(retornos)
    return variancia**0.5


def max_drawdown(equity_curve: list[tuple[date, float]]) -> DrawdownResult:
    if not equity_curve:
        return DrawdownResult(0.0, 0)

    pico = equity_curve[0][1]
    data_pico = equity_curve[0][0]
    max_dd_pct = 0.0
    max_dd_dias = 0

    for data_marco, equity in equity_curve:
        if equity >= pico:
            pico = equity
            data_pico = data_marco
        else:
            dd_pct = (pico - equity) / pico if pico > 0 else 0.0
            max_dd_pct = max(max_dd_pct, dd_pct)
            max_dd_dias = max(max_dd_dias, (data_marco - data_pico).days)

    return DrawdownResult(max_dd_pct, max_dd_dias)


def _razao_ou_inf(numerador: float, denominador: float) -> float:
    if denominador == 0:
        return float("inf") if numerador > 0 else 0.0
    return numerador / denominador


def return_over_drawdown(retorno_total: float, max_dd_pct: float) -> float:
    return _razao_ou_inf(retorno_total, max_dd_pct)


def return_over_volatility(retorno_total: float, vol_pct: float) -> float:
    return _razao_ou_inf(retorno_total, vol_pct)


@dataclass(frozen=True)
class SimulacaoResultado:
    equity_curve: list[tuple[date, float]]
    total_return_pct: float
    volatility_pct: float
    max_drawdown_pct: float
    max_drawdown_duration_dias: int
    return_over_drawdown: float
    return_over_volatility: float
    turnover_medio: float
    n_transversal: list[int]  # tamanho do universo elegivel em cada decisao anual usada


def _compute_metricas(
    equity_curve: list[tuple[date, float]],
    capital_inicial: float,
    turnovers: list[float],
    n_transversal: list[int],
) -> SimulacaoResultado:
    dd = max_drawdown(equity_curve)
    ret = total_return_pct(equity_curve, capital_inicial)
    vol = volatility_pct(equity_curve)
    return SimulacaoResultado(
        equity_curve=list(equity_curve),
        total_return_pct=ret,
        volatility_pct=vol,
        max_drawdown_pct=dd.max_drawdown_pct,
        max_drawdown_duration_dias=dd.max_drawdown_duration_dias,
        return_over_drawdown=return_over_drawdown(ret, dd.max_drawdown_pct),
        return_over_volatility=return_over_volatility(ret, vol),
        turnover_medio=sum(turnovers) / len(turnovers) if turnovers else 0.0,
        n_transversal=list(n_transversal),
    )


# ---------------------------------------------------------------------------
# Custos — Seção 9 pede "parametrizados", não um valor único verificado contra a
# tabela vigente da B3 (diferente do resto da spec, que só materializa dado medido).
# Defaults conservadores, declarados como parâmetro, nunca como fato medido.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CustosSimulacao:
    corretagem_pct: float = 0.0
    emolumentos_pct: float = 0.0005
    slippage_normal_pct: float = 0.001
    slippage_saida_iliquidez_pct: float = 0.02

    @property
    def custo_normal_pct(self) -> float:
        return self.corretagem_pct + self.emolumentos_pct + self.slippage_normal_pct


# ---------------------------------------------------------------------------
# Seleção (quais tickers) e política de peso (como pesar) — separados de propósito:
# o candidato e os dois benchmarks derivados do universo diferem só em QUEM entra
# (seleção) e/ou em COMO pesa (política), nunca precisam de um motor de simulação
# próprio cada um.
# ---------------------------------------------------------------------------

Selecao = set[tuple[str, str]]  # {(ticker, cnpj), ...}
Selecionar = Callable[[DecisaoResultado], Selecao]


def selecionar_top_n(n: int = N_PADRAO) -> Selecionar:
    def _selecionar(resultado: DecisaoResultado) -> Selecao:
        posicoes = formar_carteira_minima(resultado, n=n)
        return {(p.ticker, p.cnpj) for p in posicoes}

    return _selecionar


def selecionar_universo_completo(resultado: DecisaoResultado) -> Selecao:
    return {(e.ticker, e.cnpj) for e in resultado.empresas}


@dataclass(frozen=True)
class PoliticaPeso:
    nome: str
    calcular: Callable[[list[str], Session, date], dict[str, float]]


def _pesos_iguais(tickers: list[str], session: Session, marco: date) -> dict[str, float]:
    if not tickers:
        return {}
    peso = 1.0 / len(tickers)
    return {t: peso for t in tickers}


def _pesos_por_volume(tickers: list[str], session: Session, marco: date) -> dict[str, float]:
    volumes = {}
    for ticker in tickers:
        volume = volume_mediano_as_of(session, ticker, marco, JANELA_PREGOES_PADRAO)
        if volume and volume > 0:
            volumes[ticker] = volume
    total = sum(volumes.values())
    if total <= 0:
        return {}
    return {t: v / total for t, v in volumes.items()}


POLITICA_PESO_IGUAL = PoliticaPeso("peso_igual", _pesos_iguais)
POLITICA_PESO_LIQUIDEZ = PoliticaPeso("peso_liquidez", _pesos_por_volume)


# ---------------------------------------------------------------------------
# Simulação mensal
# ---------------------------------------------------------------------------


def _fins_de_mes_no_intervalo(inicio: date, fim: date) -> list[date]:
    """Todo fim de mês entre `inicio` (exclusive) e `fim` (inclusive), na ordem
    cronológica — `inicio` já é o marco anterior, nunca repetido aqui."""
    marcos = []
    ano, mes = inicio.year, inicio.month
    while True:
        if mes == 12:
            ano, mes = ano + 1, 1
        else:
            mes += 1
        ultimo_dia = monthrange(ano, mes)[1]
        marco = date(ano, mes, ultimo_dia)
        if marco >= fim:
            break
        marcos.append(marco)
    marcos.append(fim)
    return marcos


def _turnover(holdings_atuais: dict[str, float], alvo: dict[str, float]) -> float:
    """Metade da soma das variações absolutas de peso — valor comprado == valor
    vendido num rebalanceamento normalizado a 1, dividir por 2 evita contar a mesma
    troca duas vezes (uma como compra, outra como venda)."""
    tickers = set(holdings_atuais) | set(alvo)
    return sum(abs(alvo.get(t, 0.0) - holdings_atuais.get(t, 0.0)) for t in tickers) / 2.0


def tem_quebra_de_nivel(session: Session, ticker: str, data_inicio: date, data_fim: date) -> bool:
    """Existe evento `CorporateEventFlag.is_level_break=True` (bonificação/grupamento,
    Seção 5.3) para `ticker` estritamente entre `data_inicio` (exclusive) e `data_fim`
    (inclusive)? `CotahistPrice.close` é bruto, nunca ajustado por evento societário — a
    própria docstring do modelo diz que isso é responsabilidade da consulta, cruzando
    com esta tabela, nunca da ingestão. `CorporateEventFlag` só tem tipo+data, nunca
    magnitude (a COTAHIST não carrega razão de bonificação/grupamento) — não existe como
    *ajustar* o preço numericamente, só como *detectar* que o intervalo atravessa uma
    quebra e recusar a interpretar a razão de preço bruto como retorno real (mesmo
    achado do benchmark, 2026-08-27: um `EG` de `BRPR3` em 2023-02-24 produzia sozinho
    a maior parte de um retorno de 11 anos que não existia)."""
    stmt = select(CorporateEventFlag.id).where(
        CorporateEventFlag.ticker == ticker,
        CorporateEventFlag.is_level_break.is_(True),
        CorporateEventFlag.event_date > data_inicio,
        CorporateEventFlag.event_date <= data_fim,
    ).limit(1)
    return session.execute(stmt).first() is not None


def _marcar_e_ajustar_mes(
    session: Session,
    holdings: dict[str, float],
    capital: float,
    marco_anterior: date,
    marco: date,
    custos: CustosSimulacao,
) -> tuple[float, dict[str, float]]:
    """Marca cada posição a mercado (preço point-in-time, nunca inventa retorno se
    faltar preço num dos dois extremos, ou se o intervalo atravessar uma quebra de
    nível não ajustável — Seção 5.3 — mantém o valor nominal nesses casos) e aplica a
    regra de saída por perda de liquidez (Seção 8): a posição é liquidada com a
    penalidade de slippage de saída, nunca desaparece do total sem custo.

    Devolve o capital total pós-marcação/saídas e o peso de cada sobrevivente **como
    fração do capital total** (não renormalizado entre os sobreviventes) — o
    reequilíbrio de volta ao peso-alvo da política acontece no chamador, como um
    turnover mensal normal, com seu próprio custo (o capital liberado por uma saída não
    volta a trabalhar de graça)."""
    valor_por_ticker: dict[str, float] = {}
    for ticker, peso in holdings.items():
        preco_novo = preco_as_of(session, ticker, marco)
        preco_velho = preco_as_of(session, ticker, marco_anterior)
        valor_base = capital * peso
        quebra = tem_quebra_de_nivel(session, ticker, marco_anterior, marco)
        if preco_novo and preco_velho and preco_velho > 0 and not quebra:
            valor_por_ticker[ticker] = valor_base * (preco_novo / preco_velho)
        else:
            valor_por_ticker[ticker] = valor_base

    piso_liquidez = deflacionar_piso(MIN_VOLUME_MEDIANO_PADRAO, DATA_BASE_LIQUIDEZ, marco, session)

    total = 0.0
    sobreviventes: dict[str, float] = {}
    for ticker, valor in valor_por_ticker.items():
        volume = volume_mediano_as_of(session, ticker, marco, JANELA_PREGOES_PADRAO)
        if volume is None or volume < piso_liquidez:
            total += valor * (1 - custos.slippage_saida_iliquidez_pct)
        else:
            total += valor
            sobreviventes[ticker] = valor

    if total <= 0:
        return 0.0, {}
    return total, {t: v / total for t, v in sobreviventes.items()}


def simulate_estrategia(
    session: Session,
    datas_decisao: tuple[date, ...],
    selecionar: Selecionar,
    politica_peso: PoliticaPeso,
    setor_by_cnpj: dict[str, str],
    *,
    capital_inicial: float = 10_000.0,
    custos: CustosSimulacao = CustosSimulacao(),
    pesos: tuple[PesoFator, ...] = PESOS_PADRAO,
    **kwargs_universo,
) -> SimulacaoResultado:
    """Formação de carteira mínima (Seção 8) simulada mês a mês entre decisões anuais —
    seleção só muda numa data de decisão (fundamento é anual), peso é reequilibrado
    todo mês (Seção 9: "rebalanceamento mensal"), saída por perda de liquidez checada
    todo mês (Seção 8, a regra que não pode ser adiada)."""
    datas_ordenadas = sorted(datas_decisao)
    if len(datas_ordenadas) < 2:
        raise ValueError("precisa de pelo menos 2 datas de decisao para ter retorno realizado")

    equity_curve: list[tuple[date, float]] = [(datas_ordenadas[0], capital_inicial)]
    turnovers: list[float] = []
    n_transversal: list[int] = []
    capital = capital_inicial
    holdings: dict[str, float] = {}
    marco_anterior = datas_ordenadas[0]

    for data_decisao, proxima_decisao in zip(datas_ordenadas, datas_ordenadas[1:]):
        resultado = build_decisao(session, data_decisao, setor_by_cnpj, pesos=pesos, **kwargs_universo)
        n_transversal.append(len(resultado.empresas))

        tickers_selecionados = sorted(t for t, _ in selecionar(resultado))
        alvo = politica_peso.calcular(tickers_selecionados, session, data_decisao)

        turnover = _turnover(holdings, alvo)
        capital -= capital * turnover * custos.custo_normal_pct
        turnovers.append(turnover)
        holdings = dict(alvo)
        marco_anterior = data_decisao

        for marco in _fins_de_mes_no_intervalo(data_decisao, proxima_decisao):
            capital, holdings_pos_saida = _marcar_e_ajustar_mes(
                session, holdings, capital, marco_anterior, marco, custos
            )
            equity_curve.append((marco, capital))
            marco_anterior = marco

            if holdings_pos_saida:
                alvo_mes = politica_peso.calcular(sorted(holdings_pos_saida), session, marco)
                turnover_mes = _turnover(holdings_pos_saida, alvo_mes)
                capital -= capital * turnover_mes * custos.custo_normal_pct
                turnovers.append(turnover_mes)
                holdings = dict(alvo_mes)
            else:
                holdings = {}

    return _compute_metricas(equity_curve, capital_inicial, turnovers, n_transversal)


# ---------------------------------------------------------------------------
# Teste de nulidade (Seção 9): permuta a associação score-retorno futuro, N >= 100.
# Usa o retorno anual "de um tiro" (preço na decisão -> preço na próxima decisão), não
# a simulação mensal completa com custos — isolar o efeito de "quem foi selecionado"
# do resto da mecânica de simulação é o que o teste de significância pede, e roda
# N>=100 vezes sem precisar refazer o loop mensal a cada permutação.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TesteNulidadeResultado:
    metrica_real: float
    metrica_nula: list[float]
    p_valor: float
    fora_da_nuvem_nula: bool


def _retorno_anual_por_ticker(
    session: Session, resultado: DecisaoResultado, proxima_decisao: date
) -> dict[str, float | None]:
    """`None` (nunca inventa retorno) quando falta preço num dos extremos OU quando o
    intervalo atravessa uma quebra de nível não ajustável (`tem_quebra_de_nivel`) —
    mesma disciplina de `_marcar_e_ajustar_mes`, para o teste de nulidade não herdar o
    mesmo artefato que inflou a simulação (Seção 9, achado 2026-08-27)."""
    retornos: dict[str, float | None] = {}
    for empresa in resultado.empresas:
        preco_inicio = preco_as_of(session, empresa.ticker, resultado.data_decisao)
        preco_fim = preco_as_of(session, empresa.ticker, proxima_decisao)
        quebra = tem_quebra_de_nivel(session, empresa.ticker, resultado.data_decisao, proxima_decisao)
        retornos[empresa.ticker] = (
            (preco_fim - preco_inicio) / preco_inicio
            if preco_inicio and preco_fim and preco_inicio > 0 and not quebra
            else None
        )
    return retornos


def _metrica_selecao(tickers_selecionados: list[str], retornos_por_ticker: dict[str, float | None]) -> float | None:
    validos = [retornos_por_ticker[t] for t in tickers_selecionados if retornos_por_ticker.get(t) is not None]
    if not validos:
        return None
    return sum(validos) / len(validos)


def teste_nulidade(
    session: Session,
    datas_decisao: tuple[date, ...],
    setor_by_cnpj: dict[str, str],
    *,
    n_top: int = N_PADRAO,
    n_permutacoes: int = 100,
    pesos: tuple[PesoFator, ...] = PESOS_PADRAO,
    rng: random.Random | None = None,
    **kwargs_universo,
) -> TesteNulidadeResultado:
    if n_permutacoes < 100:
        raise ValueError("N < 100 nao satisfaz o piso do teste de nulidade (Secao 9)")

    datas_ordenadas = sorted(datas_decisao)
    if rng is None:
        rng = random.Random()

    tickers_por_ano: list[list[str]] = []
    scores_por_ano: list[dict[str, float | None]] = []
    retornos_por_ano: list[dict[str, float | None]] = []
    metricas_reais: list[float] = []

    for data_decisao, proxima_decisao in zip(datas_ordenadas, datas_ordenadas[1:]):
        resultado = build_decisao(session, data_decisao, setor_by_cnpj, pesos=pesos, **kwargs_universo)
        retornos = _retorno_anual_por_ticker(session, resultado, proxima_decisao)
        tickers = [e.ticker for e in resultado.empresas]
        scores = {e.ticker: e.score_composto for e in resultado.empresas}

        selecionados_reais = sorted(
            (t for t in tickers if scores[t] is not None), key=lambda t: (-scores[t], t)
        )[:n_top]
        metrica_real = _metrica_selecao(selecionados_reais, retornos)
        if metrica_real is not None:
            metricas_reais.append(metrica_real)

        tickers_por_ano.append(tickers)
        scores_por_ano.append(scores)
        retornos_por_ano.append(retornos)

    metrica_real_agregada = sum(metricas_reais) / len(metricas_reais) if metricas_reais else 0.0

    metricas_nulas: list[float] = []
    for _ in range(n_permutacoes):
        metricas_do_ano: list[float] = []
        for tickers, scores, retornos in zip(tickers_por_ano, scores_por_ano, retornos_por_ano):
            valores = [scores[t] for t in tickers]
            rng.shuffle(valores)
            scores_embaralhados = dict(zip(tickers, valores))
            selecionados = sorted(
                (t for t in tickers if scores_embaralhados[t] is not None),
                key=lambda t: (-scores_embaralhados[t], t),
            )[:n_top]
            metrica = _metrica_selecao(selecionados, retornos)
            if metrica is not None:
                metricas_do_ano.append(metrica)
        if metricas_do_ano:
            metricas_nulas.append(sum(metricas_do_ano) / len(metricas_do_ano))

    if not metricas_nulas:
        return TesteNulidadeResultado(metrica_real_agregada, [], 1.0, False)

    mais_extremas_ou_iguais = sum(1 for m in metricas_nulas if m >= metrica_real_agregada)
    p_valor = mais_extremas_ou_iguais / len(metricas_nulas)
    return TesteNulidadeResultado(
        metrica_real=metrica_real_agregada,
        metrica_nula=metricas_nulas,
        p_valor=p_valor,
        fora_da_nuvem_nula=p_valor < 0.05,
    )


# ---------------------------------------------------------------------------
# Walk-forward por fold (Seção 9 — folds temporais, nunca confundir com N transversal,
# Seção 10). "Purga" no sentido do bot (janela de treino/teste) não tem equivalente
# aqui: os pesos dos fatores (PESOS_PADRAO) são fixos a priori, nunca ajustados a
# partir de dado — não existe parâmetro treinado que pudesse vazar entre folds. A
# garantia equivalente é estrutural, não uma janela extra: cada fold só agrega retorno
# realizado estritamente dentro do próprio intervalo de decisões (`simulate_estrategia`
# já nunca usa uma decisão sem a próxima).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FoldResultado:
    datas_decisao: tuple[date, ...]
    n_transversal_min: int
    n_transversal_mediano: int
    n_transversal_maximo: int
    resultado: SimulacaoResultado


def _mediana_int(valores: list[int]) -> int:
    ordenados = sorted(valores)
    return ordenados[len(ordenados) // 2]


def walk_forward_folds(
    session: Session,
    datas_decisao: tuple[date, ...],
    selecionar: Selecionar,
    politica_peso: PoliticaPeso,
    setor_by_cnpj: dict[str, str],
    *,
    tamanho_fold: int = 4,
    capital_inicial: float = 10_000.0,
    custos: CustosSimulacao = CustosSimulacao(),
    pesos: tuple[PesoFator, ...] = PESOS_PADRAO,
    **kwargs_universo,
) -> list[FoldResultado]:
    datas_ordenadas = sorted(datas_decisao)
    folds: list[FoldResultado] = []
    i = 0
    while i + 1 < len(datas_ordenadas):
        fim = min(i + tamanho_fold + 1, len(datas_ordenadas))
        datas_do_fold = tuple(datas_ordenadas[i:fim])
        if len(datas_do_fold) < 2:
            break

        n_transversal = [
            len(build_decisao(session, data_decisao, setor_by_cnpj, pesos=pesos, **kwargs_universo).empresas)
            for data_decisao in datas_do_fold[:-1]
        ]

        resultado_fold = simulate_estrategia(
            session,
            datas_do_fold,
            selecionar,
            politica_peso,
            setor_by_cnpj,
            capital_inicial=capital_inicial,
            custos=custos,
            pesos=pesos,
            **kwargs_universo,
        )
        folds.append(
            FoldResultado(
                datas_decisao=datas_do_fold,
                n_transversal_min=min(n_transversal),
                n_transversal_mediano=_mediana_int(n_transversal),
                n_transversal_maximo=max(n_transversal),
                resultado=resultado_fold,
            )
        )
        i += tamanho_fold

    return folds


# ---------------------------------------------------------------------------
# Contabilização de configurações testadas (Seção 9.2) — mesmo componente do bot,
# domain="acoes", arquivo físico separado (learnings/experiments_acoes.jsonl).
# ---------------------------------------------------------------------------


def registrar_experimento(
    hypothesis: str,
    params: dict,
    result_summary: dict,
    *,
    outcome: str = OUTCOME_NO_FINDING,
    changes_file: str | None = None,
    path: Path = DEFAULT_EXPERIMENTS_PATH_ACOES,
) -> ExperimentRecord:
    record = ExperimentRecord(
        ts=int(time.time()),
        hypothesis=hypothesis,
        tool="acoes_backtest",
        params=params,
        result_summary=result_summary,
        outcome=outcome,
        changes_file=changes_file,
        domain=DOMAIN_ACOES,
    )
    append_experiment(record, path)
    return record
