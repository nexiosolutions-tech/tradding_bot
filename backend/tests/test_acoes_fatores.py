"""Fase 2 do módulo de Ações — primeiro fator ponta a ponta: earnings yield (spec 14,
Seção 7). Primeira camada de decisão de modelagem, não de fundação de dado — o rigor
aqui é "tem justificativa econômica?", não "bate com a fonte?".

Fixtures reais (mesmas três empresas do teste de aceite da Seção 6, mesma data de
decisão 2016-07-15, para que os números deste módulo sejam auditáveis contra o mesmo
universo já fechado):

- `tests/fixtures/cvm/dre_con_2015_itub_bbas_petr_eps_real_extract.csv` — Lucro Básico
  por Ação real (`CD_CONTA` `3.99.01.01`/`.02`), exercício 2015 (publicado 2016), Itaú
  (ON=PN=4,30), Banco do Brasil (ON=5,03 — só tem classe ON) e **Petrobras (ON=PN=-2,67,
  prejuízo real** — queda do petróleo + baixas contábeis do período, o caso que earnings
  yield existe para tratar sem inverter sinal).
- Preço real: `COTAHIST_A2016_universo_real_extract.ZIP` (mesma fixture da Seção 6) —
  fechamento real em 2016-07-15: `ITUB4`=R$33,46, `BBAS3`=R$19,26, `PETR4`=R$11,02.
"""

from datetime import date
from pathlib import Path

import pytest

from tradingbot.acoes.cnpj_ticker_map import build_cnpj_ticker_map, compute_vigencia, load_fca_identity
from tradingbot.acoes.cotahist_ingestion import ingest_cotahist_year
from tradingbot.acoes.cvm_ingestion import ingest_line_items_for_cnpj, ingest_master_index
from tradingbot.acoes.fatores import (
    FactorInput,
    compute_demeaned_percentiles,
    earnings_yield_raw,
    get_eps_as_of,
    winsorize,
)
from tradingbot.acoes.persistence import get_session_factory

FIXTURES = Path(__file__).parent / "fixtures"
COTAHIST_2016 = FIXTURES / "cotahist" / "COTAHIST_A2016_universo_real_extract.ZIP"
DFP_2015 = FIXTURES / "cvm" / "dfp_master_index_2015_itub_bbas_petr_real_extract.csv"
DRE_2015_EPS = FIXTURES / "cvm" / "dre_con_2015_itub_bbas_petr_eps_real_extract.csv"

FCA_DIR = FIXTURES / "fca"
CONFIABLE_FCA_YEARS = [2018, 2019, 2020, 2021, 2022, 2024, 2025]
FCA_PATHS = [FCA_DIR / f"valor_mobiliario_{y}.csv" for y in CONFIABLE_FCA_YEARS]

BB_CNPJ = "00.000.000/0001-91"
ITAU_CNPJ = "60.872.504/0001-23"
PETR_CNPJ = "33.000.167/0001-01"

DATA_DECISAO = date(2016, 7, 15)

# fechamento real na propria data de decisao (fixture COTAHIST 2016, ja usada na Secao 6)
PRECO_REAL = {"ITUB4": 33.46, "BBAS3": 19.26, "PETR4": 11.02}


def _session(tmp_path):
    factory = get_session_factory(f"sqlite:///{tmp_path}/acoes_fatores_test.db")
    return factory()


def _setup(session):
    ingest_master_index(session, DFP_2015)
    for cnpj in (BB_CNPJ, ITAU_CNPJ, PETR_CNPJ):
        ingest_line_items_for_cnpj(session, DRE_2015_EPS, cnpj)


def test_get_eps_as_of_valores_reais(tmp_path):
    """Confirma o Lucro Básico por Ação real das três empresas, na data de decisão que
    fecha a Seção 6 — inclusive o prejuízo real da Petrobras, não invertido nem
    arredondado para zero."""
    session = _session(tmp_path)
    _setup(session)

    assert get_eps_as_of(session, ITAU_CNPJ, "ITUB4", DATA_DECISAO) == pytest.approx(4.30)
    assert get_eps_as_of(session, BB_CNPJ, "BBAS3", DATA_DECISAO) == pytest.approx(5.03)
    assert get_eps_as_of(session, PETR_CNPJ, "PETR4", DATA_DECISAO) == pytest.approx(-2.67)


def test_get_eps_as_of_none_antes_da_publicacao(tmp_path):
    """Antes do balanço de 2015 ser publicado (o mais cedo dos três, Itaú em
    2016-02-02), nenhum EPS está visível — mesma disciplina point-in-time da Seção 5.2,
    não um erro do fator."""
    session = _session(tmp_path)
    _setup(session)

    assert get_eps_as_of(session, ITAU_CNPJ, "ITUB4", date(2016, 2, 1)) is None


def test_earnings_yield_raw_petrobras_negativo_nao_invertido():
    """O caso central da métrica: earnings yield de empresa deficitária é negativo, não
    "a mais barata" — o erro clássico que P/L bruto cometeria."""
    yield_petr = earnings_yield_raw(-2.67, 11.02)
    yield_itub = earnings_yield_raw(4.30, 33.46)
    assert yield_petr < 0
    assert yield_petr < yield_itub


