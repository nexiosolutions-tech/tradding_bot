"""Fase 2 do módulo de Ações — terceiro fator ponta a ponta: ROE (spec 14, Seção 7.3).
Primeiro fator a cruzar duas demonstrações num único quociente (lucro da DRE sobre
patrimônio do BP) e primeiro a testar demeaning setorial de verdade em vez da matriz —
ROE se aplica a banco, mas não é comparável em nível absoluto com industrial.

Fixtures reais, exercício 2015 (publicado 2016), mesmas três empresas dos fatores
anteriores:

- `dre_con_2015_itub_bbas_petr_lucro_controladores_real_extract.csv` — `DS_CONTA
  "Atribuído a Sócios da Empresa Controladora"`. Achado real (mesmo padrão do `"3.05"`,
  Seção 7.2): o `CD_CONTA` numérico muda por empresa (`"3.09.01"` banco, `"3.11.01"`
  Petrobras) — busca sempre por `DS_CONTA`.
- `bpp_con_2015_itub_bbas_petr_patrimonio_real_extract.csv` — `"Patrimônio Líquido
  Consolidado"` e `"Participação dos Acionistas Não Controladores"` das três empresas
  (mesmo achado: `CD_CONTA "2.08"` banco, `"2.03"` Petrobras).

ROE real: Petrobras -13,68% (prejuízo real de 2015, patrimônio ainda positivo — não é o
caso "indefinido", é prejuízo genuíno refletido corretamente), Itaú +22,93%, Banco do
Brasil +17,04% — os dois bancos com ROE estruturalmente mais alto que a industrial, o
efeito que o demeaning setorial precisa neutralizar.
"""

from datetime import date
from pathlib import Path

import pytest

from tradingbot.acoes.cvm_ingestion import ingest_line_items_for_cnpj, ingest_master_index
from tradingbot.acoes.fatores import (
    FactorInput,
    compute_demeaned_percentiles,
    earnings_yield_raw,
    get_lucro_liquido_controladores_as_of,
    get_patrimonio_liquido_controladores_as_of,
    pearson_correlation,
    roe_raw,
)
from tradingbot.acoes.persistence import get_session_factory

FIXTURES = Path(__file__).parent / "fixtures"
DFP_2015 = FIXTURES / "cvm" / "dfp_master_index_2015_itub_bbas_petr_real_extract.csv"
LUCRO_2015 = FIXTURES / "cvm" / "dre_con_2015_itub_bbas_petr_lucro_controladores_real_extract.csv"
PATRIMONIO_2015 = FIXTURES / "cvm" / "bpp_con_2015_itub_bbas_petr_patrimonio_real_extract.csv"

BB_CNPJ = "00.000.000/0001-91"
ITAU_CNPJ = "60.872.504/0001-23"
PETR_CNPJ = "33.000.167/0001-01"

DATA_DECISAO = date(2016, 7, 15)

# valores reais, verificados contra os arquivos brutos antes de escrever qualquer teste
LUCRO_CONTROLADORES_REAL = {
    "ITAU": 25_740_000.0,
    "BB": 14_069_582.0,
    "PETR": -34_836_000.0,
}
PATRIMONIO_CONTROLADORES_REAL = {
    "ITAU": 114_059_000.0 - 1_807_000.0,
    "BB": 86_229_994.0 - 3_672_743.0,
    "PETR": 257_930_000.0 - 3_199_000.0,
}
ROE_REAL = {
    label: LUCRO_CONTROLADORES_REAL[label] / PATRIMONIO_CONTROLADORES_REAL[label]
    for label in ("ITAU", "BB", "PETR")
}

# reusa earnings yield real ja fechado (rodada anterior) para o teste de correlacao
EPS_REAL = {"ITUB4": 4.30, "BBAS3": 5.03, "PETR4": -2.67}
PRECO_REAL = {"ITUB4": 33.46, "BBAS3": 19.26, "PETR4": 11.02}


def _session(tmp_path):
    factory = get_session_factory(f"sqlite:///{tmp_path}/acoes_fatores_roe_test.db")
    return factory()


def _setup(session):
    ingest_master_index(session, DFP_2015)
    for cnpj in (BB_CNPJ, ITAU_CNPJ, PETR_CNPJ):
        ingest_line_items_for_cnpj(session, LUCRO_2015, cnpj, base="con")
        ingest_line_items_for_cnpj(session, PATRIMONIO_2015, cnpj, base="con")


