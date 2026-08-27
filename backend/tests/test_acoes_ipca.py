"""Deflação IPCA — spec 14, Seção 6.3.

Fixture real: variação mensal do IPCA, janeiro/2015 a fevereiro/2016 (série 433 do BCB
SGS, `https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados`, consultada em
2026-08-26). Índice acumulado esperado calculado independentemente (fora do módulo,
encadeando as variações reais à mão) para travar contra um número conhecido, não contra
"a mesma lógica" do próprio `build_indice_acumulado`.
"""

from datetime import date

import pytest

from tradingbot.acoes.ipca import (
    build_indice_acumulado,
    deflacionar_piso,
    get_ipca_as_of,
    ingest_ipca_series,
)
from tradingbot.acoes.persistence import get_session_factory

# variação mensal real (%), IPCA, BCB SGS 433, jan/2015-fev/2016
IPCA_REAL_JAN2015_FEV2016 = [
    (date(2015, 1, 1), 1.24), (date(2015, 2, 1), 1.22), (date(2015, 3, 1), 1.32),
    (date(2015, 4, 1), 0.71), (date(2015, 5, 1), 0.74), (date(2015, 6, 1), 0.79),
    (date(2015, 7, 1), 0.62), (date(2015, 8, 1), 0.22), (date(2015, 9, 1), 0.54),
    (date(2015, 10, 1), 0.82), (date(2015, 11, 1), 1.01), (date(2015, 12, 1), 0.96),
    (date(2016, 1, 1), 1.27), (date(2016, 2, 1), 0.90),
]


def _session(tmp_path):
    factory = get_session_factory(f"sqlite:///{tmp_path}/acoes_ipca_test.db")
    return factory()


def test_build_indice_acumulado_bate_com_encadeamento_manual_real():
    """Trava contra o número calculado à mão fora do módulo, não contra a mesma lógica
    reaplicada — mesma disciplina da regressão dos 712 matches do cnpj_ticker_map."""
    indice = build_indice_acumulado(IPCA_REAL_JAN2015_FEV2016)
    por_data = dict(indice)
    assert por_data[date(2015, 2, 1)] == pytest.approx(102.475128, rel=1e-6)
    assert por_data[date(2016, 2, 1)] == pytest.approx(113.087763, rel=1e-6)


def test_get_ipca_as_of_usa_ultima_publicacao_ate_a_data(tmp_path):
    session = _session(tmp_path)
    ingest_ipca_series(session, IPCA_REAL_JAN2015_FEV2016)

    # data exatamente no mes publicado
    assert get_ipca_as_of(session, date(2016, 2, 1)) == pytest.approx(113.087763, rel=1e-6)
    # data no meio do mes seguinte, sem publicacao propria: usa a ultima conhecida
    assert get_ipca_as_of(session, date(2016, 2, 27)) == pytest.approx(113.087763, rel=1e-6)
    # antes de qualquer publicacao ingerida
    assert get_ipca_as_of(session, date(2014, 12, 31)) is None


def test_ingest_ipca_series_e_idempotente(tmp_path):
    session = _session(tmp_path)
    primeira = ingest_ipca_series(session, IPCA_REAL_JAN2015_FEV2016)
    segunda = ingest_ipca_series(session, IPCA_REAL_JAN2015_FEV2016)
    assert primeira == len(IPCA_REAL_JAN2015_FEV2016)
    assert segunda == 0


def test_deflacionar_piso_sobe_com_inflacao_acumulada_real(tmp_path):
    """R$500 mil ancorado em 2015-02-27 precisa de mais reais nominais em 2016-02-29
    para manter o mesmo poder de compra — o piso deve *subir*, nunca ficar igual nem
    cair, com inflação positiva acumulada real no período."""
    session = _session(tmp_path)
    ingest_ipca_series(session, IPCA_REAL_JAN2015_FEV2016)

    piso_base = 500_000.0
    piso_2016 = deflacionar_piso(piso_base, date(2015, 2, 27), date(2016, 2, 29), session)

    assert piso_2016 > piso_base
    fator_esperado = 113.087763 / 102.475128  # indices reais de fev/2016 e fev/2015
    assert piso_2016 == pytest.approx(piso_base * fator_esperado, rel=1e-6)


def test_deflacionar_piso_degrada_para_nominal_sem_ipca_ingerido(tmp_path):
    """Sem IPCA ingerido, o piso não é bloqueado nem inventa inflação — usa o valor
    nominal sem ajuste, o mesmo comportamento de antes desta seção. Todo teste que não
    ingere IPCA continua funcionando exatamente como funcionava."""
    session = _session(tmp_path)
    piso = deflacionar_piso(500_000.0, date(2015, 2, 27), date(2026, 2, 27), session)
    assert piso == 500_000.0
