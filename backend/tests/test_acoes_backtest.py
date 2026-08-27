"""Motor de backtest — spec 14, Seção 9.

`build_decisao` é monkeypatchado por um dublê determinístico em todos os testes de
simulação/nulidade/fold — a orquestração universo+fatores+score já é travada por
`test_acoes_decisao.py` contra dado 100% real; aqui o alvo é a lógica nova
(turnover/custo, marcação a mercado, saída por liquidez, permutação, folds), isolada da
máquina de ingestão pesada, mesma disciplina de `test_build_decisao_nao_reimplementa_
compute_score_composto` (monkeypatch para isolar uma camada por vez).
"""

from datetime import date

import pytest

import tradingbot.acoes.backtest as backtest_module
from tradingbot.acoes.backtest import (
    CustosSimulacao,
    DrawdownResult,
    POLITICA_PESO_IGUAL,
    POLITICA_PESO_LIQUIDEZ,
    max_drawdown,
    registrar_experimento,
    return_over_drawdown,
    return_over_volatility,
    selecionar_top_n,
    selecionar_universo_completo,
    simulate_estrategia,
    tem_quebra_de_nivel,
    teste_nulidade as executar_teste_nulidade,
    total_return_pct,
    volatility_pct,
    walk_forward_folds,
)
from tradingbot.acoes.decisao import DecisaoEmpresa, DecisaoResultado
from tradingbot.acoes.models import CorporateEventFlag, CotahistPrice
from tradingbot.acoes.persistence import get_session_factory
from tradingbot.acoes.universo_elegivel import UniversoElegivelStats
from tradingbot.learning_engine.experiment_log import DOMAIN_ACOES, load_experiments


def _session(tmp_path, nome="db"):
    factory = get_session_factory(f"sqlite:///{tmp_path}/{nome}.db")
    return factory()


def _empresa(ticker, cnpj, score, volume_mediano=1_000_000.0):
    return DecisaoEmpresa(
        ticker=ticker,
        cnpj=cnpj,
        setor_ativ=None,
        setor_b3=None,
        subsetor_b3=None,
        segmento_b3=None,
        earnings_yield_percentil=None,
        divida_liquida_ebitda_percentil=None,
        roe_percentil=None,
        score_composto=score,
        tem_fator_real=score is not None,
        volume_mediano=volume_mediano,
    )


def _seed_precos(session, ticker, data_inicio, data_fim, preco_inicial, crescimento_mensal, volume):
    """Um preço por dia de calendário no intervalo — simplicidade sobre realismo de
    calendário de pregão (o próprio backtest usa `<=` como fallback, então um dia sem
    pregão de verdade não muda a semântica testada). Cresce continuamente pela fração
    de mês decorrida, para que a marcação mês a mês tenha um valor esperado exato."""
    dias = (data_fim - data_inicio).days
    linhas = []
    for i in range(dias + 1):
        dia = date.fromordinal(data_inicio.toordinal() + i)
        meses_decorridos = i / 30.0
        preco = preco_inicial * ((1 + crescimento_mensal) ** meses_decorridos)
        linhas.append(
            CotahistPrice(
                ticker=ticker,
                trade_date=dia,
                especi_raw="ON      NM",
                fatcot=1,
                open=preco,
                high=preco,
                low=preco,
                avg=preco,
                close=preco,
                quantity=1000,
                financial_volume=volume,
            )
        )
    session.add_all(linhas)
    session.commit()


# ---------------------------------------------------------------------------
# Métricas puras
# ---------------------------------------------------------------------------


def test_total_return_pct_curva_vazia_e_capital_zero():
    assert total_return_pct([], 10_000.0) == 0.0
    assert total_return_pct([(date(2020, 1, 1), 100.0)], 0.0) == 0.0


def test_total_return_pct_caso_simples():
    curva = [(date(2020, 1, 1), 10_000.0), (date(2020, 2, 1), 11_000.0)]
    assert total_return_pct(curva, 10_000.0) == pytest.approx(0.10)


def test_volatility_pct_curva_constante_e_zero():
    curva = [(date(2020, 1, 1), 10_000.0), (date(2020, 2, 1), 10_000.0), (date(2020, 3, 1), 10_000.0)]
    assert volatility_pct(curva) == pytest.approx(0.0)


