"""CDI — spec 14, Seção 9 (benchmark 4: custo de oportunidade real no Brasil).

Fonte: Banco Central — SGS, série 12 (CDI, taxa diária, % ao dia) — mesma fonte já
declarada para Selic/IPCA/câmbio (Seção 4.3). Diferente de `ipca.py`, que encadeia a
série inteira numa base fixa, aqui o encadeamento acontece sob demanda
(`cdi_equity_curve`) para o intervalo exato de cada curva de equity simulada — o CDI é
sempre consumido como "quanto renderia esse capital nesse período", nunca como
número-índice comparado em valor absoluto fora deste módulo.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tradingbot.acoes.models import CdiTaxa


def ingest_cdi_series(session: Session, taxas_diarias: list[tuple[date, float]]) -> int:
    """`taxas_diarias`: `[(data, taxa_pct_ao_dia), ...]` — o formato bruto da série 12
    do BCB. Append-only por `data_referencia` — reingerir a mesma série é seguro
    (duplicata rejeitada pela `UniqueConstraint`, banco decide)."""
    inseridos = 0
    for data_referencia, taxa_diaria_pct in taxas_diarias:
        try:
            with session.begin_nested():
                session.add(CdiTaxa(data_referencia=data_referencia, taxa_diaria_pct=taxa_diaria_pct))
        except IntegrityError:
            pass
        else:
            inseridos += 1
    session.commit()
    return inseridos


def get_taxas_no_intervalo(session: Session, data_inicio: date, data_fim: date) -> list[tuple[date, float]]:
    """Todas as taxas diárias com `data_inicio < data_referencia <= data_fim` — fronteira
    igual à do resto da spec (inclusiva no fim), exclusiva no início porque o capital já
    está posicionado desde `data_inicio`, o primeiro dia a render é o seguinte."""
    stmt = (
        select(CdiTaxa.data_referencia, CdiTaxa.taxa_diaria_pct)
        .where(CdiTaxa.data_referencia > data_inicio, CdiTaxa.data_referencia <= data_fim)
        .order_by(CdiTaxa.data_referencia.asc())
    )
    return list(session.execute(stmt).all())


def cdi_equity_curve(
    session: Session, datas: list[date], capital_inicial: float = 10_000.0
) -> list[tuple[date, float]]:
    """Curva de equity do CDI marcada nas mesmas `datas` de rebalanceamento das outras
    curvas do backtest (Seção 9) — para que `total_return_pct`/`volatility_pct`/etc.
    (`backtest.py`) rodem sobre o CDI com a matemática idêntica à de qualquer outra
    curva, sem fórmula separada.

    Cada ponto composto as taxas diárias reais do intervalo desde a data anterior — não
    aproxima por uma taxa mensal fixa. `[]` se `datas` estiver vazio; um ponto por data,
    mesmo que falte CDI para algum sub-intervalo (nesse caso o capital fica congelado
    naquele trecho — nunca inventa taxa para um dia sem dado publicado)."""
    if not datas:
        return []

    ordenadas = sorted(datas)
    curva: list[tuple[date, float]] = [(ordenadas[0], capital_inicial)]
    capital = capital_inicial

    for anterior, atual in zip(ordenadas, ordenadas[1:]):
        for _, taxa_diaria_pct in get_taxas_no_intervalo(session, anterior, atual):
            capital *= 1 + taxa_diaria_pct / 100
        curva.append((atual, capital))

    return curva
