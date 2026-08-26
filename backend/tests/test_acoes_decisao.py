"""Fase 2 do módulo de Ações — o driver de uma data de decisão (spec 14, Seção 7.6).
Primeira vez que os três fatores + `compute_score_composto` rodam através de uma única
chamada (`build_decisao`), sobre o mesmo universo materializado pela Seção 6 — não mais
scripts ad hoc por fator, isolados uns dos outros.

Reusa integralmente as fixtures reais já comitadas para 2016-07-15 (ITUB4/BBAS3/PETR4):
universo elegível (`test_acoes_universo_elegivel.py`), earnings yield
(`test_acoes_fatores.py`), dívida líquida/EBITDA (`test_acoes_fatores_divida_liquida_
ebitda.py`) e ROE (`test_acoes_fatores_roe.py`) — nenhum dado novo, só a orquestração
nova."""

import json
from datetime import date
from pathlib import Path

import pytest

from tradingbot.acoes.b3_setor import ingest_classification_snapshot
from tradingbot.acoes.cnpj_ticker_map import build_cnpj_ticker_map, compute_vigencia, load_fca_identity
from tradingbot.acoes.cotahist_ingestion import ingest_cotahist_year
from tradingbot.acoes.cvm_ingestion import ingest_line_items_for_cnpj, ingest_master_index
from tradingbot.acoes.decisao import build_decisao
from tradingbot.acoes.persistence import get_session_factory

FIXTURES = Path(__file__).parent / "fixtures"
COTAHIST_2016 = FIXTURES / "cotahist" / "COTAHIST_A2016_universo_real_extract.ZIP"
DFP_2015 = FIXTURES / "cvm" / "dfp_master_index_2015_itub_bbas_petr_real_extract.csv"
DRE_2015_EPS = FIXTURES / "cvm" / "dre_con_2015_itub_bbas_petr_eps_real_extract.csv"
LUCRO_2015 = FIXTURES / "cvm" / "dre_con_2015_itub_bbas_petr_lucro_controladores_real_extract.csv"
PATRIMONIO_2015 = FIXTURES / "cvm" / "bpp_con_2015_itub_bbas_petr_patrimonio_real_extract.csv"
EBIT_2015 = FIXTURES / "cvm" / "dre_con_2015_itub_bbas_petr_ebit_real_extract.csv"
DA_2015 = FIXTURES / "cvm" / "dfc_mi_con_2015_petr_da_real_extract.csv"
CAIXA_2015 = FIXTURES / "cvm" / "bpa_con_2015_petr_caixa_real_extract.csv"
DIVIDA_2015 = FIXTURES / "cvm" / "bpp_con_2015_petr_divida_real_extract.csv"
B3_SETOR_FIXTURE = FIXTURES / "b3_setor" / "getdetail_real_samples.json"
CADASTRO = FIXTURES / "cvm_cadastro" / "cad_cia_aberta_itub_bbas_petr_real_extract.csv"

FCA_DIR = FIXTURES / "fca"
CONFIABLE_FCA_YEARS = [2018, 2019, 2020, 2021, 2022, 2024, 2025]
FCA_PATHS = [FCA_DIR / f"valor_mobiliario_{y}.csv" for y in CONFIABLE_FCA_YEARS]

BB_CNPJ = "00.000.000/0001-91"
ITAU_CNPJ = "60.872.504/0001-23"
PETR_CNPJ = "33.000.167/0001-01"

DATA_DECISAO = date(2016, 7, 15)


def _session(tmp_path):
    factory = get_session_factory(f"sqlite:///{tmp_path}/acoes_decisao_test.db")
    return factory()


def _setor_by_cnpj():
    import csv

    with open(CADASTRO, encoding="latin-1") as f:
        return {row["CNPJ_CIA"].strip(): row["SETOR_ATIV"].strip() for row in csv.DictReader(f, delimiter=";")}


