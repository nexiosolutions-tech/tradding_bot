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

from dataclasses import dataclass

from tradingbot.acoes.backtest import DATAS_DECISAO_SERIE
from tradingbot.acoes.decisao import DecisaoEmpresa, DecisaoResultado, build_decisao, preco_as_of_lote
from tradingbot.acoes.fatores import (
    _extrair_da,
    _extrair_divida_liquida,
    _extrair_ebit,
    _extrair_eps,
    _extrair_lucro_liquido_controladores,
    _extrair_patrimonio_liquido_controladores,
    divida_liquida_ebitda_raw,
    earnings_yield_raw,
    fator_divida_liquida_ebitda_aplicavel,
    roe_raw,
)
from tradingbot.acoes.cnpj_ticker_map import get_fonte_identidade_as_of_lote
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
from tradingbot.acoes.pointintime import existe_algum_item_lote, get_latest_filing_as_of_lote, get_line_items_lote
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


# ---------------------------------------------------------------------------
# Disponibilidade do módulo — persistência é local por escolha, não por omissão
# (Seção 11.12). Sem volume/Postgres em produção, `results/acoes.db` sobe vazio a
# cada deploy — achado real (2026-08-27): antes desta checagem, isso caía direto no
# caso degenerado de `compute_demeaned_percentiles` (universo vazio) e virava um 500
# mudo, indistinguível de um bug de dado de verdade. Checagem barata (uma contagem,
# nunca chama `build_decisao`) para toda rota nunca devolver isso — 503 com mensagem
# clara, mesma disciplina de estado vazio honesto da Seção 11.3.
# ---------------------------------------------------------------------------

_disponibilidade_cache: bool | None = None

MENSAGEM_INDISPONIVEL = (
    "Módulo de Ações sem dado neste ambiente — o banco (results/acoes.db) está vazio "
    "ou não existe. Isso é esperado em produção sem volume persistente/Postgres "
    "configurado (Seção 11.12 da spec 14): o módulo é local por escolha. Rode "
    "localmente para usá-lo."
)


def _acoes_disponivel(session: Session) -> bool:
    global _disponibilidade_cache
    if _disponibilidade_cache is None:
        contagem = session.execute(select(func.count()).select_from(CvmFiling)).scalar()
        _disponibilidade_cache = bool(contagem and contagem > 0)
    return _disponibilidade_cache


def _exigir_acoes_disponivel(session: Session) -> None:
    if not _acoes_disponivel(session):
        raise HTTPException(status_code=503, detail=MENSAGEM_INDISPONIVEL)


@router.get("/disponivel")
def disponivel():
    """Checagem barata e nunca-gateada (o frontend chama isso antes de decidir se
    mostra a aba Ações, Seção 11.12) — nunca materializa universo, só conta linhas já
    ingeridas."""
    session = _session()
    try:
        return {"disponivel": _acoes_disponivel(session)}
    finally:
        session.close()


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
            if not _acoes_disponivel(session):
                return  # banco vazio (Seção 11.12) — nunca gasta tempo aquecendo o vazio
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
# (Seção 11.3: inaplicavel / indefinido / sem_dado / versao_indisponivel). Reusa só os
# extratores puros de `fatores.py`/`pointintime.py` (mesma regra de cada fator, nunca
# reimplementada aqui) sobre dado já buscado em lote para o ranking inteiro — achado
# real da reescrita em lote (2026-08-29): esta camada refazia a mesma consulta de
# filing/fatores uma vez por empresa, o mesmo N+1 já corrigido em `build_decisao`, só
# que na apresentação em vez do cálculo. Medido: `/api/acoes/mes-atual` levava ~5min
# contra Postgres antes desta correção, mesmo com `build_decisao` já em lote.
# ---------------------------------------------------------------------------


@dataclass
class _DossieRanking:
    """Tudo que `_empresa_para_ranking` precisa, buscado uma vez para o universo
    inteiro antes do laço — não uma vez por empresa."""

    filing_por_cnpj: dict[str, CvmFiling | None]
    linhas_por_cnpj: dict[str, list[CvmFinancialLineItem]]
    existe_algum_item_por_cnpj: dict[str, bool]
    precos: dict[str, float | None]
    fonte_por_ticker: dict[str, str | None]


def _montar_dossie_ranking(session: Session, empresas: list[DecisaoEmpresa], data_decisao: date) -> _DossieRanking:
    tickers = [e.ticker for e in empresas]
    cnpjs = list({e.cnpj for e in empresas})
    filing_por_cnpj = get_latest_filing_as_of_lote(session, cnpjs, "DFP", data_decisao)
    filing_encontrado = {cnpj: f for cnpj, f in filing_por_cnpj.items() if f is not None}
    return _DossieRanking(
        filing_por_cnpj=filing_por_cnpj,
        linhas_por_cnpj=get_line_items_lote(session, filing_encontrado),
        existe_algum_item_por_cnpj=existe_algum_item_lote(session, filing_encontrado),
        precos=preco_as_of_lote(session, tickers, data_decisao),
        fonte_por_ticker=get_fonte_identidade_as_of_lote(session, tickers, data_decisao),
    )