def test_get_lucro_liquido_controladores_as_of_real(tmp_path):
    """Confirma que a busca por `DS_CONTA` resolve certo nas duas variantes de plano de
    contas (banco e industrial), apesar do `CD_CONTA` numérico diferir."""
    session = _session(tmp_path)
    _setup(session)

    assert get_lucro_liquido_controladores_as_of(session, ITAU_CNPJ, DATA_DECISAO) == pytest.approx(
        LUCRO_CONTROLADORES_REAL["ITAU"]
    )
    assert get_lucro_liquido_controladores_as_of(session, BB_CNPJ, DATA_DECISAO) == pytest.approx(
        LUCRO_CONTROLADORES_REAL["BB"]
    )
    assert get_lucro_liquido_controladores_as_of(session, PETR_CNPJ, DATA_DECISAO) == pytest.approx(
        LUCRO_CONTROLADORES_REAL["PETR"]
    )


def test_get_patrimonio_liquido_controladores_as_of_real(tmp_path):
    """Patrimônio líquido consolidado menos participação de não controladores — real,
    nas três empresas, consistente com o numerador (lucro dos controladores, não o
    consolidado com minoritários)."""
    session = _session(tmp_path)
    _setup(session)

    assert get_patrimonio_liquido_controladores_as_of(session, ITAU_CNPJ, DATA_DECISAO) == pytest.approx(
        PATRIMONIO_CONTROLADORES_REAL["ITAU"]
    )
    assert get_patrimonio_liquido_controladores_as_of(session, BB_CNPJ, DATA_DECISAO) == pytest.approx(
        PATRIMONIO_CONTROLADORES_REAL["BB"]
    )
    assert get_patrimonio_liquido_controladores_as_of(session, PETR_CNPJ, DATA_DECISAO) == pytest.approx(
        PATRIMONIO_CONTROLADORES_REAL["PETR"]
    )


def test_roe_raw_real_petrobras_negativo_mas_nao_indefinido():
    """A Petrobras teve prejuízo real em 2015: ROE real negativo (-13,68%), mas o
    patrimônio líquido dos controladores continua positivo — este NÃO é o caso
    "indefinido" (patrimônio ≤ 0), é um prejuízo genuíno corretamente refletido como ROE
    negativo. A distinção importa: nem todo ROE negativo é indefinido, só o caso onde o
    denominador quebra o significado econômico do quociente."""
    roe = roe_raw(LUCRO_CONTROLADORES_REAL["PETR"], PATRIMONIO_CONTROLADORES_REAL["PETR"])
    assert roe == pytest.approx(ROE_REAL["PETR"])
    assert roe < 0
    assert PATRIMONIO_CONTROLADORES_REAL["PETR"] > 0


def test_roe_raw_bancos_reais_estruturalmente_mais_altos_que_industrial():
    assert ROE_REAL["ITAU"] == pytest.approx(0.22928, abs=1e-4)
    assert ROE_REAL["BB"] == pytest.approx(0.17044, abs=1e-4)
    assert ROE_REAL["ITAU"] > ROE_REAL["PETR"]
    assert ROE_REAL["BB"] > ROE_REAL["PETR"]


def test_roe_raw_patrimonio_negativo_e_indefinido_mesmo_com_lucro_positivo():
    """A armadilha perversa: prejuízo dividido por patrimônio negativo daria ROE
    positivo (empresa quebrando parecendo excelente) se não fosse tratado. Também
    testado o caso simétrico (lucro positivo/patrimônio negativo, que daria ROE
    negativo enganoso) — os dois ficam `None`, nunca calculados."""
    assert roe_raw(lucro_liquido_controladores=-100.0, patrimonio_liquido_controladores=-50.0) is None
    assert roe_raw(lucro_liquido_controladores=100.0, patrimonio_liquido_controladores=-50.0) is None
    assert roe_raw(lucro_liquido_controladores=100.0, patrimonio_liquido_controladores=0.0) is None
    assert roe_raw(lucro_liquido_controladores=100.0, patrimonio_liquido_controladores=50.0) == pytest.approx(2.0)


def test_categoria_indefinido_generaliza_dois_gatilhos_independentes():
    """Confirma explicitamente o que a Seção 7.3 pediu para verificar: a categoria
    "indefinido" não foi codificada específica para EBITDA — dois fatores
    independentes (dívida líquida/EBITDA via `EBITDA≤0`, ROE via `patrimônio≤0`) usam o
    mesmo padrão mecânico (`None`, sem acoplamento entre as duas funções)."""
    from tradingbot.acoes.fatores import divida_liquida_ebitda_raw

    assert divida_liquida_ebitda_raw(divida_liquida=100.0, ebitda=0.0) is None
    assert roe_raw(lucro_liquido_controladores=100.0, patrimonio_liquido_controladores=0.0) is None


