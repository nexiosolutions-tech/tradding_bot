"""API do módulo de Ações — spec 14, Seção 11. Reusa a fixture real de
`test_acoes_decisao.py` (ITUB4/BBAS3/PETR4, 2016-07-15) — a orquestração universo+
fatores já é travada lá; aqui o alvo é a camada HTTP (shape de resposta, carimbo nunca
ausente quando há valor, estados de célula vazia, cache em processo)."""

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tradingbot.acoes.b3_setor import ingest_classification_snapshot
from tradingbot.acoes.cnpj_ticker_map import build_cnpj_ticker_map, compute_vigencia, load_fca_identity
from tradingbot.acoes.cotahist_ingestion import ingest_cotahist_year
from tradingbot.acoes.cvm_ingestion import ingest_line_items_for_cnpj, ingest_master_index

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

FCA_DIR = FIXTURES / "fca"
CONFIABLE_FCA_YEARS = [2018, 2019, 2020, 2021, 2022, 2024, 2025]
FCA_PATHS = [FCA_DIR / f"valor_mobiliario_{y}.csv" for y in CONFIABLE_FCA_YEARS]

BB_CNPJ = "00.000.000/0001-91"
ITAU_CNPJ = "60.872.504/0001-23"
PETR_CNPJ = "33.000.167/0001-01"

DATA_DECISAO = date(2016, 7, 15)