def test_max_drawdown_caso_conhecido():
    curva = [
        (date(2020, 1, 1), 100.0), (date(2020, 2, 1), 120.0),
        (date(2020, 3, 1), 90.0), (date(2020, 4, 1), 130.0),
    ]
    resultado = max_drawdown(curva)
    assert resultado == DrawdownResult(max_drawdown_pct=pytest.approx(0.25), max_drawdown_duration_dias=29)


def test_return_over_drawdown_sem_drawdown_e_infinito_com_retorno_positivo():
    assert return_over_drawdown(0.1, 0.0) == float("inf")
    assert return_over_drawdown(0.0, 0.0) == 0.0


def test_return_over_volatility_divide_normalmente():
    assert return_over_volatility(0.2, 0.1) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Políticas de peso
# ---------------------------------------------------------------------------


def test_politica_peso_igual_divide_uniformemente(tmp_path):
    session = _session(tmp_path)
    pesos = POLITICA_PESO_IGUAL.calcular(["AAAA3", "BBBB3", "CCCC3"], session, date(2020, 1, 1))
    assert pesos == {"AAAA3": pytest.approx(1 / 3), "BBBB3": pytest.approx(1 / 3), "CCCC3": pytest.approx(1 / 3)}


def test_politica_peso_igual_lista_vazia(tmp_path):
    session = _session(tmp_path)
    assert POLITICA_PESO_IGUAL.calcular([], session, date(2020, 1, 1)) == {}


def test_politica_peso_liquidez_pondera_por_volume_real(tmp_path):
    session = _session(tmp_path)
    _seed_precos(session, "AAAA3", date(2019, 1, 1), date(2020, 1, 31), 10.0, 0.0, volume=300_000.0)
    _seed_precos(session, "BBBB3", date(2019, 1, 1), date(2020, 1, 31), 10.0, 0.0, volume=100_000.0)

    pesos = POLITICA_PESO_LIQUIDEZ.calcular(["AAAA3", "BBBB3"], session, date(2020, 1, 31))

    assert pesos["AAAA3"] == pytest.approx(0.75)
    assert pesos["BBBB3"] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Seleção
# ---------------------------------------------------------------------------


def test_selecionar_top_n_usa_formar_carteira_minima():
    empresas = [_empresa(f"T{i}3", f"cnpj{i}", float(i)) for i in range(5)]
    resultado = DecisaoResultado(date(2020, 1, 1), UniversoElegivelStats(), empresas)
    selecao = selecionar_top_n(n=2)(resultado)
    assert selecao == {("T43", "cnpj4"), ("T33", "cnpj3")}


def test_selecionar_universo_completo_ignora_score():
    empresas = [_empresa("AAAA3", "c1", None), _empresa("BBBB3", "c2", 5.0)]
    resultado = DecisaoResultado(date(2020, 1, 1), UniversoElegivelStats(), empresas)
    selecao = selecionar_universo_completo(resultado)
    assert selecao == {("AAAA3", "c1"), ("BBBB3", "c2")}


# ---------------------------------------------------------------------------
# Simulação (build_decisao monkeypatchado)
# ---------------------------------------------------------------------------


def _fake_build_decisao_factory(por_data):
    def _fake(session, data_decisao, setor_by_cnpj, *, pesos=None, **kwargs_universo):
        return por_data[data_decisao]

    return _fake


def test_simulate_estrategia_duas_acoes_peso_igual_sem_saida(tmp_path, monkeypatch):
    """Duas ações, peso igual, uma decisão -> um ciclo de 12 meses. AAAA3 sobe 1%/mês,
    BBBB3 fica parada — retorno total esperado é a média dos dois fatores de
    crescimento compostos, sem custo (custos zerados para isolar a marcação a
    mercado)."""
    session = _session(tmp_path)
    d0, d1 = date(2020, 1, 31), date(2021, 1, 31)
    _seed_precos(session, "AAAA3", d0, d1, 10.0, 0.01, volume=10_000_000.0)
    _seed_precos(session, "BBBB3", d0, d1, 10.0, 0.00, volume=10_000_000.0)

    resultado_decisao = DecisaoResultado(
        d0, UniversoElegivelStats(),
        [_empresa("AAAA3", "c1", 1.0, volume_mediano=10_000_000.0), _empresa("BBBB3", "c2", 1.0, volume_mediano=10_000_000.0)],
    )
    monkeypatch.setattr(backtest_module, "build_decisao", _fake_build_decisao_factory({d0: resultado_decisao}))

    resultado = simulate_estrategia(
        session, (d0, d1), selecionar_universo_completo, POLITICA_PESO_IGUAL, {},
        capital_inicial=10_000.0, custos=CustosSimulacao(0, 0, 0, 0),
    )

    fator_aaaa = 1.01 ** 12
    retorno_esperado = (fator_aaaa + 1.0) / 2 - 1
    assert resultado.total_return_pct == pytest.approx(retorno_esperado, rel=0.02)
    assert resultado.equity_curve[0] == (d0, 10_000.0)
    assert resultado.equity_curve[-1][0] == d1
    assert resultado.n_transversal == [2]