def test_demeaning_bancos_comparados_entre_si_dado_real():
    """Os dois bancos reais (`ITAU`/`BB`, mesmo segmento `Bancos`) demeaned contra a
    própria média de par — não distorcidos pela escala muito diferente da industrial
    (`PETR`, ROE muito menor). `min_bucket_size=2`: fixture real tem só 3 empresas ao
    todo, piso de produção (3) nunca formaria bucket de segmento com só 2 bancos —
    reduzido aqui deliberadamente para exercitar o bucket mais fino com dado real
    disponível (mesmo padrão já usado em rodadas anteriores por limite de tamanho de
    fixture, não um valor de produção)."""
    itens = [
        FactorInput("ITUB4", ROE_REAL["ITAU"], segmento="Bancos", subsetor="Intermediários Financeiros", setor="Financeiro"),
        FactorInput("BBAS3", ROE_REAL["BB"], segmento="Bancos", subsetor="Intermediários Financeiros", setor="Financeiro"),
        FactorInput(
            "PETR4", ROE_REAL["PETR"],
            segmento="Exploração. Refino e Distribuição",
            subsetor="Petróleo. Gás e Biocombustíveis",
            setor="Petróleo. Gás e Biocombustíveis",
        ),
    ]
    resultados = {r.ticker: r for r in compute_demeaned_percentiles(itens, min_bucket_size=2)}

    assert resultados["ITUB4"].bucket_usado == "segmento"
    assert resultados["BBAS3"].bucket_usado == "segmento"
    # PETR sozinho no proprio segmento/subsetor/setor (n=1 < piso 2) - cai no universo
    assert resultados["PETR4"].bucket_usado == "universo"

    media_bancos = (ROE_REAL["ITAU"] + ROE_REAL["BB"]) / 2
    assert resultados["ITUB4"].demeaned == pytest.approx(ROE_REAL["ITAU"] - media_bancos)
    assert resultados["BBAS3"].demeaned == pytest.approx(ROE_REAL["BB"] - media_bancos)


def test_demeaning_setorial_torna_banco_e_industrial_tipicos_comparaveis_mecanismo():
    """Mecanismo isolado (valores ilustrativos, não dado real de empresa — o objetivo é
    provar que demeaning neutraliza a diferença estrutural de escala entre setores, não
    afirmar um fato de mercado). Bucket "bancos" com ROE em torno de 20% e bucket
    "industriais" com ROE em torno de 5% — bem separados em nível absoluto. Depois do
    demeaning, um banco e uma industrial ambos "típicos" do próprio setor (perto da
    média setorial) ficam com percentil parecido (perto de 50), não um sistematicamente
    acima do outro só pela estrutura de capital do setor."""
    itens = [
        FactorInput("BANCO1", 0.18, segmento="Bancos", subsetor="Bancos", setor="Financeiro"),
        FactorInput("BANCO2", 0.20, segmento="Bancos", subsetor="Bancos", setor="Financeiro"),
        FactorInput("BANCO3", 0.22, segmento="Bancos", subsetor="Bancos", setor="Financeiro"),
        FactorInput("IND1", 0.03, segmento="Industria", subsetor="Industria", setor="Industria"),
        FactorInput("IND2", 0.05, segmento="Industria", subsetor="Industria", setor="Industria"),
        FactorInput("IND3", 0.07, segmento="Industria", subsetor="Industria", setor="Industria"),
    ]
    resultados = {r.ticker: r for r in compute_demeaned_percentiles(itens, min_bucket_size=3)}

    # o banco "mediano" do proprio setor e a industria "mediana" da propria ficam perto
    # do centro do ranking demeaned (percentil ~50), apesar de ROE absoluto muito diferente
    assert 40 <= resultados["BANCO2"].percentil <= 60
    assert 40 <= resultados["IND2"].percentil <= 60
    assert abs(resultados["BANCO2"].percentil - resultados["IND2"].percentil) < 20


def test_correlacao_roe_earnings_yield_universo_2016_com_ressalva_estatistica():
    """Medição real, não presumida — mas com o tamanho de amostra que a fixture desta
    rodada tem (`n=3`, as mesmas três empresas de todos os fatores da Fase 2). `n=3` NÃO
    é suficiente para aplicar o limiar de 0,7 pré-especificado com confiança estatística
    — 3 pontos quase sempre produzem uma correlação alta por acaso, não porque os
    fatores meçam a mesma coisa de verdade. O número é calculado e registrado
    honestamente, mas a decisão de ortogonalidade fica pendente até o universo real de
    2016 (115 empresas, já materializado na Seção 6) ser usado de fato — próximo passo
    explícito, não fabricado aqui."""
    tickers = ["ITUB4", "BBAS3", "PETR4"]
    labels = {"ITUB4": "ITAU", "BBAS3": "BB", "PETR4": "PETR"}

    earnings_yields = [earnings_yield_raw(EPS_REAL[t], PRECO_REAL[t]) for t in tickers]
    roes = [ROE_REAL[labels[t]] for t in tickers]

    correlacao = pearson_correlation(earnings_yields, roes)

    assert -1.0 <= correlacao <= 1.0
    # registrado, nao usado para decidir nada com n=3 - ver docstring
    assert correlacao == pytest.approx(0.918, abs=0.01)
