"""Fase 1 do módulo de Ações — ingestão de preço bruto COTAHIST e eventos societários
tipo+data (spec 14, Seção 4.2/5.3). Fixture em `tests/fixtures/cotahist/` é um extrato
real (8 registros reais, mesmo cabeçalho/rodapé do formato oficial) do
`COTAHIST_A2024.ZIP` baixado de `bvmf.bmfbovespa.com.br` em 2026-08-20 — cobre a
transição real EB (bonificação) e EDJ (dividendo+juros) do BBAS3. A verificação de
FATCOT usa valores reais de `FNAM11`/`SMLL11` medidos diretamente contra o arquivo
original (não incluídos na fixture — são fundos, fora do universo de ações — mas os
números vêm de linhas reais inspecionadas, não inventados).
"""

import pytest

from tradingbot.acoes.cotahist_ingestion import (
    ingest_cotahist_year,
    normalize_price,
    parse_cotahist_year,
)
from tradingbot.acoes.models import CorporateEventFlag, CotahistPrice
from tradingbot.acoes.persistence import get_session_factory
from tradingbot.acoes.price_sanity import find_implausible_returns
from pathlib import Path
from sqlalchemy import select

FIXTURE = Path(__file__).parent / "fixtures" / "cotahist" / "COTAHIST_A2024_real_extract.ZIP"


def _session(tmp_path):
    factory = get_session_factory(f"sqlite:///{tmp_path}/acoes_cotahist_test.db")
    return factory()


def test_normalize_price_matches_real_traded_average():
    """FNAM11, 2024-01-02, linha real: PREULT bruto=34 (R$0,34), FATCOT=1000,
    QUATOT=715000, VOLTOT=R$242,21. Preço médio real do dia (VOLTOT/QUATOT) é
    invariante a qualquer convenção de escala — bate com PREULT normalizado.
    SMLL11, 2024-10-16: PREULT bruto=203300 (R$2033,00), FATCOT=10 (valor não
    documentado no layout oficial, só '1' e '1000' são descritos, mas presente no
    dado real), QUATOT=4890, VOLTOT=R$994137,00."""
    fnam11 = normalize_price(34, 1000)
    assert fnam11 == pytest.approx(242.21 / 715000, rel=0.05)

    smll11 = normalize_price(203300, 10)
    assert smll11 == pytest.approx(994137.00 / 4890, rel=1e-6)


def test_parse_equity_only_excludes_funds():
    """O filtro `equity_only` (default) exclui FNAM11/SMLL11 do universo — são fundos
    (CODBDI != 02 ou ESPECI fora de ON/PN/PR/OR/UNT), corretamente fora do escopo da
    Seção 6. Confirma que o parser da fixture só devolve as 6 linhas de BBAS3."""
    rows = list(parse_cotahist_year(FIXTURE))
    assert len(rows) == 6
    assert all(r.ticker == "BBAS3" for r in rows)


def test_ingest_prices_is_append_only(tmp_path):
    session = _session(tmp_path)
    first = ingest_cotahist_year(session, FIXTURE)
    assert first.prices_inserted == 6
    assert first.prices_rejected_duplicate == 0

    second = ingest_cotahist_year(session, FIXTURE)
    assert second.prices_inserted == 0
    assert second.prices_rejected_duplicate == 6


def test_prices_normalized_fatcot_1_equal_to_raw(tmp_path):
    """BBAS3 na fixture tem FATCOT=1 em todos os pregões — preço normalizado deve bater
    exatamente com o preço bruto do arquivo (nenhuma escala aplicada)."""
    session = _session(tmp_path)
    ingest_cotahist_year(session, FIXTURE)

    row = session.execute(
        select(CotahistPrice).where(
            CotahistPrice.ticker == "BBAS3", CotahistPrice.trade_date == "2024-04-15"
        )
    ).scalar_one()
    assert row.fatcot == 1
    assert row.close == pytest.approx(56.46)


def test_corporate_event_detected_only_on_first_day_of_transition(tmp_path):
    """A transição ON -> ON EB (2024-04-16) gera um evento; o pregão seguinte
    (2024-04-17), ainda EB, não gera um segundo — confirmado contra o padrão real (a
    mesma sequência de sufixo persistiu ~8 pregões para o BBAS3 em outra janela do
    mesmo ano, e só a primeira data importa)."""
    session = _session(tmp_path)
    stats = ingest_cotahist_year(session, FIXTURE)

    # duas transições reais na fixture: ON->EB em 04-16, ON->EDJ em 06-12
    assert stats.events_inserted == 2

    events = session.execute(
        select(CorporateEventFlag).order_by(CorporateEventFlag.event_date)
    ).scalars().all()
    assert [(e.ex_suffix, str(e.event_date)) for e in events] == [
        ("EB", "2024-04-16"),
        ("EDJ", "2024-06-12"),
    ]


def test_bonificacao_is_level_break_dividendo_juros_is_not(tmp_path):
    """EB (bonificação) muda quantidade de ações sem contrapartida em caixa — quebra de
    nível real, medida: -50,57% no dia. EDJ (dividendo+juros) é distribuição em caixa,
    o preço bruto ali é movimento de mercado real, não uma descontinuidade artificial —
    medido: -3,53%, dentro do normal."""
    session = _session(tmp_path)
    ingest_cotahist_year(session, FIXTURE)

    eb = session.execute(
        select(CorporateEventFlag).where(CorporateEventFlag.ex_suffix == "EB")
    ).scalar_one()
    assert eb.is_level_break is True

    edj = session.execute(
        select(CorporateEventFlag).where(CorporateEventFlag.ex_suffix == "EDJ")
    ).scalar_one()
    assert edj.is_level_break is False


def test_implausible_return_flagged_only_when_unexplained(tmp_path):
    """A quebra real do EB é -50,57% — abaixo do limiar padrão de 60% (Seção 5.3), então
    usa-se aqui um limiar de 40% para exercitar a detecção sem depender de um evento
    ainda maior. Com o evento presente, o detector não acusa (a queda tem explicação);
    apagando o `CorporateEventFlag` real (simula normalização/detecção que falhou), o
    detector precisa acusar — prova que ele reage à ausência do evento, não a um caso
    fabricado do zero."""
    session = _session(tmp_path)
    ingest_cotahist_year(session, FIXTURE)

    # com o evento real presente, a queda de -50,57% do EB é esperada, não acusada
    assert find_implausible_returns(session, threshold=0.40) == []

    # remove o CorporateEventFlag do EB (simula normalização/deteccao que falhou)
    eb = session.execute(
        select(CorporateEventFlag).where(CorporateEventFlag.ex_suffix == "EB")
    ).scalar_one()
    session.delete(eb)
    session.commit()

    anomalies = find_implausible_returns(session, threshold=0.40)
    assert len(anomalies) == 1
    assert anomalies[0].ticker == "BBAS3"
    assert str(anomalies[0].date_to) == "2024-04-16"
    assert anomalies[0].pct_change < -0.5
