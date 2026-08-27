"""Formação mínima de carteira — spec 14, Seção 8 (preâmbulo)/9."""

from datetime import date

import pytest

from tradingbot.acoes.decisao import DecisaoEmpresa, DecisaoResultado
from tradingbot.acoes.formacao_minima import N_PADRAO, formar_carteira_minima
from tradingbot.acoes.universo_elegivel import UniversoElegivelStats


def _empresa(ticker, score):
    return DecisaoEmpresa(
        ticker=ticker,
        cnpj=f"cnpj-{ticker}",
        setor_ativ=None,
        setor_b3=None,
        subsetor_b3=None,
        segmento_b3=None,
        earnings_yield_percentil=None,
        divida_liquida_ebitda_percentil=None,
        roe_percentil=None,
        score_composto=score,
        tem_fator_real=score is not None,
    )


def _resultado(empresas):
    return DecisaoResultado(
        data_decisao=date(2016, 2, 29),
        universo_stats=UniversoElegivelStats(),
        empresas=empresas,
    )


def test_top_n_por_score_peso_igual():
    empresas = [_empresa(f"T{i}3", float(i)) for i in range(30)]
    resultado = _resultado(empresas)

    carteira = formar_carteira_minima(resultado, n=5)

    assert len(carteira) == 5
    assert [p.ticker for p in carteira] == ["T293", "T283", "T273", "T263", "T253"]
    assert all(p.peso == pytest.approx(0.2) for p in carteira)
    assert sum(p.peso for p in carteira) == pytest.approx(1.0)


def test_empresa_sem_score_nunca_entra_mesmo_com_vaga_sobrando():
    empresas = [_empresa("AAAA3", 10.0), _empresa("BBBB3", None), _empresa("CCCC3", 5.0)]
    resultado = _resultado(empresas)

    carteira = formar_carteira_minima(resultado, n=5)

    tickers = {p.ticker for p in carteira}
    assert "BBBB3" not in tickers
    assert len(carteira) == 2  # so as duas com score, nunca preenche ate 5
    assert all(p.peso == pytest.approx(0.5) for p in carteira)


def test_empate_exato_desempata_por_ticker_alfabetico():
    empresas = [_empresa("ZZZZ3", 1.0), _empresa("AAAA3", 1.0), _empresa("MMMM3", 1.0)]
    resultado = _resultado(empresas)

    carteira = formar_carteira_minima(resultado, n=2)

    assert [p.ticker for p in carteira] == ["AAAA3", "MMMM3"]


def test_universo_vazio_devolve_carteira_vazia():
    resultado = _resultado([])
    assert formar_carteira_minima(resultado, n=N_PADRAO) == []


def test_todas_empresas_sem_score_devolve_carteira_vazia():
    empresas = [_empresa("AAAA3", None), _empresa("BBBB3", None)]
    resultado = _resultado(empresas)
    assert formar_carteira_minima(resultado, n=N_PADRAO) == []