def _setup(session):
    ingest_cotahist_year(session, COTAHIST_2016)

    identity = load_fca_identity(FCA_PATHS)
    vigencia = compute_vigencia([COTAHIST_2016])
    tickers_by_year = {
        2016: {
            "ITUB3": "ITAUUNIBANCO",
            "ITUB4": "ITAUUNIBANCO",
            "BBAS3": "BRASIL",
            "PETR3": "PETROBRAS",
            "PETR4": "PETROBRAS",
            "HOOT4": "HOTEIS OTHON",
        }
    }
    build_cnpj_ticker_map(session, identity, vigencia, tickers_by_year, date(2026, 8, 20))

    b3_fixture = json.loads(B3_SETOR_FIXTURE.read_text())
    raw_entries = [v["raw"] | {"codeCVM": v["codeCVM"]} for v in b3_fixture.values()]
    ingest_classification_snapshot(session, raw_entries, date(2026, 8, 21))

    ingest_master_index(session, DFP_2015)
    for cnpj in (ITAU_CNPJ, BB_CNPJ, PETR_CNPJ):
        ingest_line_items_for_cnpj(session, DRE_2015_EPS, cnpj)
        ingest_line_items_for_cnpj(session, LUCRO_2015, cnpj)
        ingest_line_items_for_cnpj(session, PATRIMONIO_2015, cnpj)
        ingest_line_items_for_cnpj(session, EBIT_2015, cnpj)
    ingest_line_items_for_cnpj(session, DA_2015, PETR_CNPJ)
    ingest_line_items_for_cnpj(session, CAIXA_2015, PETR_CNPJ)
    ingest_line_items_for_cnpj(session, DIVIDA_2015, PETR_CNPJ)


def test_build_decisao_materializa_universo_e_computa_score_das_tres_empresas(tmp_path):
    """As três sobreviventes da Seção 6 (ITUB4/BBAS3/PETR4) saem com score composto —
    prova que `build_decisao` de fato liga universo + fatores + `compute_score_composto`
    numa única chamada, sobre dado 100% real já comitado."""
    session = _session(tmp_path)
    _setup(session)

    resultado = build_decisao(session, DATA_DECISAO, _setor_by_cnpj(), min_pregoes_historico=60)

    assert resultado.universo_stats.aceitos == 3
    tickers = {e.ticker for e in resultado.empresas}
    assert tickers == {"ITUB4", "BBAS3", "PETR4"}

    por_ticker = {e.ticker: e for e in resultado.empresas}
    for ticker in ("ITUB4", "BBAS3", "PETR4"):
        assert por_ticker[ticker].score_composto is not None
        assert por_ticker[ticker].tem_fator_real is True

    assert resultado.n_score_computavel == 3


def test_divida_liquida_ebitda_inaplicavel_para_bancos_nunca_entra_como_none(tmp_path):
    """ITUB4/BBAS3 (subsetor "Intermediários Financeiros", inaplicável pela matriz da
    Seção 7.2) não recebem percentil de dívida líquida/EBITDA — `None` por
    inaplicabilidade, nunca confundido com `None` por dado faltante (que seria
    imputado). PETR4, subsetor aplicável, recebe percentil real."""
    session = _session(tmp_path)
    _setup(session)

    resultado = build_decisao(session, DATA_DECISAO, _setor_by_cnpj(), min_pregoes_historico=60)
    por_ticker = {e.ticker: e for e in resultado.empresas}

    assert por_ticker["ITUB4"].divida_liquida_ebitda_percentil is None
    assert por_ticker["BBAS3"].divida_liquida_ebitda_percentil is None
    assert por_ticker["PETR4"].divida_liquida_ebitda_percentil is not None

    # renormalizacao (Secao 7.2): banco sem o fator ainda tem score, via os outros dois
    assert por_ticker["ITUB4"].score_composto is not None
    assert por_ticker["BBAS3"].score_composto is not None


def test_build_decisao_nao_reimplementa_compute_score_composto(tmp_path, monkeypatch):
    """`build_decisao` precisa chamar `compute_score_composto` de verdade, não uma
    reimplementação equivalente — o risco de divergência que a Seção 7.6 registra.
    Prova via monkeypatch: se a função do módulo `fatores` for substituída, o resultado
    do driver muda de acordo — só é possível se o driver de fato delega, em vez de
    calcular por conta própria."""
    import tradingbot.acoes.decisao as decisao_module

    session = _session(tmp_path)
    _setup(session)

    monkeypatch.setattr(decisao_module, "compute_score_composto", lambda percentis, pesos: 42.0)

    resultado = build_decisao(session, DATA_DECISAO, _setor_by_cnpj(), min_pregoes_historico=60)
    assert all(e.score_composto == 42.0 for e in resultado.empresas)