def test_simulate_estrategia_aplica_custo_no_rebalanceamento(tmp_path, monkeypatch):
    """Mesmo cenário sem crescimento nenhum: sem custo o capital final é igual ao
    inicial; com corretagem/emolumentos/slippage > 0, o rebalanceamento mensal (peso
    igual reaplicado todo mês, mesmo sem saída) cobra turnover != 0 sempre que o preço
    relativo das duas pernas diverge — aqui as duas ficam paradas juntas, então o único
    custo é o da formação inicial da carteira (turnover=1.0 na primeira decisão)."""
    session = _session(tmp_path)
    d0, d1 = date(2020, 1, 31), date(2020, 4, 30)
    _seed_precos(session, "AAAA3", d0, d1, 10.0, 0.0, volume=10_000_000.0)

    resultado_decisao = DecisaoResultado(
        d0, UniversoElegivelStats(), [_empresa("AAAA3", "c1", 1.0, volume_mediano=10_000_000.0)]
    )
    monkeypatch.setattr(backtest_module, "build_decisao", _fake_build_decisao_factory({d0: resultado_decisao}))

    sem_custo = simulate_estrategia(
        session, (d0, d1), selecionar_universo_completo, POLITICA_PESO_IGUAL, {},
        capital_inicial=10_000.0, custos=CustosSimulacao(0, 0, 0, 0),
    )
    com_custo = simulate_estrategia(
        session, (d0, d1), selecionar_universo_completo, POLITICA_PESO_IGUAL, {},
        capital_inicial=10_000.0, custos=CustosSimulacao(corretagem_pct=0.01),
    )

    assert sem_custo.total_return_pct == pytest.approx(0.0)
    assert com_custo.total_return_pct < 0.0
    assert com_custo.equity_curve[-1][1] < sem_custo.equity_curve[-1][1]


def test_simulate_estrategia_saida_por_liquidez_penaliza_e_remove(tmp_path, monkeypatch):
    """AAAA3 negocia normalmente; BBBB3 tem volume alto até fev/2020 e despenca abaixo
    do piso a partir de então — precisa sair da carteira em fev/2020 com a penalidade
    de slippage de saída, nunca sumir sem custo."""
    session = _session(tmp_path)
    d0, d1 = date(2020, 1, 31), date(2020, 4, 30)
    _seed_precos(session, "AAAA3", d0, d1, 10.0, 0.0, volume=10_000_000.0)

    # BBBB3: volume alto ate 2020-01-31, depois cai bem abaixo do piso (deflacionado a
    # partir de R$500 mil nominal em 2015-02-27, sem IPCA ingerido aqui -> piso nominal)
    _seed_precos(session, "BBBB3", date(2019, 10, 1), d0, 10.0, 0.0, volume=10_000_000.0)
    _seed_precos(session, "BBBB3", date(2020, 2, 1), d1, 10.0, 0.0, volume=1_000.0)

    resultado_decisao = DecisaoResultado(
        d0, UniversoElegivelStats(),
        [_empresa("AAAA3", "c1", 1.0, volume_mediano=10_000_000.0), _empresa("BBBB3", "c2", 1.0, volume_mediano=10_000_000.0)],
    )
    monkeypatch.setattr(backtest_module, "build_decisao", _fake_build_decisao_factory({d0: resultado_decisao}))

    resultado = simulate_estrategia(
        session, (d0, d1), selecionar_universo_completo, POLITICA_PESO_IGUAL, {},
        capital_inicial=10_000.0, custos=CustosSimulacao(0, 0, 0, slippage_saida_iliquidez_pct=0.02),
    )

    # preco nunca mudou (crescimento 0 nos dois): sem a saida, o total return seria 0.
    # Com a saida penalizada em fev/2020, o resultado final tem que ficar negativo.
    assert resultado.total_return_pct < 0.0


