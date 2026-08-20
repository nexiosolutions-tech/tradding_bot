"""Fase 1 do módulo de Ações — ingestão do índice mestre CVM e consulta point-in-time
(spec 14, Seção 5.1/5.2). Fixtures em `tests/fixtures/cvm/` são extratos reais dos
arquivos baixados de `dados.cvm.gov.br` em 2026-08-20 (Banco do Brasil e BRB Banco de
Brasília, exercício 2024-12-31) — não dado sintético, mesma disciplina do resto da spec.
"""

from datetime import date
from pathlib import Path

from tradingbot.acoes.cvm_ingestion import ingest_line_items_for_cnpj, ingest_master_index
from tradingbot.acoes.persistence import get_session_factory
from tradingbot.acoes.pointintime import get_filing_as_of, get_line_items_as_of

FIXTURES = Path(__file__).parent / "fixtures" / "cvm"
BB_CNPJ = "00.000.000/0001-91"
BRB_CNPJ = "00.000.208/0001-00"


def _session(tmp_path):
    factory = get_session_factory(f"sqlite:///{tmp_path}/acoes_test.db")
    return factory()


def test_ingest_master_index_is_append_only(tmp_path):
    session = _session(tmp_path)
    csv_path = FIXTURES / "dfp_master_index_2024_real_extract.csv"

    first = ingest_master_index(session, csv_path)
    assert first.inserted == 4  # BB (1 versão) + BRB (3 versões)
    assert first.rejected_duplicate == 0

    second = ingest_master_index(session, csv_path)
    assert second.inserted == 0
    assert second.rejected_duplicate == 4


def test_banco_do_brasil_as_of_query_real_data(tmp_path):
    """O teste de aceite da Seção 5.2, contra o dado real: consulta em 2025-02-18 não
    retorna o exercício 2024; em 2025-02-19 (dt_receb real) retorna."""
    session = _session(tmp_path)
    ingest_master_index(session, FIXTURES / "dfp_master_index_2024_real_extract.csv")

    before = get_filing_as_of(session, BB_CNPJ, date(2024, 12, 31), "DFP", date(2025, 2, 18))
    assert before is None

    after = get_filing_as_of(session, BB_CNPJ, date(2024, 12, 31), "DFP", date(2025, 2, 19))
    assert after is not None
    assert after.versao == 1
    assert after.dt_receb == date(2025, 2, 19)


def test_fuso_fronteira_dt_receb_igual_data_decisao(tmp_path):
    """Convenção de fronteira decidida na Seção 5.2: `dt_receb == data_decisao` conta
    como disponível (`<=`, não `<`). Este teste documenta a escolha explicitamente —
    é o mesmo caso do teste do BB acima, isolado para deixar a convenção auditável por
    nome do teste, não um efeito colateral de outro caso."""
    session = _session(tmp_path)
    ingest_master_index(session, FIXTURES / "dfp_master_index_2024_real_extract.csv")

    filing = get_filing_as_of(session, BB_CNPJ, date(2024, 12, 31), "DFP", date(2025, 2, 19))
    assert filing is not None
    assert filing.dt_receb == date(2025, 2, 19)


def test_retificacao_data_entre_publicacoes_ve_versao_antiga(tmp_path):
    """O teste que a maioria dos sistemas erra: BRB Banco de Brasília retificou o mesmo
    exercício (2024-12-31) três vezes (dt_receb real: 2025-04-09, 2025-04-10, 2025-06-30).
    Uma consulta com data *entre* duas publicações precisa ver a versão vigente naquela
    data, nunca a retificação que ainda não existia do ponto de vista da data consultada."""
    session = _session(tmp_path)
    ingest_master_index(session, FIXTURES / "dfp_master_index_2024_real_extract.csv")
    dt_refer = date(2024, 12, 31)

    # antes de qualquer versão existir
    assert get_filing_as_of(session, BRB_CNPJ, dt_refer, "DFP", date(2025, 4, 8)) is None

    # exatamente na publicação da v1
    v1 = get_filing_as_of(session, BRB_CNPJ, dt_refer, "DFP", date(2025, 4, 9))
    assert v1.versao == 1

    # entre v1 e v2: ainda vê v1, não v2 (o teste decisivo)
    still_v1 = get_filing_as_of(session, BRB_CNPJ, dt_refer, "DFP", date(2025, 4, 9))
    assert still_v1.versao == 1

    # exatamente na publicação da v2
    v2 = get_filing_as_of(session, BRB_CNPJ, dt_refer, "DFP", date(2025, 4, 10))
    assert v2.versao == 2

    # entre v2 e v3 (mais de dois meses depois): ainda vê v2, não v3
    still_v2 = get_filing_as_of(session, BRB_CNPJ, dt_refer, "DFP", date(2025, 6, 29))
    assert still_v2.versao == 2

    # exatamente na publicação da v3
    v3 = get_filing_as_of(session, BRB_CNPJ, dt_refer, "DFP", date(2025, 6, 30))
    assert v3.versao == 3

    # muito depois: continua vendo a mais recente (v3), não regride
    still_v3 = get_filing_as_of(session, BRB_CNPJ, dt_refer, "DFP", date(2026, 1, 1))
    assert still_v3.versao == 3


def test_ordem_exerc_so_devolve_exercicio_corrente(tmp_path):
    """Confirma, contra dado real do BB (DRE consolidado, 2024-12-31), que a consulta
    devolve só `ÚLTIMO` — nunca `PENÚLTIMO`, o comparativo do ano anterior embutido no
    mesmo filing (mesmo CD_CONTA aparece duas vezes na fonte, um valor cada)."""
    session = _session(tmp_path)
    ingest_master_index(session, FIXTURES / "dfp_master_index_2024_real_extract.csv")
    ingest_line_items_for_cnpj(
        session, FIXTURES / "dre_con_2024_bb_real_extract.csv", BB_CNPJ
    )

    items = get_line_items_as_of(session, BB_CNPJ, date(2024, 12, 31), "DFP", date(2025, 2, 19))

    assert len(items) == 3  # os 3 CD_CONTA do extrato, só o lado ÚLTIMO de cada um
    assert all(item.ordem_exerc == "ÚLTIMO" for item in items)

    by_conta = {item.cd_conta: item.vl_conta for item in items}
    # valores reais do exercício 2024 (ÚLTIMO) — não os de 2023 (PENÚLTIMO) do mesmo filing
    assert by_conta["3.01"] == 273505274.0
    assert by_conta["3.03"] == 104514447.0
    assert by_conta["3.11"] == 29171564.0


def test_line_items_vazio_antes_do_filing_existir(tmp_path):
    """Antes da data de publicação real, nenhum filing está visível — a consulta de itens
    devolve lista vazia, não erro nem dado de uma versão futura."""
    session = _session(tmp_path)
    ingest_master_index(session, FIXTURES / "dfp_master_index_2024_real_extract.csv")
    ingest_line_items_for_cnpj(
        session, FIXTURES / "dre_con_2024_bb_real_extract.csv", BB_CNPJ
    )

    items = get_line_items_as_of(session, BB_CNPJ, date(2024, 12, 31), "DFP", date(2025, 2, 18))
    assert items == []
