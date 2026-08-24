"""Fase 1 do módulo de Ações — universo elegível (spec 14, Seção 6). Primeiro teste que
exercita a junção real das três fundações point-in-time (identidade, preço, publicação)
numa única data de decisão.

Fixtures reais:

- `tests/fixtures/cotahist/COTAHIST_A2016_universo_real_extract.ZIP` — linhas reais de
  `ITUB3`/`ITUB4`/`BBAS3`/`PETR3`/`PETR4` (5 pregões líquidos, abril-julho/2016, cobrindo
  a data de decisão 2016-07-15) e `HOOT4` (Hotéis Othon, real, mediana de `VOLTOT` de
  ~R$890 no mesmo período — muito abaixo do piso de R$500 mil, caso real de exclusão por
  liquidez).
- `tests/fixtures/cvm/dfp_master_index_2015_itub_bbas_petr_real_extract.csv` — índice
  mestre real da CVM, exercício 2015-12-31 (publicado 2016), Itaú Unibanco/Banco do
  Brasil/Petrobras — inclui as 3 retificações reais do BB (`dt_receb` 2016-02-25,
  2016-03-28, 2016-06-02), o mesmo padrão de retificação já testado em
  `test_acoes_cvm_pointintime.py` para outro exercício.
- `tests/fixtures/cvm_cadastro/cad_cia_aberta_itub_bbas_petr_real_extract.csv` —
  `SETOR_ATIV` real do cadastro CVM (`Bancos` para Itaú/BB, `Petróleo e Gás` para
  Petrobras).
- `tests/fixtures/b3_setor/getdetail_real_samples.json` — classificação setorial real da
  B3 (Seção 6.2) para as mesmas três empresas, taxonomia de produção.

O teste de junção de fronteira (mesmo relógio nas três camadas) reusa fixtures já
existentes (BBAS3/Banco do Brasil, `COTAHIST_A2024_real_extract.ZIP` +
`dfp_master_index_2024_real_extract.csv`) — mesma empresa real em duas fixtures já
comitadas, sem precisar de dado novo para provar que preço e publicação usam a mesma
convenção de fronteira inclusiva.
"""

import csv
import json
from datetime import date
from pathlib import Path

from sqlalchemy import select

from tradingbot.acoes.b3_setor import ingest_classification_snapshot
from tradingbot.acoes.cnpj_ticker_map import build_cnpj_ticker_map, compute_vigencia, load_fca_identity
from tradingbot.acoes.cotahist_ingestion import ingest_cotahist_year
from tradingbot.acoes.cvm_ingestion import ingest_master_index
from tradingbot.acoes.models import UniversoElegivel, UniversoExclusao
from tradingbot.acoes.persistence import get_session_factory
from tradingbot.acoes.pointintime import get_latest_filing_as_of
from tradingbot.acoes.universo_elegivel import build_universo_elegivel

FIXTURES = Path(__file__).parent / "fixtures"
COTAHIST_2016 = FIXTURES / "cotahist" / "COTAHIST_A2016_universo_real_extract.ZIP"
COTAHIST_2024_BBAS3 = FIXTURES / "cotahist" / "COTAHIST_A2024_real_extract.ZIP"
DFP_2015 = FIXTURES / "cvm" / "dfp_master_index_2015_itub_bbas_petr_real_extract.csv"
DFP_2024_BB = FIXTURES / "cvm" / "dfp_master_index_2024_real_extract.csv"
CADASTRO = FIXTURES / "cvm_cadastro" / "cad_cia_aberta_itub_bbas_petr_real_extract.csv"
B3_SETOR_FIXTURE = FIXTURES / "b3_setor" / "getdetail_real_samples.json"

FCA_DIR = FIXTURES / "fca"
CONFIABLE_FCA_YEARS = [2018, 2019, 2020, 2021, 2022, 2024, 2025]
FCA_PATHS = [FCA_DIR / f"valor_mobiliario_{y}.csv" for y in CONFIABLE_FCA_YEARS]

BB_CNPJ = "00.000.000/0001-91"
ITAU_CNPJ = "60.872.504/0001-23"
PETR_CNPJ = "33.000.167/0001-01"

DATA_DECISAO_2016 = date(2016, 7, 15)


def _session(tmp_path, name="acoes_universo_test.db"):
    factory = get_session_factory(f"sqlite:///{tmp_path}/{name}")
    return factory()


def _setor_by_cnpj():
    with open(CADASTRO, encoding="latin-1") as f:
        return {row["CNPJ_CIA"].strip(): row["SETOR_ATIV"].strip() for row in csv.DictReader(f, delimiter=";")}


def _setup_universo_2016(session):
    """Ingesta as três camadas persistidas de que `build_universo_elegivel` depende:
    preço (COTAHIST 2016), identidade (`cnpj_ticker_map` construído sobre o mesmo
    fixture, via a identidade FCA real)."""
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