def test_tem_quebra_de_nivel_detecta_evento_no_intervalo_e_respeita_fronteira(tmp_path):
    session = _session(tmp_path)
    session.add(
        CorporateEventFlag(
            ticker="AAAA3", event_date=date(2020, 2, 15), ex_suffix="EG",
            is_level_break=True, source="ESPECI_TRANSITION",
        )
    )
    session.commit()

    assert tem_quebra_de_nivel(session, "AAAA3", date(2020, 1, 31), date(2020, 2, 29)) is True
    # fora do intervalo (antes do inicio exclusivo ou depois do fim)
    assert tem_quebra_de_nivel(session, "AAAA3", date(2020, 2, 15), date(2020, 2, 29)) is False
    assert tem_quebra_de_nivel(session, "AAAA3", date(2020, 1, 1), date(2020, 2, 14)) is False
    # ticker diferente, mesmo evento, nunca cruza
    assert tem_quebra_de_nivel(session, "BBBB3", date(2020, 1, 31), date(2020, 2, 29)) is False


def test_tem_quebra_de_nivel_ignora_evento_que_nao_e_quebra_de_nivel(tmp_path):
    session = _session(tmp_path)
    session.add(
        CorporateEventFlag(
            ticker="AAAA3", event_date=date(2020, 2, 15), ex_suffix="ED",
            is_level_break=False, source="ESPECI_TRANSITION",
        )
    )
    session.commit()
    assert tem_quebra_de_nivel(session, "AAAA3", date(2020, 1, 31), date(2020, 2, 29)) is False


def test_simulate_estrategia_nunca_transforma_quebra_de_nivel_em_retorno(tmp_path, monkeypatch):
    """AAAA3 tem um grupamento (EG) registrado no meio do mes de fevereiro/2020 — o
    preco bruto (nao ajustado, Secao 5.3) salta 10x nesse dia sem nenhum retorno real
    por tras. Sem a checagem contra `CorporateEventFlag`, isso viraria um +900% de
    retorno de carteira num unico mes (o achado real do benchmark, 2026-08-27). Com a
    checagem, o valor da posicao fica congelado nesse mes, nunca inventa o retorno."""
    session = _session(tmp_path)
    d0, d1 = date(2020, 1, 31), date(2020, 4, 30)

    # preco cru "salta" 10x em 2020-02-15 (simula o efeito bruto de um grupamento 10:1
    # sem ajuste) - sem a protecao, isso pareceria um retorno de +900% naquele mes.
    session.add_all(
        [
            CotahistPrice(ticker="AAAA3", trade_date=date(2020, 1, 31), especi_raw="ON      NM",
                           fatcot=1, open=10.0, high=10.0, low=10.0, avg=10.0, close=10.0,
                           quantity=1000, financial_volume=10_000_000.0),
            CotahistPrice(ticker="AAAA3", trade_date=date(2020, 2, 15), especi_raw="ON      NM",
                           fatcot=1, open=100.0, high=100.0, low=100.0, avg=100.0, close=100.0,
                           quantity=1000, financial_volume=10_000_000.0),
            CotahistPrice(ticker="AAAA3", trade_date=date(2020, 2, 29), especi_raw="ON      NM",
                           fatcot=1, open=100.0, high=100.0, low=100.0, avg=100.0, close=100.0,
                           quantity=1000, financial_volume=10_000_000.0),
        ]
    )
    session.add(
        CorporateEventFlag(
            ticker="AAAA3", event_date=date(2020, 2, 15), ex_suffix="EG",
            is_level_break=True, source="ESPECI_TRANSITION",
        )
    )
    session.commit()
    _seed_precos(session, "AAAA3", date(2020, 3, 1), d1, 100.0, 0.0, volume=10_000_000.0)

    resultado_decisao = DecisaoResultado(
        d0, UniversoElegivelStats(), [_empresa("AAAA3", "c1", 1.0, volume_mediano=10_000_000.0)]
    )
    monkeypatch.setattr(backtest_module, "build_decisao", _fake_build_decisao_factory({d0: resultado_decisao}))

    resultado = simulate_estrategia(
        session, (d0, d1), selecionar_universo_completo, POLITICA_PESO_IGUAL, {},
        capital_inicial=10_000.0, custos=CustosSimulacao(0, 0, 0, 0),
    )

    marco_fevereiro = next(v for d, v in resultado.equity_curve if d == date(2020, 2, 29))
    assert marco_fevereiro == pytest.approx(10_000.0)
    assert resultado.total_return_pct == pytest.approx(0.0)


