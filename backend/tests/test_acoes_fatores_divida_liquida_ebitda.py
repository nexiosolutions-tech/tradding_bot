"""Fase 2 do módulo de Ações — segundo fator ponta a ponta: dívida líquida/EBITDA (spec
14, Seção 7.2). Primeiro fator a exercitar a matriz de aplicabilidade de verdade e o
point-in-time de múltiplas demonstrações (DRE + DFC + BP).

Fixtures reais, exercício 2015 (publicado 2016), mesmas três empresas dos testes
anteriores da Fase 2:

- `dre_con_2015_itub_bbas_petr_ebit_real_extract.csv` — `CD_CONTA "3.05"` das três
  empresas. Achado real que motiva a verificação de `DS_CONTA` em `get_ebit_as_of`: para
  Petrobras é `"Resultado Antes do Resultado Financeiro e dos Tributos"` (EBIT real,
  -R$13.188 milhões — a Petrobras teve **prejuízo operacional** em 2015, não só líquido);
  para Itaú e Banco do Brasil (instituições financeiras) o mesmo código é
  `"Resultado Antes dos Tributos sobre o Lucro"` — outra conta inteiramente, mesmo com
  `ST_CONTA_FIXA='S'` nas duas.
- `dfc_mi_con_2015_petr_da_real_extract.csv` — grupo de reconciliação `6.01.01.*` da DFC
  método indireto da Petrobras (12 linhas reais), só uma (`6.01.01.04`, "Depreciação,
  Depleção e Amortização", R$38.574 milhões) casa com as palavras-chave de D&A — prova
  real de que a busca por conteúdo (não por código fixo) resolve sem ambiguidade.
- `bpa_con_2015_petr_caixa_real_extract.csv` / `bpp_con_2015_petr_divida_real_extract.csv`
  — caixa (R$97.845 milhões) e dívida circulante+não circulante (R$57.382 + R$435.467
  milhões) reais da Petrobras.

EBITDA real da Petrobras = EBIT + D&A = -13.188.000 + 38.574.000 = R$25.386.000 (mil).
Dívida líquida real = (57.382.000 + 435.467.000) - 97.845.000 = R$395.004.000 (mil).
Dívida líquida/EBITDA real ≈ 15,56 — alavancagem real e severa (2015 foi o ano do
rebaixamento de rating da Petrobras por agências internacionais).
"""

from datetime import date
from pathlib import Path

import pytest

from tradingbot.acoes.cvm_ingestion import ingest_line_items_for_cnpj, ingest_master_index
from tradingbot.acoes.fatores import (
    DIVIDA_LIQUIDA_EBITDA_SUBSETORES_INAPLICAVEIS,
    PesoFator,
    compute_score_composto,
    divida_liquida_ebitda_raw,
    fator_divida_liquida_ebitda_aplicavel,
    get_divida_liquida_as_of,
    get_ebit_as_of,
    get_ebitda_as_of,
)
from tradingbot.acoes.persistence import get_session_factory

FIXTURES = Path(__file__).parent / "fixtures"
DFP_2015 = FIXTURES / "cvm" / "dfp_master_index_2015_itub_bbas_petr_real_extract.csv"
EBIT_2015 = FIXTURES / "cvm" / "dre_con_2015_itub_bbas_petr_ebit_real_extract.csv"
DA_2015 = FIXTURES / "cvm" / "dfc_mi_con_2015_petr_da_real_extract.csv"
CAIXA_2015 = FIXTURES / "cvm" / "bpa_con_2015_petr_caixa_real_extract.csv"
DIVIDA_2015 = FIXTURES / "cvm" / "bpp_con_2015_petr_divida_real_extract.csv"

BB_CNPJ = "00.000.000/0001-91"
ITAU_CNPJ = "60.872.504/0001-23"
PETR_CNPJ = "33.000.167/0001-01"

DATA_DECISAO = date(2016, 7, 15)

# valores reais, verificados contra os arquivos brutos antes de escrever qualquer teste
EBIT_REAL_PETR = -13_188_000.0
DA_REAL_PETR = 38_574_000.0
EBITDA_REAL_PETR = EBIT_REAL_PETR + DA_REAL_PETR
CAIXA_REAL_PETR = 97_845_000.0
DIVIDA_BRUTA_REAL_PETR = 57_382_000.0 + 435_467_000.0
DIVIDA_LIQUIDA_REAL_PETR = DIVIDA_BRUTA_REAL_PETR - CAIXA_REAL_PETR


def _session(tmp_path):
    factory = get_session_factory(f"sqlite:///{tmp_path}/acoes_fatores_dle_test.db")
    return factory()


