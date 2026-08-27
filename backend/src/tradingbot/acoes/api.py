"""API do módulo de Ações — spec 14, Seção 11. `APIRouter` próprio, montado em
`tradingbot.api.app` via `include_router`, com sessão de banco própria
(`acoes.persistence`) — nunca reusa `app.state.session_factory`/`orchestrator` do bot
(CLAUDE.md: "nunca estado, dado, modelo ou runtime" compartilhado entre os módulos).

Painel de evidência, não de recomendação (Seção 11.0): toda rota devolve dado point-in-
time com proveniência — nunca um "score final" sem os componentes que o formam, nunca
um número de balanço sem a data em que ficou público.
"""

from __future__ import annotations

import json
import threading
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradingbot.acoes.backtest import DATAS_DECISAO_SERIE
from tradingbot.acoes.decisao import DecisaoEmpresa, DecisaoResultado, build_decisao, preco_as_of
from tradingbot.acoes.fatores import (
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
from tradingbot.acoes.models import (
    CdiTaxa,
    CnpjTickerMap,
    CotahistPrice,
    CvmFiling,
    CvmFinancialLineItem,
    IpcaIndice,
    UniversoElegivel,
    UniversoExclusao,
)
from tradingbot.acoes.persistence import get_session
from tradingbot.acoes.pointintime import get_latest_filing_as_of
from tradingbot.acoes.universo_elegivel import MIN_PREGOES_HISTORICO_PADRAO

router = APIRouter(prefix="/api/acoes", tags=["acoes"])

RESULTS_DIR = Path(__file__).resolve().parents[4] / "results"
BACKTEST_RESULT_PATH = RESULTS_DIR / "acoes_backtest.json"

FONTE_ALTA_CONFIANCA = "fca"

# Módulo constante (não hardcoded na chamada) para ser monkeypatchável em teste — a
# fixture leve reusada em `test_acoes_api.py` (mesmo dado de `test_acoes_decisao.py`)
# não tem histórico suficiente para o piso de produção (252 pregões), mesma razão pela
# qual os testes de `build_decisao` já passam `min_pregoes_historico=60` explicitamente.
MIN_PREGOES_HISTORICO = MIN_PREGOES_HISTORICO_PADRAO


def _session() -> Session:
    return get_session()


# `build_decisao` materializa o universo elegível + computa os três fatores para cada
# empresa (centenas de consultas point-in-time) — medido em ~15-60s por data (Seção 9,
# mesma ordem de grandeza do backtest completo). As telas de Empresa/Histórico chamam
# várias datas na mesma requisição, e datas passadas nunca mudam de resultado (mesma
# garantia de reprodutibilidade point-in-time que já rege o resto da spec) — cache em
# processo por data_decisao, nunca para "hoje" (a única data cujo resultado pode mudar
# dentro do mesmo dia, conforme novo dado point-in-time chega).
_cache_decisao: dict[date, DecisaoResultado] = {}

# FastAPI roda handlers `def` (síncronos) num threadpool — duas requisições lentas em
# paralelo (achado real: Empresa + Saúde do Dado navegadas em sequência rápida)
# disputam a mesma `_cache_decisao` sem trava nenhuma, e pior, escrevem no mesmo
# arquivo SQLite ao mesmo tempo por conexões de threads diferentes — medido causando
# timeout de conexão no navegador (aparece como falha de CORS, mas a causa real é a
# requisição nunca terminar). Uma trava global serializa o cálculo: esta API é
# "ferramenta de trabalho" de um usuário só (Seção 11.1), não um serviço de alta
# concorrência — correção nunca fica mais lenta que sem a trava, só nunca mais rápida
# que uma requisição de cada vez.
_lock_decisao = threading.Lock()


def _build_decisao_cacheada(session: Session, data_decisao: date) -> DecisaoResultado:
    hoje = date.today()
    if data_decisao == hoje:
        with _lock_decisao:
            return build_decisao(session, data_decisao, {}, min_pregoes_historico=MIN_PREGOES_HISTORICO)
    if data_decisao not in _cache_decisao:
        with _lock_decisao:
            if data_decisao not in _cache_decisao:  # outra thread pode ter terminado enquanto esperava a trava
                _cache_decisao[data_decisao] = build_decisao(
                    session, data_decisao, {}, min_pregoes_historico=MIN_PREGOES_HISTORICO
                )
    return _cache_decisao[data_decisao]


# Desligado em teste (`test_acoes_api.py` monkeypatcha para `False` antes de criar o
# `TestClient`) — sem isso, a thread de aquecimento dispara no `lifespan` do
# `TestClient` e corre contra as próprias asserções do teste sobre o estado do cache
# (`_cache_decisao` vazio logo após o startup), uma fonte de flakiness por timing que
# não tem por que existir aqui.
WARMUP_HABILITADO = True


def warm_up_cache_em_background() -> None:
    """Pré-aquece `_cache_decisao` para as 12 datas de `DATAS_DECISAO_SERIE` numa
    thread separada, chamada pelo `lifespan` da API (Seção 11) — sem isso, a primeira
    pessoa a abrir Empresa/Histórico/Saúde do Dado paga a soma de todo o cálculo (~12 x
    15-30s, agora serializado pela trava acima), em vez de cada requisição normal já
    encontrar o cache pronto. Roda em thread daemon (nunca atrasa o startup do
    servidor, nunca impede o processo de encerrar)."""
    if not WARMUP_HABILITADO:
        return

    def _aquecer():
        session = _session()
        try:
            for data in DATAS_DECISAO_SERIE:
                if date.today() >= data:
                    _build_decisao_cacheada(session, data)
        finally:
            session.close()

    threading.Thread(target=_aquecer, name="acoes-warmup", daemon=True).start()


# ---------------------------------------------------------------------------
# Resolução de data — "mês atual" e navegação mês a mês, sempre travada ao último
# pregão disponível quando o mês pedido ainda não fechou (nunca inventa dado futuro).
# ---------------------------------------------------------------------------


def _ultima_data_disponivel(session: Session) -> date | None:
    return session.execute(select(func.max(CotahistPrice.trade_date))).scalar()


def _resolver_data_decisao(session: Session, ano: int | None, mes: int | None) -> date:
    hoje = date.today()
    ano = ano or hoje.year
    mes = mes or hoje.month
    ultimo_dia = monthrange(ano, mes)[1]
    fim_do_mes = date(ano, mes, ultimo_dia)
    ultima_disponivel = _ultima_data_disponivel(session)
    if ultima_disponivel is None:
        return fim_do_mes
    return min(fim_do_mes, ultima_disponivel)


def _mes_anterior(ano: int, mes: int) -> tuple[int, int]:
    return (ano - 1, 12) if mes == 1 else (ano, mes - 1)


# ---------------------------------------------------------------------------
# Detalhe por fator — valor bruto + percentil + carimbo + motivo da célula vazia
# (Seção 11.3: inaplicavel / indefinido / sem_dado / versao_indisponivel). Reusa só
# funções já públicas de `fatores.py`/`pointintime.py` — nunca reimplementa a
# extração do dado, só materializa o que `build_decisao` já computou mas não expõe.
# ---------------------------------------------------------------------------


def _filing_existe_mas_sem_itens(session: Session, cnpj: str, filing: CvmFiling) -> bool:
    """`True` quando a CVM listou a existência do filing (índice mestre) mas nenhuma
    linha de item financeiro dessa versão específica está disponível no arquivo
    público — o achado real da Seção 7.5 ("versão indisponível"), distinto de
    "empresa não reportou este campo" (que tem outras linhas da mesma versão, só não
    a procurada)."""
    existe = session.execute(
        select(CvmFinancialLineItem.id)
        .where(
            CvmFinancialLineItem.cnpj_cia == cnpj,
            CvmFinancialLineItem.dt_refer == filing.dt_refer,
            CvmFinancialLineItem.versao == filing.versao,
        )
        .limit(1)
    ).first()
    return existe is None


def _motivo_ausencia(session: Session, cnpj: str, filing: CvmFiling | None) -> str:
    if filing is None:
        return "sem_dado"
    if _filing_existe_mas_sem_itens(session, cnpj, filing):
        return "versao_indisponivel"
    return "sem_dado"


def _carimbo(filing: CvmFiling | None) -> dict | None:
    if filing is None:
        return None
    return {"data_publicacao": filing.dt_receb.isoformat(), "versao": filing.versao}


def _detalhe_earnings_yield(session: Session, empresa: DecisaoEmpresa, data_decisao: date) -> dict:
    filing = get_latest_filing_as_of(session, empresa.cnpj, "DFP", data_decisao)
    eps = get_eps_as_of(session, empresa.cnpj, empresa.ticker, data_decisao)
    preco = preco_as_of(session, empresa.ticker, data_decisao)
    if eps is not None and preco:
        valor = earnings_yield_raw(eps, preco)
        if valor is None:  # EPS implausível na fonte (achado Seção 13, 2026-08-27)
            return {"valor": None, "percentil": None, "carimbo": _carimbo(filing), "motivo": "indefinido"}
        return {
            "valor": valor,
            "percentil": empresa.earnings_yield_percentil,
            "carimbo": _carimbo(filing),
            "motivo": None,
        }
    return {
        "valor": None,
        "percentil": None,
        "carimbo": None,
        "motivo": _motivo_ausencia(session, empresa.cnpj, filing),
    }


def _detalhe_divida_liquida_ebitda(session: Session, empresa: DecisaoEmpresa, data_decisao: date) -> dict:
    if not fator_divida_liquida_ebitda_aplicavel(empresa.subsetor_b3):
        return {"valor": None, "percentil": None, "carimbo": None, "motivo": "inaplicavel"}

    filing = get_latest_filing_as_of(session, empresa.cnpj, "DFP", data_decisao)
    divida = get_divida_liquida_as_of(session, empresa.cnpj, data_decisao)
    ebitda = get_ebitda_as_of(session, empresa.cnpj, data_decisao)
    if divida is not None and ebitda is not None:
        valor = divida_liquida_ebitda_raw(divida, ebitda)
        if valor is None:
            return {"valor": None, "percentil": None, "carimbo": _carimbo(filing), "motivo": "indefinido"}
        return {"valor": valor, "percentil": empresa.divida_liquida_ebitda_percentil, "carimbo": _carimbo(filing), "motivo": None}
    return {
        "valor": None,
        "percentil": None,
        "carimbo": None,
        "motivo": _motivo_ausencia(session, empresa.cnpj, filing),
    }


def _detalhe_roe(session: Session, empresa: DecisaoEmpresa, data_decisao: date) -> dict:
    filing = get_latest_filing_as_of(session, empresa.cnpj, "DFP", data_decisao)
    lucro = get_lucro_liquido_controladores_as_of(session, empresa.cnpj, data_decisao)
    patrimonio = get_patrimonio_liquido_controladores_as_of(session, empresa.cnpj, data_decisao)
    if lucro is not None and patrimonio is not None:
        valor = roe_raw(lucro, patrimonio)
        if valor is None:
            return {"valor": None, "percentil": None, "carimbo": _carimbo(filing), "motivo": "indefinido"}
        return {"valor": valor, "percentil": empresa.roe_percentil, "carimbo": _carimbo(filing), "motivo": None}
    return {
        "valor": None,
        "percentil": None,
        "carimbo": None,
        "motivo": _motivo_ausencia(session, empresa.cnpj, filing),
    }


def _selo_identidade(session: Session, ticker: str, data_decisao: date) -> str:
    """Três estados (Seção 11.3) — direto da fonte real gravada em `cnpj_ticker_map`
    (Seção 5.6), nunca um heurístico por era: `fca` é a fonte de alta confiança;
    `raiz_propagacao`/`reconciliacao_nome` são as duas fontes de fallback. Empresa fora
    do universo (identidade não resolvida) não passa por aqui — só aparece na tela de
    Saúde do Dado (Seção 11.7)."""
    row = session.execute(
        select(CnpjTickerMap.fonte).where(
            CnpjTickerMap.ticker == ticker,
            CnpjTickerMap.data_inicio_vigencia <= data_decisao,
            (CnpjTickerMap.data_fim_vigencia.is_(None)) | (CnpjTickerMap.data_fim_vigencia > data_decisao),
        )
    ).scalar_one_or_none()
    if row is None or row == FONTE_ALTA_CONFIANCA:
        return "alta_confianca"
    return "reconciliada"


def _empresa_para_ranking(session: Session, empresa: DecisaoEmpresa, data_decisao: date) -> dict:
    return {
        "ticker": empresa.ticker,
        "cnpj": empresa.cnpj,
        "setor_b3": empresa.setor_b3,
        "subsetor_b3": empresa.subsetor_b3,
        "segmento_b3": empresa.segmento_b3,
        "selo_identidade": _selo_identidade(session, empresa.ticker, data_decisao),
        "earnings_yield": _detalhe_earnings_yield(session, empresa, data_decisao),
        "divida_liquida_ebitda": _detalhe_divida_liquida_ebitda(session, empresa, data_decisao),
        "roe": _detalhe_roe(session, empresa, data_decisao),
        "score_composto": empresa.score_composto,
    }


def _distribuicao_setorial(empresas: list[DecisaoEmpresa]) -> list[dict]:
    contagem: dict[str, int] = {}
    for empresa in empresas:
        chave = empresa.setor_b3 or "Sem classificação B3"
        contagem[chave] = contagem.get(chave, 0) + 1
    total = len(empresas) or 1
    return sorted(
        (
            {"setor": setor, "contagem": n, "pct": n / total, "amostra_pequena": n < 6}
            for setor, n in contagem.items()
        ),
        key=lambda x: -x["contagem"],
    )


def _mudancas_do_mes(
    session: Session, resultado_atual: DecisaoResultado, resultado_anterior: DecisaoResultado | None
) -> dict:
    if resultado_anterior is None:
        return {"entraram": 0, "sairam": 0, "balancos_novos": 0, "retificacoes": 0}

    tickers_atual = {e.ticker for e in resultado_atual.empresas}
    tickers_anterior = {e.ticker for e in resultado_anterior.empresas}

    balancos_novos = session.execute(
        select(func.count(CvmFiling.id)).where(
            CvmFiling.dt_receb > resultado_anterior.data_decisao,
            CvmFiling.dt_receb <= resultado_atual.data_decisao,
        )
    ).scalar()
    retificacoes = session.execute(
        select(func.count(CvmFiling.id)).where(
            CvmFiling.dt_receb > resultado_anterior.data_decisao,
            CvmFiling.dt_receb <= resultado_atual.data_decisao,
            CvmFiling.versao > 1,
        )
    ).scalar()

    return {
        "entraram": len(tickers_atual - tickers_anterior),
        "sairam": len(tickers_anterior - tickers_atual),
        "balancos_novos": balancos_novos or 0,
        "retificacoes": retificacoes or 0,
    }


@router.get("/mes-atual")
def mes_atual(ano: int | None = None, mes: int | None = None):
    session = _session()
    try:
        data_decisao = _resolver_data_decisao(session, ano, mes)
        resultado = _build_decisao_cacheada(session, data_decisao)

        ano_anterior, mes_anterior_num = _mes_anterior(data_decisao.year, data_decisao.month)
        data_anterior = _resolver_data_decisao(session, ano_anterior, mes_anterior_num)
        resultado_anterior = (
            _build_decisao_cacheada(session, data_anterior) if data_anterior < data_decisao else None
        )

        excluidas = list(
            session.execute(
                select(UniversoExclusao).where(UniversoExclusao.data_decisao == data_decisao)
            ).scalars()
        )

        ranking = [_empresa_para_ranking(session, e, data_decisao) for e in resultado.empresas]
        ranking.sort(key=lambda e: (e["score_composto"] is None, -(e["score_composto"] or 0), e["ticker"]))

        total = len(resultado.empresas)
        return {
            "data_decisao": data_decisao.isoformat(),
            "elegiveis": total,
            "com_score": resultado.n_score_computavel,
            "excluidas": len(excluidas),
            "cobertura_pct": (resultado.n_score_computavel / total) if total else 0.0,
            "ranking": ranking,
            "distribuicao_setorial": _distribuicao_setorial(resultado.empresas),
            "mudancas_do_mes": _mudancas_do_mes(session, resultado, resultado_anterior),
            "excluidas_detalhe": [{"ticker": x.ticker, "motivo": x.motivo} for x in excluidas],
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Empresa (Seção 11.5)
# ---------------------------------------------------------------------------


def _vigencia_ticker(session: Session, cnpj: str) -> list[dict]:
    linhas = session.execute(
        select(CnpjTickerMap).where(CnpjTickerMap.cnpj == cnpj).order_by(CnpjTickerMap.data_inicio_vigencia)
    ).scalars().all()
    return [
        {
            "ticker": linha.ticker,
            "data_inicio_vigencia": linha.data_inicio_vigencia.isoformat(),
            "data_fim_vigencia": linha.data_fim_vigencia.isoformat() if linha.data_fim_vigencia else None,
            "fonte": linha.fonte,
        }
        for linha in linhas
    ]


def _historico_entregas_cvm(session: Session, cnpj: str) -> list[dict]:
    filings = session.execute(
        select(CvmFiling)
        .where(CvmFiling.cnpj_cia == cnpj, CvmFiling.categ_doc == "DFP")
        .order_by(CvmFiling.dt_refer.desc(), CvmFiling.versao.desc())
    ).scalars().all()
    return [
        {
            "dt_refer": f.dt_refer.isoformat(),
            "versao": f.versao,
            "dt_receb": f.dt_receb.isoformat(),
        }
        for f in filings
    ]


def _retificacoes_ultimos_5_anos(historico: list[dict], data_decisao: date) -> int:
    limite = date(data_decisao.year - 5, data_decisao.month, 1)
    return sum(1 for f in historico if f["versao"] > 1 and date.fromisoformat(f["dt_receb"]) >= limite)


@router.get("/empresas/{ticker}")
def empresa_detalhe(ticker: str, ano: int | None = None, mes: int | None = None):
    session = _session()
    try:
        data_decisao = _resolver_data_decisao(session, ano, mes)
        resultado = _build_decisao_cacheada(session, data_decisao)
        empresa = next((e for e in resultado.empresas if e.ticker == ticker), None)
        if empresa is None:
            raise HTTPException(status_code=404, detail="ticker não está no universo elegível na data pedida")

        linha_do_tempo = []
        for data in DATAS_DECISAO_SERIE:
            if data > data_decisao:
                continue
            resultado_historico = _build_decisao_cacheada(session, data)
            historica = next((e for e in resultado_historico.empresas if e.ticker == ticker), None)
            if historica is None:
                continue
            linha_do_tempo.append(
                {
                    "data_decisao": data.isoformat(),
                    "earnings_yield": _detalhe_earnings_yield(session, historica, data)["valor"],
                    "divida_liquida_ebitda": _detalhe_divida_liquida_ebitda(session, historica, data)["valor"],
                    "roe": _detalhe_roe(session, historica, data)["valor"],
                }
            )

        historico_cvm = _historico_entregas_cvm(session, empresa.cnpj)

        return {
            "ticker": empresa.ticker,
            "cnpj": empresa.cnpj,
            "setor_b3": empresa.setor_b3,
            "subsetor_b3": empresa.subsetor_b3,
            "segmento_b3": empresa.segmento_b3,
            "selo_identidade": _selo_identidade(session, empresa.ticker, data_decisao),
            "vigencia_ticker": _vigencia_ticker(session, empresa.cnpj),
            "fatores_hoje": {
                "earnings_yield": _detalhe_earnings_yield(session, empresa, data_decisao),
                "divida_liquida_ebitda": _detalhe_divida_liquida_ebitda(session, empresa, data_decisao),
                "roe": _detalhe_roe(session, empresa, data_decisao),
            },
            "linha_do_tempo_conhecimento": linha_do_tempo,
            "historico_entregas_cvm": historico_cvm,
            "retificacoes_ultimos_5_anos": _retificacoes_ultimos_5_anos(historico_cvm, data_decisao),
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Saúde do dado (Seção 11.7)
# ---------------------------------------------------------------------------

FRESCOR_LIMITE_DIAS = 10


def _status_fonte(ultima_data: date | None, hoje: date) -> dict:
    if ultima_data is None:
        return {"ultima_coleta": None, "status": "sem_dado"}
    idade_dias = (hoje - ultima_data).days
    return {
        "ultima_coleta": ultima_data.isoformat(),
        "idade_dias": idade_dias,
        "status": "ok" if idade_dias <= FRESCOR_LIMITE_DIAS else "atrasado",
    }


@router.get("/saude-do-dado")
def saude_do_dado(ano: int | None = None, mes: int | None = None):
    session = _session()
    try:
        hoje = date.today()
        data_decisao = _resolver_data_decisao(session, ano, mes)

        fontes = {
            "cvm_dfp_itr": _status_fonte(
                session.execute(select(func.max(CvmFiling.dt_receb))).scalar(), hoje
            ),
            "cotahist": _status_fonte(_ultima_data_disponivel(session), hoje),
            "cdi": _status_fonte(
                session.execute(select(func.max(CdiTaxa.data_referencia))).scalar(), hoje
            ),
            "ipca": _status_fonte(
                session.execute(select(func.max(IpcaIndice.data_referencia))).scalar(), hoje
            ),
        }
        todas_ok = all(f["status"] == "ok" for f in fontes.values())

        cobertura_por_ano = []
        for data in DATAS_DECISAO_SERIE:
            if data > data_decisao:
                continue
            resultado = _build_decisao_cacheada(session, data)
            total = len(resultado.empresas)
            cobertura_por_ano.append(
                {
                    "ano": data.year,
                    "data_decisao": data.isoformat(),
                    "elegiveis": total,
                    "com_score": resultado.n_score_computavel,
                    "cobertura_pct": (resultado.n_score_computavel / total) if total else 0.0,
                    "era": "confiavel" if data.year >= 2018 else "reconciliada",
                }
            )

        excluidas = list(
            session.execute(
                select(UniversoExclusao).where(UniversoExclusao.data_decisao == data_decisao)
            ).scalars()
        )
        contagem_por_motivo: dict[str, int] = {}
        for x in excluidas:
            contagem_por_motivo[x.motivo] = contagem_por_motivo.get(x.motivo, 0) + 1

        backtest = json.loads(BACKTEST_RESULT_PATH.read_text()) if BACKTEST_RESULT_PATH.exists() else None

        return {
            "data_decisao": data_decisao.isoformat(),
            "fontes": fontes,
            "todas_fontes_ok": todas_ok,
            "cobertura_por_ano": cobertura_por_ano,
            "exclusoes_do_mes": {
                "total": len(excluidas),
                "por_motivo": contagem_por_motivo,
                "detalhe": [{"ticker": x.ticker, "motivo": x.motivo} for x in excluidas],
            },
            "backtest": backtest,
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Histórico (Seção 11.8)
# ---------------------------------------------------------------------------


def _retorno_carteira_topo_ou_base(
    session: Session, resultado: DecisaoResultado, data_decisao: date, meses: int, *, topo: bool, n: int = 10
) -> float | None:
    ordenadas = sorted(
        (e for e in resultado.empresas if e.score_composto is not None),
        key=lambda e: (-e.score_composto, e.ticker),
    )
    if not ordenadas:
        return None
    alvo = ordenadas[:n] if topo else ordenadas[-n:]
    data_alvo = data_decisao + timedelta(days=30 * meses)
    retornos = []
    for empresa in alvo:
        preco_inicio = preco_as_of(session, empresa.ticker, data_decisao)
        preco_fim = preco_as_of(session, empresa.ticker, data_alvo)
        if preco_inicio and preco_fim and preco_inicio > 0:
            retornos.append((preco_fim - preco_inicio) / preco_inicio)
    if not retornos:
        return None
    return sum(retornos) / len(retornos)


@router.get("/historico")
def historico_lista():
    return {"datas_decisao": [d.isoformat() for d in DATAS_DECISAO_SERIE]}


@router.get("/historico/{data_decisao}")
def historico_detalhe(data_decisao: str):
    try:
        data = date.fromisoformat(data_decisao)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="data inválida, use AAAA-MM-DD") from exc
    if data not in DATAS_DECISAO_SERIE:
        raise HTTPException(status_code=404, detail="data não é uma decisão materializada da série")

    session = _session()
    try:
        resultado = _build_decisao_cacheada(session, data)
        ranking = [_empresa_para_ranking(session, e, data) for e in resultado.empresas]
        ranking.sort(key=lambda e: (e["score_composto"] is None, -(e["score_composto"] or 0), e["ticker"]))

        retorno_topo = {
            f"{meses}m": _retorno_carteira_topo_ou_base(session, resultado, data, meses, topo=True)
            for meses in (1, 3, 6, 12)
        }
        retorno_base = {
            f"{meses}m": _retorno_carteira_topo_ou_base(session, resultado, data, meses, topo=False)
            for meses in (1, 3, 6, 12)
        }

        return {
            "data_decisao": data.isoformat(),
            "elegiveis": len(resultado.empresas),
            "com_score": resultado.n_score_computavel,
            "ranking": ranking,
            "retorno_subsequente_topo_10": retorno_topo,
            "retorno_subsequente_base_10": retorno_base,
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Preços (Seção 11.6, Minha carteira) — última cotação conhecida por ticker, para
# marcar a valor atual uma composição digitada manualmente (nunca há corretora
# integrada, Seção 2). Consulta leve, nunca chama `build_decisao` — não precisa do
# universo elegível para simplesmente ler um preço já ingerido.
# ---------------------------------------------------------------------------


@router.get("/precos")
def precos(tickers: str):
    session = _session()
    try:
        hoje = date.today()
        lista = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        return {ticker: preco_as_of(session, ticker, hoje) for ticker in lista}
    finally:
        session.close()