def _popular_fixture(session):
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


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ACOES_DATABASE_URL", f"sqlite:///{tmp_path}/acoes-api-test.db")

    import tradingbot.acoes.api as acoes_api
    import tradingbot.acoes.persistence as acoes_persistence

    monkeypatch.setattr(acoes_persistence, "_default_session_factory", None)
    acoes_api._cache_decisao.clear()
    monkeypatch.setattr(acoes_api, "DATAS_DECISAO_SERIE", (DATA_DECISAO,))
    monkeypatch.setattr(acoes_api, "BACKTEST_RESULT_PATH", tmp_path / "acoes_backtest.json")
    # fixture leve (mesmo dado real de test_acoes_decisao.py) nao tem 252 pregoes de
    # historico - mesmo ajuste que os testes de build_decisao ja precisam.
    monkeypatch.setattr(acoes_api, "MIN_PREGOES_HISTORICO", 60)
    # a thread de aquecimento correria contra as asserções deste arquivo sobre o
    # estado do cache logo após o startup (race de timing, não determinístico).
    monkeypatch.setattr(acoes_api, "WARMUP_HABILITADO", False)

    session = acoes_persistence.get_session()
    _popular_fixture(session)
    session.close()

    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/bot-api-test.db")

    import tradingbot.api.app as api_app

    monkeypatch.setattr(api_app, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(api_app, "MODELS_DIR", tmp_path / "results" / "models")
    monkeypatch.setattr(api_app, "LEARNINGS_DIR", tmp_path / "learnings")
    monkeypatch.setattr(api_app, "CHANGES_DIR", tmp_path / "changes")

    with TestClient(api_app.app) as test_client:
        yield test_client

    acoes_api._cache_decisao.clear()


def test_mes_atual_devolve_ranking_com_carimbo_em_todo_valor_presente(client):
    resp = client.get("/api/acoes/mes-atual", params={"ano": 2016, "mes": 7})
    assert resp.status_code == 200
    body = resp.json()

    assert body["data_decisao"] == "2016-07-15"
    assert body["elegiveis"] == 3
    tickers = {e["ticker"] for e in body["ranking"]}
    assert tickers == {"ITUB4", "BBAS3", "PETR4"}

    for empresa in body["ranking"]:
        for fator in ("earnings_yield", "divida_liquida_ebitda", "roe"):
            detalhe = empresa[fator]
            # regra da Secao 11.3: numero de balanco sem carimbo nao pode existir
            if detalhe["valor"] is not None:
                assert detalhe["carimbo"] is not None
                assert detalhe["motivo"] is None
            else:
                assert detalhe["carimbo"] is None
                assert detalhe["motivo"] in ("inaplicavel", "indefinido", "sem_dado", "versao_indisponivel")


def test_mes_atual_earnings_yield_implausivel_vira_indefinido(client, monkeypatch):
    """Achado real (Seção 13, 2026-08-27): EPS implausível na fonte precisa virar
    `indefinido` na API, nunca um número exposto sem contexto — a mesma regra de
    carimbo/motivo do resto da Seção 11.3. Limiar reduzido para 0,25 (abaixo do
    earnings yield real de BBAS3 nesta fixture, 26,1%, mas acima de ITUB4 12,9% e
    |PETR4| 24,2%) — filtra só uma empresa, não todas, para não bater no caso
    degenerado (nenhum valor real no bucket para imputar as demais)."""
    import tradingbot.acoes.fatores as fatores

    monkeypatch.setattr(fatores, "EARNINGS_YIELD_IMPLAUSIVEL_LIMIAR", 0.25)

    resp = client.get("/api/acoes/mes-atual", params={"ano": 2016, "mes": 7})
    body = resp.json()
    por_ticker = {e["ticker"]: e for e in body["ranking"]}

    detalhe_bbas3 = por_ticker["BBAS3"]["earnings_yield"]
    assert detalhe_bbas3["valor"] is None
    assert detalhe_bbas3["motivo"] == "indefinido"
    assert detalhe_bbas3["carimbo"] is not None  # sabe-se a data do filing, mesmo indefinido

    assert por_ticker["ITUB4"]["earnings_yield"]["valor"] is not None
    assert por_ticker["PETR4"]["earnings_yield"]["valor"] is not None


def test_mes_atual_dl_ebitda_inaplicavel_para_bancos(client):
    resp = client.get("/api/acoes/mes-atual", params={"ano": 2016, "mes": 7})
    body = resp.json()
    por_ticker = {e["ticker"]: e for e in body["ranking"]}

    assert por_ticker["ITUB4"]["divida_liquida_ebitda"]["motivo"] == "inaplicavel"
    assert por_ticker["BBAS3"]["divida_liquida_ebitda"]["motivo"] == "inaplicavel"
    assert por_ticker["PETR4"]["divida_liquida_ebitda"]["valor"] is not None


def test_mes_atual_selo_identidade_presente(client):
    resp = client.get("/api/acoes/mes-atual", params={"ano": 2016, "mes": 7})
    body = resp.json()
    for empresa in body["ranking"]:
        assert empresa["selo_identidade"] in ("alta_confianca", "reconciliada")


def test_mes_atual_distribuicao_setorial_soma_o_total(client):
    resp = client.get("/api/acoes/mes-atual", params={"ano": 2016, "mes": 7})
    body = resp.json()
    assert sum(s["contagem"] for s in body["distribuicao_setorial"]) == body["elegiveis"]


def test_empresa_detalhe_traz_ficha_completa(client):
    resp = client.get("/api/acoes/empresas/PETR4", params={"ano": 2016, "mes": 7})
    assert resp.status_code == 200
    body = resp.json()

    assert body["ticker"] == "PETR4"
    assert body["cnpj"] == PETR_CNPJ
    assert body["fatores_hoje"]["earnings_yield"]["valor"] is not None
    assert len(body["vigencia_ticker"]) >= 1
    assert len(body["historico_entregas_cvm"]) >= 1
    assert len(body["linha_do_tempo_conhecimento"]) == 1
    assert body["linha_do_tempo_conhecimento"][0]["data_decisao"] == "2016-07-15"


def test_empresa_detalhe_404_para_ticker_fora_do_universo(client):
    resp = client.get("/api/acoes/empresas/AAAA3", params={"ano": 2016, "mes": 7})
    assert resp.status_code == 404


def test_saude_do_dado_reporta_fontes_e_cobertura(client):
    resp = client.get("/api/acoes/saude-do-dado", params={"ano": 2016, "mes": 7})
    assert resp.status_code == 200
    body = resp.json()

    assert set(body["fontes"].keys()) == {"cvm_dfp_itr", "cotahist", "cdi", "ipca"}
    assert len(body["cobertura_por_ano"]) == 1
    assert body["cobertura_por_ano"][0]["elegiveis"] == 3
    assert "exclusoes_do_mes" in body
    assert body["backtest"] is None  # nenhum resultado persistido nesta fixture


def test_historico_lista_as_datas_configuradas(client):
    resp = client.get("/api/acoes/historico")
    assert resp.status_code == 200
    assert resp.json()["datas_decisao"] == ["2016-07-15"]


def test_historico_detalhe_reconstroi_e_calcula_retorno_subsequente(client):
    resp = client.get("/api/acoes/historico/2016-07-15")
    assert resp.status_code == 200
    body = resp.json()

    assert body["elegiveis"] == 3
    assert set(body["retorno_subsequente_topo_10"].keys()) == {"1m", "3m", "6m", "12m"}


def test_historico_detalhe_404_para_data_fora_da_serie(client):
    resp = client.get("/api/acoes/historico/2020-01-01")
    assert resp.status_code == 404


def test_historico_detalhe_400_para_data_invalida(client):
    resp = client.get("/api/acoes/historico/nao-e-uma-data")
    assert resp.status_code == 400


def test_cache_de_decisao_reusa_resultado_entre_requisicoes(client):
    import tradingbot.acoes.api as acoes_api

    assert DATA_DECISAO not in acoes_api._cache_decisao
    client.get("/api/acoes/historico/2016-07-15")
    assert DATA_DECISAO in acoes_api._cache_decisao


def test_precos_devolve_ultima_cotacao_conhecida_por_ticker(client):
    resp = client.get("/api/acoes/precos", params={"tickers": "PETR4,BBAS3,NAOEXISTE9"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["PETR4"] is not None
    assert body["BBAS3"] is not None
    assert body["NAOEXISTE9"] is None