def _setup(session):
    ingest_master_index(session, DFP_2015)
    for cnpj in (BB_CNPJ, ITAU_CNPJ, PETR_CNPJ):
        ingest_line_items_for_cnpj(session, EBIT_2015, cnpj, base="con")
    ingest_line_items_for_cnpj(session, DA_2015, PETR_CNPJ, base="con")
    ingest_line_items_for_cnpj(session, CAIXA_2015, PETR_CNPJ, base="con")
    ingest_line_items_for_cnpj(session, DIVIDA_2015, PETR_CNPJ, base="con")


def test_get_ebit_as_of_verifica_ds_conta_banco_tem_conta_diferente(tmp_path):
    """O achado central desta rodada: `CD_CONTA "3.05"` existe para as três empresas,
    mas só para a Petrobras (industrial) tem o `DS_CONTA` esperado de EBIT — para Itaú e
    Banco do Brasil é outra conta (`"Resultado Antes dos Tributos sobre o Lucro"`), então
    `get_ebit_as_of` devolve `None` para os bancos, nunca o valor errado com cara de
    EBIT."""
    session = _session(tmp_path)
    _setup(session)

    assert get_ebit_as_of(session, PETR_CNPJ, DATA_DECISAO) == pytest.approx(EBIT_REAL_PETR)
    assert get_ebit_as_of(session, ITAU_CNPJ, DATA_DECISAO) is None
    assert get_ebit_as_of(session, BB_CNPJ, DATA_DECISAO) is None


def test_get_depreciacao_amortizacao_as_of_real(tmp_path):
    """Doze linhas reais no grupo de reconciliação `6.01.01.*` da DFC da Petrobras, só
    uma casa com as palavras-chave de D&A — a busca por conteúdo resolve sem
    ambiguidade contra dado real, não uma amostra construída para caber."""
    session = _session(tmp_path)
    _setup(session)

    from tradingbot.acoes.fatores import get_depreciacao_amortizacao_as_of

    assert get_depreciacao_amortizacao_as_of(session, PETR_CNPJ, DATA_DECISAO) == pytest.approx(DA_REAL_PETR)


def test_get_ebitda_as_of_real_petrobras_positivo_apesar_de_ebit_negativo(tmp_path):
    """EBITDA real da Petrobras é positivo (R$25.386 milhões) apesar do EBIT real
    negativo (-R$13.188 milhões, prejuízo operacional em 2015) — D&A grande (empresa
    intensiva em ativo fixo) reverte o sinal na soma, exatamente o comportamento
    esperado de EBITDA vs. EBIT em indústria de capital intensivo."""
    session = _session(tmp_path)
    _setup(session)

    ebitda = get_ebitda_as_of(session, PETR_CNPJ, DATA_DECISAO)
    assert ebitda == pytest.approx(EBITDA_REAL_PETR)
    assert ebitda > 0
    assert EBIT_REAL_PETR < 0


def test_get_ebitda_as_of_banco_none_por_ebit_ausente(tmp_path):
    """Banco não tem EBIT válido (achado acima) — `get_ebitda_as_of` propaga `None`
    mesmo que, hipoteticamente, D&A existisse, porque a soma nunca é parcial."""
    session = _session(tmp_path)
    _setup(session)

    assert get_ebitda_as_of(session, ITAU_CNPJ, DATA_DECISAO) is None


def test_get_divida_liquida_as_of_real_petrobras(tmp_path):
    session = _session(tmp_path)
    _setup(session)

    assert get_divida_liquida_as_of(session, PETR_CNPJ, DATA_DECISAO) == pytest.approx(
        DIVIDA_LIQUIDA_REAL_PETR
    )


def test_divida_liquida_ebitda_raw_real_petrobras_alavancagem_severa():
    """Múltiplo real ≈15,56x — alavancagem severa e verdadeira: 2015 foi o ano do
    rebaixamento de rating soberano/corporativo da Petrobras por agências
    internacionais, consistente com o número."""
    multiplo = divida_liquida_ebitda_raw(DIVIDA_LIQUIDA_REAL_PETR, EBITDA_REAL_PETR)
    assert multiplo == pytest.approx(DIVIDA_LIQUIDA_REAL_PETR / EBITDA_REAL_PETR)
    assert multiplo > 10  # alavancagem real, nao um numero pequeno


