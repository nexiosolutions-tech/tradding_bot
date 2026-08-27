"""CDI — spec 14, Seção 9 (benchmark 4).

Fixture real: taxa diária do CDI, janeiro/2015 (série 12 do BCB SGS,
`https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados`, consultada em 2026-08-26).
Capital acumulado esperado calculado independentemente (fora do módulo, compondo as
taxas reais à mão) — mesma disciplina de `test_acoes_ipca.py`.
"""

from datetime import date

import pytest

from tradingbot.acoes.cdi import cdi_equity_curve, get_taxas_no_intervalo, ingest_cdi_series
from tradingbot.acoes.persistence import get_session_factory

# taxa diária real (% ao dia), CDI, BCB SGS 12, janeiro/2015
CDI_REAL_JAN2015 = [
    (date(2015, 1, 2), 0.043455), (date(2015, 1, 5), 0.043455), (date(2015, 1, 6), 0.043455),
    (date(2015, 1, 7), 0.043455), (date(2015, 1, 8), 0.043455), (date(2015, 1, 9), 0.043455),
    (date(2015, 1, 12), 0.043455), (date(2015, 1, 13), 0.043455), (date(2015, 1, 14), 0.043455),
    (date(2015, 1, 15), 0.043455), (date(2015, 1, 16), 0.043455), (date(2015, 1, 19), 0.043455),
    (date(2015, 1, 20), 0.043455), (date(2015, 1, 21), 0.043455), (date(2015, 1, 22), 0.045301),
    (date(2015, 1, 23), 0.045265), (date(2015, 1, 26), 0.045265), (date(2015, 1, 27), 0.045265),
    (date(2015, 1, 28), 0.045265), (date(2015, 1, 29), 0.045265), (date(2015, 1, 30), 0.045265),
]


def _session(tmp_path):
    factory = get_session_factory(f"sqlite:///{tmp_path}/acoes_cdi_test.db")
    return factory()


def test_ingest_cdi_series_e_idempotente(tmp_path):
    session = _session(tmp_path)
    primeira = ingest_cdi_series(session, CDI_REAL_JAN2015)
    segunda = ingest_cdi_series(session, CDI_REAL_JAN2015)
    assert primeira == len(CDI_REAL_JAN2015)
    assert segunda == 0


def test_get_taxas_no_intervalo_e_exclusivo_no_inicio_inclusivo_no_fim(tmp_path):
    session = _session(tmp_path)
    ingest_cdi_series(session, CDI_REAL_JAN2015)

    taxas = get_taxas_no_intervalo(session, date(2015, 1, 2), date(2015, 1, 9))

    assert [d for d, _ in taxas] == [
        date(2015, 1, 5), date(2015, 1, 6), date(2015, 1, 7), date(2015, 1, 8), date(2015, 1, 9)
    ]


def test_cdi_equity_curve_compoe_taxas_diarias_reais_ate_numero_calculado_a_mao(tmp_path):
    """Trava contra o número composto à mão fora do módulo (5 dias a 0.043455% a.d.),
    não contra a mesma lógica de composição reaplicada."""
    session = _session(tmp_path)
    ingest_cdi_series(session, CDI_REAL_JAN2015)

    curva = cdi_equity_curve(session, [date(2015, 1, 2), date(2015, 1, 9)], capital_inicial=10_000.0)

    assert curva[0] == (date(2015, 1, 2), 10_000.0)
    assert curva[1][0] == date(2015, 1, 9)
    assert curva[1][1] == pytest.approx(10_021.746391577803, rel=1e-9)


def test_cdi_equity_curve_mes_inteiro_real(tmp_path):
    session = _session(tmp_path)
    ingest_cdi_series(session, CDI_REAL_JAN2015)

    curva = cdi_equity_curve(session, [date(2015, 1, 2), date(2015, 1, 30)], capital_inicial=10_000.0)

    assert curva[-1][1] == pytest.approx(10_088.550922731734, rel=1e-9)


def test_cdi_equity_curve_ordena_datas_fora_de_ordem(tmp_path):
    session = _session(tmp_path)
    ingest_cdi_series(session, CDI_REAL_JAN2015)

    curva = cdi_equity_curve(session, [date(2015, 1, 9), date(2015, 1, 2)], capital_inicial=10_000.0)

    assert [d for d, _ in curva] == [date(2015, 1, 2), date(2015, 1, 9)]


def test_cdi_equity_curve_lista_vazia_devolve_vazia(tmp_path):
    session = _session(tmp_path)
    assert cdi_equity_curve(session, [], capital_inicial=10_000.0) == []


def test_cdi_equity_curve_sem_dado_congela_capital(tmp_path):
    """Sem CDI ingerido para o intervalo, nunca inventa taxa — o capital fica congelado
    no trecho sem dado, mesma disciplina de `get_ipca_as_of`/`deflacionar_piso`."""
    session = _session(tmp_path)
    curva = cdi_equity_curve(session, [date(2015, 1, 2), date(2015, 1, 9)], capital_inicial=10_000.0)
    assert curva == [(date(2015, 1, 2), 10_000.0), (date(2015, 1, 9), 10_000.0)]