def _montar_dossie_uma_empresa(session: Session, empresa: DecisaoEmpresa, data_decisao: date) -> _DossieRanking:
    """`_montar_dossie_ranking` para uma empresa só — usado pela tela Empresa (Seção
    11.5), que olha uma empresa por vez ao longo de até 12 datas históricas, nunca o
    universo inteiro de uma data. Mesmas funções em lote, listas de um elemento."""
    return _montar_dossie_ranking(session, [empresa], data_decisao)


def _motivo_ausencia(filing: CvmFiling | None, existe_algum_item: bool) -> str:
    if filing is None:
        return "sem_dado"
    if not existe_algum_item:  # CVM listou o filing, mas nenhuma linha dessa versão chegou (Seção 7.5)
        return "versao_indisponivel"
    return "sem_dado"


def _carimbo(filing: CvmFiling | None) -> dict | None:
    if filing is None:
        return None
    return {"data_publicacao": filing.dt_receb.isoformat(), "versao": filing.versao}


def _detalhe_earnings_yield(empresa: DecisaoEmpresa, dossie: _DossieRanking) -> dict:
    filing = dossie.filing_por_cnpj.get(empresa.cnpj)
    linhas = dossie.linhas_por_cnpj.get(empresa.cnpj, [])
    eps = _extrair_eps(empresa.ticker, linhas)
    preco = dossie.precos.get(empresa.ticker)
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
        "motivo": _motivo_ausencia(filing, dossie.existe_algum_item_por_cnpj.get(empresa.cnpj, False)),
    }


def _detalhe_divida_liquida_ebitda(empresa: DecisaoEmpresa, dossie: _DossieRanking) -> dict:
    if not fator_divida_liquida_ebitda_aplicavel(empresa.subsetor_b3):
        return {"valor": None, "percentil": None, "carimbo": None, "motivo": "inaplicavel"}

    filing = dossie.filing_por_cnpj.get(empresa.cnpj)
    linhas = dossie.linhas_por_cnpj.get(empresa.cnpj, [])
    ebit = _extrair_ebit(linhas)
    da = _extrair_da(linhas)
    ebitda = ebit + da if ebit is not None and da is not None else None
    divida = _extrair_divida_liquida(linhas)
    if divida is not None and ebitda is not None:
        valor = divida_liquida_ebitda_raw(divida, ebitda)
        if valor is None:
            return {"valor": None, "percentil": None, "carimbo": _carimbo(filing), "motivo": "indefinido"}
        return {"valor": valor, "percentil": empresa.divida_liquida_ebitda_percentil, "carimbo": _carimbo(filing), "motivo": None}
    return {
        "valor": None,
        "percentil": None,
        "carimbo": None,
        "motivo": _motivo_ausencia(filing, dossie.existe_algum_item_por_cnpj.get(empresa.cnpj, False)),
    }


def _detalhe_roe(empresa: DecisaoEmpresa, dossie: _DossieRanking) -> dict:
    filing = dossie.filing_por_cnpj.get(empresa.cnpj)
    linhas = dossie.linhas_por_cnpj.get(empresa.cnpj, [])
    lucro = _extrair_lucro_liquido_controladores(linhas)
    patrimonio = _extrair_patrimonio_liquido_controladores(linhas)
    if lucro is not None and patrimonio is not None:
        valor = roe_raw(lucro, patrimonio)
        if valor is None:
            return {"valor": None, "percentil": None, "carimbo": _carimbo(filing), "motivo": "indefinido"}
        return {"valor": valor, "percentil": empresa.roe_percentil, "carimbo": _carimbo(filing), "motivo": None}
    return {
        "valor": None,
        "percentil": None,
        "carimbo": None,
        "motivo": _motivo_ausencia(filing, dossie.existe_algum_item_por_cnpj.get(empresa.cnpj, False)),
    }


def _selo_identidade(fonte: str | None) -> str:
    """Três estados (Seção 11.3) — direto da fonte real gravada em `cnpj_ticker_map`
    (Seção 5.6), nunca um heurístico por era: `fca` é a fonte de alta confiança;
    `raiz_propagacao`/`reconciliacao_nome` são as duas fontes de fallback. Empresa fora
    do universo (identidade não resolvida) não passa por aqui — só aparece na tela de
    Saúde do Dado (Seção 11.7)."""
    if fonte is None or fonte == FONTE_ALTA_CONFIANCA:
        return "alta_confianca"
    return "reconciliada"