def test_winsorize_amostra_pequena_nao_corta_extremos():
    """Regressão do bug achado nesta rodada: com `n=3` e índice por truncamento
    (`int`), o percentil 99 mapeava para o valor do meio, não o máximo, cortando o maior
    valor de uma amostra pequena incorretamente. Com arredondamento (`round`), amostra
    pequena não perde nada aos percentis 1/99 por construção."""
    valores = [-0.24, 0.13, 0.26]
    resultado = winsorize(valores, lower_pct=0.01, upper_pct=0.99)
    assert resultado == valores


def test_winsorize_corta_cauda_com_amostra_grande():
    valores = list(range(1, 101))  # 1..100
    resultado = winsorize([float(v) for v in valores], lower_pct=0.01, upper_pct=0.99)
    assert min(resultado) > 1.0
    assert max(resultado) < 100.0


def test_compute_demeaned_percentiles_universo_real_2016(tmp_path):
    """Ponta a ponta com dado real: as três empresas do universo de 2016-07-15, earnings
    yield real, agrupadas pelo setor B3 real (Seção 6.2). Com só 3 empresas no universo
    elegível desta fixture, nenhum nível da hierarquia (segmento/subsetor/setor) atinge a
    população mínima de 3 sozinho — todas caem no bucket `universo`, resultado real e
    esperado dado o tamanho do universo aqui, não um bug. Petrobras (earnings yield
    negativo real) fica com o percentil mais baixo, na ponta oposta de Banco do Brasil
    (o yield mais alto) — o ranking não inverte o sinal do prejuízo real."""
    session = _session(tmp_path)
    _setup(session)

    itens = [
        FactorInput(
            ticker="ITUB4",
            raw_value=earnings_yield_raw(4.30, PRECO_REAL["ITUB4"]),
            segmento="Bancos", subsetor="Intermediários Financeiros", setor="Financeiro",
        ),
        FactorInput(
            ticker="BBAS3",
            raw_value=earnings_yield_raw(5.03, PRECO_REAL["BBAS3"]),
            segmento="Bancos", subsetor="Intermediários Financeiros", setor="Financeiro",
        ),
        FactorInput(
            ticker="PETR4",
            raw_value=earnings_yield_raw(-2.67, PRECO_REAL["PETR4"]),
            segmento="Exploração. Refino e Distribuição",
            subsetor="Petróleo. Gás e Biocombustíveis",
            setor="Petróleo. Gás e Biocombustíveis",
        ),
    ]

    resultados = {r.ticker: r for r in compute_demeaned_percentiles(itens)}

    assert resultados["ITUB4"].bucket_usado == "universo"
    assert resultados["BBAS3"].bucket_usado == "universo"
    assert resultados["PETR4"].bucket_usado == "universo"

    assert resultados["PETR4"].percentil < resultados["ITUB4"].percentil < resultados["BBAS3"].percentil
    assert resultados["PETR4"].demeaned < 0
    assert not any(r.imputado for r in resultados.values())


def test_compute_demeaned_percentiles_sobe_hierarquia_quando_bucket_fino_e_pequeno():
    """Mecanismo de fallback isolado (valores ilustrativos, não dado real de empresa —
    o objetivo é provar que o algoritmo sobe `segmento` -> `subsetor` -> `setor` ->
    `universo` corretamente, não afirmar um fato de mercado). Dois segmentos com 2
    empresas cada (abaixo do piso de 3) dentro do mesmo setor com 4 empresas no total —
    o bucket usado deve ser `setor`, não `segmento` nem `universo`."""
    itens = [
        FactorInput("A1", 10.0, segmento="SegA", subsetor="SubA", setor="SetorX"),
        FactorInput("A2", 12.0, segmento="SegA", subsetor="SubA", setor="SetorX"),
        FactorInput("B1", 20.0, segmento="SegB", subsetor="SubB", setor="SetorX"),
        FactorInput("B2", 22.0, segmento="SegB", subsetor="SubB", setor="SetorX"),
    ]
    resultados = {r.ticker: r for r in compute_demeaned_percentiles(itens, min_bucket_size=3)}
    assert all(r.bucket_usado == "setor" for r in resultados.values())


def test_dado_faltante_imputado_pela_mediana_nao_excluido():
    """Empresa sem dado (`raw_value=None`) é imputada pela mediana do universo, não
    excluída — regra declarada da Seção 7, evita viés de seleção sistemático contra
    empresa de reporte mais fraco."""
    itens = [
        FactorInput("COM_DADO_1", 10.0, segmento="Seg", subsetor="Sub", setor="Setor"),
        FactorInput("COM_DADO_2", 20.0, segmento="Seg", subsetor="Sub", setor="Setor"),
        FactorInput("COM_DADO_3", 30.0, segmento="Seg", subsetor="Sub", setor="Setor"),
        FactorInput("SEM_DADO", None, segmento="Seg", subsetor="Sub", setor="Setor"),
    ]
    resultados = {r.ticker: r for r in compute_demeaned_percentiles(itens)}
    assert resultados["SEM_DADO"].raw_value == pytest.approx(20.0)  # mediana de [10,20,30]
    assert resultados["SEM_DADO"].imputado is True
    assert resultados["COM_DADO_1"].imputado is False