def test_divida_liquida_ebitda_raw_ebitda_zero_ou_negativo_e_indefinido():
    """Terceira categoria: dado existe, múltiplo não tem significado econômico.
    Distinta de `None` por ausência de dado (faltante) e de exclusão por matriz
    (inaplicável) — aqui simplesmente não se calcula, mecanicamente igual a faltante
    para fins de imputação, mas semanticamente uma categoria própria."""
    assert divida_liquida_ebitda_raw(divida_liquida=100.0, ebitda=0.0) is None
    assert divida_liquida_ebitda_raw(divida_liquida=100.0, ebitda=-5.0) is None
    assert divida_liquida_ebitda_raw(divida_liquida=100.0, ebitda=5.0) == pytest.approx(20.0)


def test_fator_divida_liquida_ebitda_aplicavel_banco_neutro_industrial_aplicavel():
    """O teste da matriz: banco (`Intermediários Financeiros`, subsetor real B3 de
    Itaú/BB, Seção 6.2) fica inaplicável; industrial (`Petróleo. Gás e
    Biocombustíveis`, subsetor real da Petrobras) fica aplicável. Subsetor desconhecido
    (`None`) não é tratado como inaplicável — decisão determinística não tomada, fica
    aplicável por padrão."""
    assert fator_divida_liquida_ebitda_aplicavel("Intermediários Financeiros") is False
    assert fator_divida_liquida_ebitda_aplicavel("Petróleo. Gás e Biocombustíveis") is True
    assert fator_divida_liquida_ebitda_aplicavel(None) is True
    assert DIVIDA_LIQUIDA_EBITDA_SUBSETORES_INAPLICAVEIS == {"Intermediários Financeiros"}


def test_compute_score_composto_banco_nao_penalizado_por_fator_inaplicavel():
    """O teste que prova a matriz de verdade: banco (`ITUB4`) tem só earnings yield
    aplicável (percentil 80); industrial (`PETR4`) tem os dois fatores, ambos também no
    percentil 80. Sem renormalização, o banco ficaria com score menor só por contar
    menos parcelas (40 em vez de 80, se o fator ausente contasse como 0) — um viés
    setorial escondido na aritmética, exatamente o que este teste teria capturado se
    `compute_score_composto` não renormalizasse."""
    pesos = [PesoFator("earnings_yield", 0.5), PesoFator("divida_liquida_ebitda", 0.5)]

    score_itub4 = compute_score_composto(
        {"earnings_yield": 80.0, "divida_liquida_ebitda": None}, pesos
    )
    score_petr4 = compute_score_composto(
        {"earnings_yield": 80.0, "divida_liquida_ebitda": 80.0}, pesos
    )

    assert score_itub4 == pytest.approx(80.0)  # 100% do peso no unico fator aplicavel
    assert score_petr4 == pytest.approx(80.0)  # media ponderada normal, dois fatores iguais
    assert score_itub4 == pytest.approx(score_petr4)  # comparavel apesar de fatores diferentes


def test_compute_score_composto_sem_renormalizacao_seria_viesado():
    """Documenta explicitamente o bug que a renormalização evita — útil como
    especificação executável, não só como comentário."""
    pesos = [PesoFator("earnings_yield", 0.5), PesoFator("divida_liquida_ebitda", 0.5)]
    score_correto = compute_score_composto({"earnings_yield": 80.0, "divida_liquida_ebitda": None}, pesos)

    score_sem_renormalizar_seria = 0.5 * 80.0 + 0.5 * 0.0  # tratando ausente como zero
    assert score_correto != pytest.approx(score_sem_renormalizar_seria)
    assert score_correto > score_sem_renormalizar_seria


def test_point_in_time_multi_fonte_ebitda_divida_liquida(tmp_path):
    """O teste mais exigente até agora: EBITDA (DRE+DFC) e dívida líquida (BP) usam o
    balanço público *na data de decisão*, as três demonstrações resolvidas pelo mesmo
    filing — antes da publicação real da Petrobras (`dt_receb=2016-03-21`), nenhum dos
    dois está disponível; depois, os valores reais aparecem, do mesmo exercício."""
    session = _session(tmp_path)
    _setup(session)

    antes = date(2016, 3, 20)
    assert get_ebitda_as_of(session, PETR_CNPJ, antes) is None
    assert get_divida_liquida_as_of(session, PETR_CNPJ, antes) is None

    depois = date(2016, 3, 21)
    assert get_ebitda_as_of(session, PETR_CNPJ, depois) == pytest.approx(EBITDA_REAL_PETR)
    assert get_divida_liquida_as_of(session, PETR_CNPJ, depois) == pytest.approx(DIVIDA_LIQUIDA_REAL_PETR)

    assert get_ebitda_as_of(session, PETR_CNPJ, DATA_DECISAO) == pytest.approx(EBITDA_REAL_PETR)