def _empresa_para_ranking(empresa: DecisaoEmpresa, dossie: _DossieRanking) -> dict:
    return {
        "ticker": empresa.ticker,
        "cnpj": empresa.cnpj,
        "setor_b3": empresa.setor_b3,
        "subsetor_b3": empresa.subsetor_b3,
        "segmento_b3": empresa.segmento_b3,
        "selo_identidade": _selo_identidade(dossie.fonte_por_ticker.get(empresa.ticker)),
        "earnings_yield": _detalhe_earnings_yield(empresa, dossie),
        "divida_liquida_ebitda": _detalhe_divida_liquida_ebitda(empresa, dossie),
        "roe": _detalhe_roe(empresa, dossie),
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
        _exigir_acoes_disponivel(session)
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

        dossie = _montar_dossie_ranking(session, resultado.empresas, data_decisao)
        ranking = [_empresa_para_ranking(e, dossie) for e in resultado.empresas]
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
        _exigir_acoes_disponivel(session)
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
            dossie_historico = _montar_dossie_uma_empresa(session, historica, data)
            linha_do_tempo.append(
                {
                    "data_decisao": data.isoformat(),
                    "earnings_yield": _detalhe_earnings_yield(historica, dossie_historico)["valor"],
                    "divida_liquida_ebitda": _detalhe_divida_liquida_ebitda(historica, dossie_historico)["valor"],
                    "roe": _detalhe_roe(historica, dossie_historico)["valor"],
                }
            )

        historico_cvm = _historico_entregas_cvm(session, empresa.cnpj)
        dossie_hoje = _montar_dossie_uma_empresa(session, empresa, data_decisao)

        return {
            "ticker": empresa.ticker,
            "cnpj": empresa.cnpj,
            "setor_b3": empresa.setor_b3,
            "subsetor_b3": empresa.subsetor_b3,
            "segmento_b3": empresa.segmento_b3,
            "selo_identidade": _selo_identidade(dossie_hoje.fonte_por_ticker.get(empresa.ticker)),
            "vigencia_ticker": _vigencia_ticker(session, empresa.cnpj),
            "fatores_hoje": {
                "earnings_yield": _detalhe_earnings_yield(empresa, dossie_hoje),
                "divida_liquida_ebitda": _detalhe_divida_liquida_ebitda(empresa, dossie_hoje),
                "roe": _detalhe_roe(empresa, dossie_hoje),
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
        _exigir_acoes_disponivel(session)
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
    resultado: DecisaoResultado,
    precos_por_data: dict[date, dict[str, float | None]],
    data_decisao: date,
    meses: int,
    *,
    topo: bool,
    n: int = 10,
) -> float | None:
    """Recebe preços já buscados em lote (`_precos_topo_base_por_data`) — achado da
    reescrita em lote (2026-08-29): esta função, chamada 8 vezes por requisição de
    Histórico (4 horizontes × topo/base), fazia 2×n consultas de preço individuais por
    chamada (até 160 no total), quando os mesmos ~20 tickers (topo ∪ base, os mesmos
    para qualquer horizonte) só precisam de preço em 5 datas distintas no total."""
    ordenadas = sorted(
        (e for e in resultado.empresas if e.score_composto is not None),
        key=lambda e: (-e.score_composto, e.ticker),
    )
    if not ordenadas:
        return None
    alvo = ordenadas[:n] if topo else ordenadas[-n:]
    data_alvo = data_decisao + timedelta(days=30 * meses)
    precos_inicio = precos_por_data.get(data_decisao, {})
    precos_fim = precos_por_data.get(data_alvo, {})
    retornos = []
    for empresa in alvo:
        preco_inicio = precos_inicio.get(empresa.ticker)
        preco_fim = precos_fim.get(empresa.ticker)
        if preco_inicio and preco_fim and preco_inicio > 0:
            retornos.append((preco_fim - preco_inicio) / preco_inicio)
    if not retornos:
        return None
    return sum(retornos) / len(retornos)


def _precos_topo_base_por_data(
    session: Session, resultado: DecisaoResultado, data_decisao: date, meses_horizontes: tuple[int, ...], n: int = 10
) -> dict[date, dict[str, float | None]]:
    ordenadas = sorted(
        (e for e in resultado.empresas if e.score_composto is not None),
        key=lambda e: (-e.score_composto, e.ticker),
    )
    tickers = list({e.ticker for e in (ordenadas[:n] + ordenadas[-n:])}) if ordenadas else []
    datas = [data_decisao] + [data_decisao + timedelta(days=30 * m) for m in meses_horizontes]
    return {data: preco_as_of_lote(session, tickers, data) for data in datas}


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
        _exigir_acoes_disponivel(session)
        resultado = _build_decisao_cacheada(session, data)
        dossie = _montar_dossie_ranking(session, resultado.empresas, data)
        ranking = [_empresa_para_ranking(e, dossie) for e in resultado.empresas]
        ranking.sort(key=lambda e: (e["score_composto"] is None, -(e["score_composto"] or 0), e["ticker"]))

        precos_por_data = _precos_topo_base_por_data(session, resultado, data, (1, 3, 6, 12))
        retorno_topo = {
            f"{meses}m": _retorno_carteira_topo_ou_base(resultado, precos_por_data, data, meses, topo=True)
            for meses in (1, 3, 6, 12)
        }
        retorno_base = {
            f"{meses}m": _retorno_carteira_topo_ou_base(resultado, precos_por_data, data, meses, topo=False)
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
        _exigir_acoes_disponivel(session)
        hoje = date.today()
        lista = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        return preco_as_of_lote(session, lista, hoje)
    finally:
        session.close()
