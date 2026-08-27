"""Deflação IPCA — spec 14, Seção 6.3.

Existe para uma coisa só: o piso de liquidez (`MIN_VOLUME_MEDIANO_PADRAO`,
`universo_elegivel.py`) é nominal, e a série de decisão atravessa 2015-2026 — mais de
uma década de inflação acumulada. Sem deflação, o mesmo valor nominal fica
progressivamente mais fácil de passar ao longo da série, afrouxando o piso sozinho, sem
nenhuma decisão de desenho pedindo isso.

Fonte: Banco Central — SGS, série 433 (IPCA, variação mensal) — a mesma fonte já
declarada para Selic/CDI/câmbio (Seção 4.3), cobre IPCA também.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tradingbot.acoes.models import IpcaIndice


def build_indice_acumulado(variacoes_mensais: list[tuple[date, float]]) -> list[tuple[date, float]]:
    """`variacoes_mensais`: `[(primeiro_dia_do_mes, variacao_percentual_no_mes), ...]`,
    em ordem cronológica (o formato bruto da série 433 do BCB). Encadeia num
    número-índice, base 100 no primeiro mês — a base é arbitrária, cancela na razão
    usada por `deflacionar_piso`, nunca comparada em valor absoluto fora deste módulo."""
    indice = 100.0
    resultado = []
    for data_mes, variacao_pct in variacoes_mensais:
        indice *= 1 + variacao_pct / 100
        resultado.append((data_mes, indice))
    return resultado


def ingest_ipca_series(session: Session, variacoes_mensais: list[tuple[date, float]]) -> int:
    """Append-only por `data_referencia` — mesmo padrão do resto da spec, reingerir a
    mesma série é seguro (duplicata rejeitada pela `UniqueConstraint`, banco decide)."""
    inseridos = 0
    for data_mes, numero_indice in build_indice_acumulado(variacoes_mensais):
        try:
            with session.begin_nested():
                session.add(IpcaIndice(data_referencia=data_mes, numero_indice=numero_indice))
        except IntegrityError:
            pass
        else:
            inseridos += 1
    session.commit()
    return inseridos


def get_ipca_as_of(session: Session, data: date) -> float | None:
    """Mesma convenção point-in-time do resto da spec: a publicação mais recente com
    `data_referencia <= data`. `None` se o IPCA não estiver ingerido para nenhum mês
    até essa data — nunca inventa inflação para uma data sem dado publicado."""
    stmt = (
        select(IpcaIndice.numero_indice)
        .where(IpcaIndice.data_referencia <= data)
        .order_by(IpcaIndice.data_referencia.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def deflacionar_piso(
    piso_nominal_base: float, data_base: date, data_decisao: date, session: Session
) -> float:
    """Reexpressa `piso_nominal_base` (ancorado em `data_base`) em reais nominais de
    `data_decisao`, mantendo o mesmo poder de compra — o piso *sobe* ao longo do tempo,
    na mesma proporção dos preços em geral, em vez de ficar estático enquanto tudo ao
    redor sobe. Degrada para o piso nominal sem ajuste (`piso_nominal_base`) se o IPCA
    não cobrir alguma das duas datas — nunca bloqueia o cálculo do universo por falta de
    um dado macro auxiliar, e mantém qualquer caminho que não ingeriu IPCA funcionando
    exatamente como antes desta seção (o comportamento antigo é o caso degenerado do
    novo, não um caminho separado)."""
    indice_base = get_ipca_as_of(session, data_base)
    indice_decisao = get_ipca_as_of(session, data_decisao)
    if indice_base is None or indice_decisao is None:
        return piso_nominal_base
    return piso_nominal_base * (indice_decisao / indice_base)