def test_teste_nulidade_exclui_ticker_com_quebra_de_nivel_no_ano(tmp_path, monkeypatch):
    """Mesma protecao no teste de nulidade: retorno anual atravessando uma quebra de
    nivel vira `None` (excluido da media), nunca um numero inflado que contamina a
    metrica real nem a nuvem nula."""
    session = _session(tmp_path)
    d0, d1 = date(2020, 1, 31), date(2021, 1, 31)

    session.add_all(
        [
            CotahistPrice(ticker="AAAA3", trade_date=d0, especi_raw="ON      NM", fatcot=1,
                           open=10.0, high=10.0, low=10.0, avg=10.0, close=10.0,
                           quantity=1000, financial_volume=10_000_000.0),
            CotahistPrice(ticker="AAAA3", trade_date=d1, especi_raw="ON      NM", fatcot=1,
                           open=100.0, high=100.0, low=100.0, avg=100.0, close=100.0,
                           quantity=1000, financial_volume=10_000_000.0),
        ]
    )
    session.add(
        CorporateEventFlag(
            ticker="AAAA3", event_date=date(2020, 6, 1), ex_suffix="EG",
            is_level_break=True, source="ESPECI_TRANSITION",
        )
    )
    _seed_precos(session, "BBBB3", d0, d1, 10.0, 0.0, volume=10_000_000.0)
    session.commit()

    resultado_decisao = DecisaoResultado(
        d0, UniversoElegivelStats(),
        [_empresa("AAAA3", "c1", 1.0, volume_mediano=10_000_000.0), _empresa("BBBB3", "c2", 1.0, volume_mediano=10_000_000.0)],
    )
    monkeypatch.setattr(backtest_module, "build_decisao", _fake_build_decisao_factory({d0: resultado_decisao}))

    resultado = executar_teste_nulidade(session, (d0, d1), {}, n_top=2, n_permutacoes=100)

    # so BBBB3 (sem quebra) entra na metrica - retorno 0%, nao a media com AAAA3 (que
    # pareceria +900% sem a protecao)
    assert resultado.metrica_real == pytest.approx(0.0)


def test_simulate_estrategia_menos_de_duas_datas_levanta_erro(tmp_path):
    session = _session(tmp_path)
    with pytest.raises(ValueError):
        simulate_estrategia(session, (date(2020, 1, 1),), selecionar_universo_completo, POLITICA_PESO_IGUAL, {})


# ---------------------------------------------------------------------------
# Teste de nulidade
# ---------------------------------------------------------------------------


def test_teste_nulidade_exige_no_minimo_100_permutacoes(tmp_path):
    session = _session(tmp_path)
    with pytest.raises(ValueError):
        executar_teste_nulidade(session, (date(2020, 1, 1), date(2021, 1, 1)), {}, n_permutacoes=10)


def test_teste_nulidade_score_perfeitamente_preditivo_fica_fora_da_nuvem_nula(tmp_path, monkeypatch):
    """Score = retorno futuro real de cada ticker (construído de propósito) — a seleção
    real bate exatamente nos vencedores, a nuvem nula (score embaralhado) quase nunca
    consegue. Prova que o teste distingue sinal real de acaso quando o sinal é
    perfeito, o caso mais fácil de verificar."""
    session = _session(tmp_path)
    d0, d1 = date(2020, 1, 31), date(2021, 1, 31)

    tickers = [f"T{i}3" for i in range(20)]
    crescimentos = [i * 0.005 for i in range(20)]  # T0 parado, T19 sobe mais
    for ticker, crescimento in zip(tickers, crescimentos):
        _seed_precos(session, ticker, d0, d1, 10.0, crescimento, volume=10_000_000.0)

    empresas = [
        _empresa(ticker, f"cnpj-{ticker}", score=crescimento, volume_mediano=10_000_000.0)
        for ticker, crescimento in zip(tickers, crescimentos)
    ]
    resultado_decisao = DecisaoResultado(d0, UniversoElegivelStats(), empresas)
    monkeypatch.setattr(backtest_module, "build_decisao", _fake_build_decisao_factory({d0: resultado_decisao}))

    import random

    resultado = executar_teste_nulidade(
        session, (d0, d1), {}, n_top=5, n_permutacoes=100, rng=random.Random(42)
    )

    assert resultado.fora_da_nuvem_nula is True
    assert resultado.p_valor < 0.05
    assert resultado.metrica_real > max(resultado.metrica_nula)