def test_materializacao_2016_itub_bbas_petr_com_cnpj_classe_e_filing_corretos(tmp_path):
    """Teste de aceite da Seção 6: materializa o universo em 2016-07-15 (dentro da era
    avaliável já auditada, Seção 5.6) e confirma que os três grandes nomes entram com
    CNPJ resolvido, a classe mais líquida escolhida sobre a menos líquida (`ITUB4` sobre
    `ITUB3`) e o último balanço público (FY2015, publicado em 2016) corretamente juntado
    via `get_latest_filing_as_of` na mesma data de decisão — inclusive a retificação real
    do Banco do Brasil (versão 3, `dt_receb=2016-06-02`, a mais recente publicada antes de
    2016-07-15).

    `min_pregoes_historico=60`: a fixture cobre ~74 pregões reais (abril-julho/2016), não
    um ano inteiro — deliberadamente abaixo do padrão de produção (252, Seção 6), mesmo
    padrão já usado em `test_acoes_cotahist_ingestion.py` (limiar de teste diferente do
    padrão de spec para exercitar o caminho sem exigir fixture do tamanho de produção)."""
    session = _session(tmp_path)
    _setup_universo_2016(session)
    ingest_master_index(session, DFP_2015)

    stats = build_universo_elegivel(
        session, DATA_DECISAO_2016, _setor_by_cnpj(), min_pregoes_historico=60
    )

    assert stats.aceitos == 3  # ITUB4, BBAS3, PETR4 (PETR3/ITUB3 saem por classe secundaria)

    aceitos = {row.ticker: row for row in session.execute(select(UniversoElegivel)).scalars().all()}
    assert set(aceitos) == {"ITUB4", "BBAS3", "PETR4"}

    assert aceitos["ITUB4"].cnpj == ITAU_CNPJ
    assert aceitos["BBAS3"].cnpj == BB_CNPJ
    assert aceitos["PETR4"].cnpj == PETR_CNPJ

    assert aceitos["ITUB4"].setor_ativ == "Bancos"
    assert aceitos["BBAS3"].setor_ativ == "Bancos"
    assert aceitos["PETR4"].setor_ativ == "Petróleo e Gás"

    # taxonomia B3 real (Seção 6.2), lado a lado com a CVM — mesmas três empresas
    assert aceitos["ITUB4"].setor_b3 == "Financeiro"
    assert aceitos["ITUB4"].segmento_b3 == "Bancos"
    assert aceitos["BBAS3"].setor_b3 == "Financeiro"
    assert aceitos["PETR4"].setor_b3 == "Petróleo. Gás e Biocombustíveis"
    assert aceitos["PETR4"].segmento_b3 == "Exploração. Refino e Distribuição"

    excluidos = {row.ticker: row.motivo for row in session.execute(select(UniversoExclusao)).scalars().all()}
    assert excluidos["ITUB3"] == "classe_secundaria"
    assert excluidos["PETR3"] == "classe_secundaria"
    assert excluidos["HOOT4"] == "iliquido"

    # o ultimo balanco publico anterior a data de decisao, juntado na mesma data
    bb_filing = get_latest_filing_as_of(session, BB_CNPJ, "DFP", DATA_DECISAO_2016)
    assert bb_filing.dt_refer == date(2015, 12, 31)
    assert bb_filing.versao == 3  # a retificacao mais recente ja publicada em 2016-07-15
    assert bb_filing.dt_receb == date(2016, 6, 2)

    itau_filing = get_latest_filing_as_of(session, ITAU_CNPJ, "DFP", DATA_DECISAO_2016)
    assert itau_filing.versao == 1
    assert itau_filing.dt_receb == date(2016, 2, 2)

    petr_filing = get_latest_filing_as_of(session, PETR_CNPJ, "DFP", DATA_DECISAO_2016)
    assert petr_filing.versao == 1
    assert petr_filing.dt_receb == date(2016, 3, 21)


def test_precedencia_iliquido_antes_de_identidade_nao_resolvida(tmp_path):
    """Um papel ilíquido E sem identidade resolvida sai por `iliquido` (primeiro da
    cadeia de precedência), nunca por `identidade_nao_resolvida` — `HOOT4` nunca teve
    `CnpjTickerMap` construído nesta sessão isolada (nenhuma chamada a
    `build_cnpj_ticker_map`), então falharia os dois motivos; o resultado prova qual
    vence."""
    session = _session(tmp_path)
    ingest_cotahist_year(session, COTAHIST_2016)
    # identidade nunca construida nesta sessao - toda resolucao de identidade falharia

    build_universo_elegivel(session, DATA_DECISAO_2016, {}, min_pregoes_historico=60)

    motivo = session.execute(
        select(UniversoExclusao.motivo).where(UniversoExclusao.ticker == "HOOT4")
    ).scalar_one()
    assert motivo == "iliquido"