def test_teste_nulidade_score_aleatorio_fica_dentro_da_nuvem_nula(tmp_path, monkeypatch):
    """Score sem nenhuma relação com o retorno futuro (mesmo valor pra todo mundo) —
    a seleção real não pode ficar sistematicamente melhor que a nuvem, p-valor não deve
    cravar significância."""
    session = _session(tmp_path)
    d0, d1 = date(2020, 1, 31), date(2021, 1, 31)

    tickers = [f"T{i}3" for i in range(20)]
    for i, ticker in enumerate(tickers):
        crescimento = 0.01 if i % 2 == 0 else -0.01
        _seed_precos(session, ticker, d0, d1, 10.0, crescimento, volume=10_000_000.0)

    empresas = [_empresa(ticker, f"cnpj-{ticker}", score=1.0, volume_mediano=10_000_000.0) for ticker in tickers]
    resultado_decisao = DecisaoResultado(d0, UniversoElegivelStats(), empresas)
    monkeypatch.setattr(backtest_module, "build_decisao", _fake_build_decisao_factory({d0: resultado_decisao}))

    import random

    resultado = executar_teste_nulidade(session, (d0, d1), {}, n_top=5, n_permutacoes=100, rng=random.Random(7))

    assert resultado.fora_da_nuvem_nula is False


# ---------------------------------------------------------------------------
# Walk-forward folds
# ---------------------------------------------------------------------------


def test_walk_forward_folds_particiona_e_reporta_n_transversal(tmp_path, monkeypatch):
    session = _session(tmp_path)
    datas = tuple(date(2015 + i, 2, 28) for i in range(6))  # 2015..2020

    por_data = {}
    for i, d in enumerate(datas):
        n_empresas = 3 + i  # tamanho do universo cresce a cada ano, deterministico
        empresas = [_empresa(f"T{i}_{j}3", f"c{i}_{j}", float(j)) for j in range(n_empresas)]
        por_data[d] = DecisaoResultado(d, UniversoElegivelStats(), empresas)
        for empresa in empresas:
            _seed_precos(session, empresa.ticker, d, date(d.year + 1, 2, 28), 10.0, 0.0, volume=10_000_000.0)

    monkeypatch.setattr(backtest_module, "build_decisao", _fake_build_decisao_factory(por_data))

    folds = walk_forward_folds(
        session, datas, selecionar_universo_completo, POLITICA_PESO_IGUAL, {},
        tamanho_fold=2, custos=CustosSimulacao(0, 0, 0, 0),
    )

    # 6 datas, fold de 2 decisoes + 1 (3 datas por fold) -> folds em [0:3], [2:5], [4:6]
    assert len(folds) == 3
    assert folds[0].datas_decisao == datas[0:3]
    # n_transversal so conta decisoes com retorno realizado dentro do fold (a ultima
    # data do fold nunca e avaliada nele - so na proxima janela, junto da decisao
    # seguinte) - fold [2015,2016,2017] avalia 2015 (n=3) e 2016 (n=4), nunca 2017.
    assert folds[0].n_transversal_min == 3
    assert folds[0].n_transversal_maximo == 4


def test_walk_forward_folds_menos_de_duas_datas_devolve_vazio(tmp_path):
    session = _session(tmp_path)
    assert walk_forward_folds(session, (date(2020, 1, 1),), selecionar_universo_completo, POLITICA_PESO_IGUAL, {}) == []


# ---------------------------------------------------------------------------
# Log de experimentos (Seção 9.2)
# ---------------------------------------------------------------------------


def test_registrar_experimento_grava_com_domain_acoes(tmp_path):
    path = tmp_path / "experiments_acoes.jsonl"
    registrar_experimento("top-N=20 bate equal-weight?", {"n_top": 20}, {"p_valor": 0.03}, path=path)

    carregados = load_experiments(path)
    assert len(carregados) == 1
    assert carregados[0].domain == DOMAIN_ACOES
    assert carregados[0].tool == "acoes_backtest"