def test_identidade_nao_resolvida_quando_liquido_e_sem_cnpj_ticker_map(tmp_path):
    """`BBAS3` sozinho na sua raiz (sobrevive liquidez + classe trivialmente) mas sem
    nenhum `CnpjTickerMap` construído nesta sessão isolada — sai por
    `identidade_nao_resolvida`, contável, não silenciosamente ausente do universo."""
    session = _session(tmp_path)
    ingest_cotahist_year(session, COTAHIST_2016)

    build_universo_elegivel(session, DATA_DECISAO_2016, {}, min_pregoes_historico=60)

    motivo = session.execute(
        select(UniversoExclusao.motivo).where(UniversoExclusao.ticker == "BBAS3")
    ).scalar_one()
    assert motivo == "identidade_nao_resolvida"


def test_historico_insuficiente_com_limiar_de_producao(tmp_path):
    """Com o limiar de produção (252 pregões, o padrão do módulo), nenhum ticker desta
    fixture (que cobre ~74 pregões reais, não um ano inteiro) tem histórico suficiente —
    prova que o motivo `historico_insuficiente` dispara mesmo depois de sobreviver
    liquidez, classe, identidade e RJ, o último elo da cadeia de precedência."""
    session = _session(tmp_path)
    _setup_universo_2016(session)

    build_universo_elegivel(session, DATA_DECISAO_2016, {})  # limiar padrao: 252

    excluidos = {row.ticker: row.motivo for row in session.execute(select(UniversoExclusao)).scalars().all()}
    assert excluidos["ITUB4"] == "historico_insuficiente"
    assert excluidos["BBAS3"] == "historico_insuficiente"
    assert excluidos["PETR4"] == "historico_insuficiente"

    aceitos = session.execute(select(UniversoElegivel)).scalars().all()
    assert aceitos == []


def test_universo_e_append_only(tmp_path):
    session = _session(tmp_path)
    _setup_universo_2016(session)
    ingest_master_index(session, DFP_2015)

    first = build_universo_elegivel(
        session, DATA_DECISAO_2016, _setor_by_cnpj(), min_pregoes_historico=60
    )
    assert first.aceitos == 3

    second = build_universo_elegivel(
        session, DATA_DECISAO_2016, _setor_by_cnpj(), min_pregoes_historico=60
    )
    assert second.aceitos == 0
    assert second.aceitos_rejeitados_duplicado == 3


def test_junta_fronteira_mesmo_relogio_preco_e_publicacao(tmp_path):
    """Teste de junção de fronteira: `BBAS3`/Banco do Brasil real em duas fixtures já
    comitadas (preço 2024, publicação 2025) — confirma que a camada de preço inclui a
    própria data de decisão quando ela é exatamente o último pregão real do fixture
    (`trade_date <= data_decisao`, igual) e que `get_latest_filing_as_of` inclui a
    própria data de decisão quando ela é exatamente o `dt_receb` real do filing
    (`dt_receb <= data_decisao`, igual) — o mesmo relógio `<=` nas duas camadas, sem
    vazamento de um dia em nenhuma direção."""
    session = _session(tmp_path)
    ingest_cotahist_year(session, COTAHIST_2024_BBAS3)
    ingest_master_index(session, DFP_2024_BB)

    identity = load_fca_identity(FCA_PATHS)
    vigencia = compute_vigencia([COTAHIST_2024_BBAS3])
    build_cnpj_ticker_map(
        session, identity, vigencia, {2024: {"BBAS3": "BRASIL"}}, date(2026, 8, 20)
    )

    ultimo_pregao_real = date(2024, 6, 12)  # ultima linha real da fixture (EDJ)
    stats = build_universo_elegivel(
        session, ultimo_pregao_real, {}, min_pregoes_historico=1, min_volume_mediano=1.0
    )
    assert stats.aceitos == 1
    universo = session.execute(select(UniversoElegivel)).scalar_one()
    assert universo.ticker == "BBAS3"
    assert universo.cnpj == BB_CNPJ
    # nenhum snapshot B3 foi ingerido nesta sessao isolada - fallback declarado, None,
    # nunca adivinhado (Secao 6.2)
    assert universo.setor_b3 is None

    dt_receb_real = date(2025, 2, 19)
    filing_no_dia_exato = get_latest_filing_as_of(session, BB_CNPJ, "DFP", dt_receb_real)
    assert filing_no_dia_exato is not None
    assert filing_no_dia_exato.dt_receb == dt_receb_real

    um_dia_antes = date(2025, 2, 18)
    assert get_latest_filing_as_of(session, BB_CNPJ, "DFP", um_dia_antes) is None
