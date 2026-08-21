"""Universo elegível — spec 14, Seção 6.

Primeiro artefato que junta as três fundações point-in-time da Fase 1 numa única data de
decisão: identidade (`cnpj_ticker_map.get_cnpj_as_of`), preço (`CotahistPrice`,
persistida) e, separadamente demonstrado no teste de aceite, publicação
(`pointintime.get_latest_filing_as_of`). Opera sobre as tabelas já persistidas pelos
módulos anteriores — nunca re-parseia ZIP da COTAHIST aqui, essa camada já foi ingerida.

**Mesmo relógio nas três consultas as-of**: todas usam fronteira inclusiva em
`data_decisao` (`trade_date <= data_decisao` para preço, `data_inicio_vigencia <=
data_decisao <= data_fim_vigencia` para identidade, `dt_receb <= data_decisao` para
publicação) — a mesma convenção testada em `get_filing_as_of`. Fazer qualquer uma delas
divergir (por exemplo, comparar preço com `<` em vez de `<=`) reintroduziria exatamente o
vazamento de um dia que a Seção 5.2 já tinha fechado, só que agora entre camadas em vez de
dentro de uma.

**Precedência de exclusão explícita, sequencial** — um ticker só chega a um motivo
posterior se sobreviveu a todos os anteriores, então nunca há ambiguidade sobre qual
motivo registrar quando mais de um se aplicaria (ex. papel ilíquido E sem identidade
resolvida sai por `iliquido`, o primeiro da cadeia, nunca por `identidade_nao_resolvida`):

1. `iliquido` — mediana de `VOLTOT` na janela móvel abaixo do piso.
2. `classe_secundaria` — mesma raiz de 4 letras que uma classe mais líquida já escolhida.
3. `identidade_nao_resolvida` — `get_cnpj_as_of` devolve `None` na data de decisão.
4. `recuperacao_judicial` — CNPJ na lista de RJ (fonte real ainda pendente, Seção 13;
   lista vazia por padrão não exclui ninguém por este motivo nesta rodada).
5. `historico_insuficiente` — menos de `min_pregoes_historico` pregões observados do
   próprio ticker até a data de decisão (proxy independente de qualquer fator específico
   da Seção 7, que ainda não existe como código — o número exato pode precisar de revisão
   quando os fatores forem implementados).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import distinct, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tradingbot.acoes.cnpj_ticker_map import get_cnpj_as_of
from tradingbot.acoes.models import CotahistPrice, UniversoElegivel, UniversoExclusao

ROOT_LEN = 4
JANELA_PREGOES_PADRAO = 63
MIN_VOLUME_MEDIANO_PADRAO = 500_000.0
MIN_PREGOES_HISTORICO_PADRAO = 252

EXCLUSION_PRECEDENCE = (
    "iliquido",
    "classe_secundaria",
    "identidade_nao_resolvida",
    "recuperacao_judicial",
    "historico_insuficiente",
)


def _mediana(valores: list[float]) -> float:
    ordenados = sorted(valores)
    return ordenados[len(ordenados) // 2]


@dataclass
class UniversoElegivelStats:
    aceitos: int = 0
    aceitos_rejeitados_duplicado: int = 0
    excluidos: int = 0
    excluidos_rejeitados_duplicado: int = 0


def _candidatos(session: Session, data_decisao: date) -> list[str]:
    janela_calendario = timedelta(days=200)  # cobre 63 pregões com folga (feriados/fins de semana)
    stmt = (
        select(distinct(CotahistPrice.ticker))
        .where(
            CotahistPrice.trade_date <= data_decisao,
            CotahistPrice.trade_date >= data_decisao - janela_calendario,
        )
    )
    return [row[0] for row in session.execute(stmt).all()]


def _volume_mediano(session: Session, ticker: str, data_decisao: date, janela_pregoes: int) -> float | None:
    stmt = (
        select(CotahistPrice.financial_volume)
        .where(CotahistPrice.ticker == ticker, CotahistPrice.trade_date <= data_decisao)
        .order_by(CotahistPrice.trade_date.desc())
        .limit(janela_pregoes)
    )
    volumes = [row[0] for row in session.execute(stmt).all()]
    if not volumes:
        return None
    return _mediana(volumes)


def _contagem_pregoes(session: Session, ticker: str, data_decisao: date) -> int:
    stmt = select(CotahistPrice.id).where(
        CotahistPrice.ticker == ticker, CotahistPrice.trade_date <= data_decisao
    )
    return len(session.execute(stmt).all())


def build_universo_elegivel(
    session: Session,
    data_decisao: date,
    setor_by_cnpj: dict[str, str],
    *,
    min_volume_mediano: float = MIN_VOLUME_MEDIANO_PADRAO,
    janela_pregoes: int = JANELA_PREGOES_PADRAO,
    min_pregoes_historico: int = MIN_PREGOES_HISTORICO_PADRAO,
    recuperacao_judicial: frozenset[str] = frozenset(),
) -> UniversoElegivelStats:
    stats = UniversoElegivelStats()

    def _excluir(ticker: str, motivo: str) -> None:
        row = UniversoExclusao(data_decisao=data_decisao, ticker=ticker, motivo=motivo)
        try:
            with session.begin_nested():
                session.add(row)
        except IntegrityError:
            stats.excluidos_rejeitados_duplicado += 1
        else:
            stats.excluidos += 1

    candidatos = _candidatos(session, data_decisao)

    # 1. liquidez
    liquidos: dict[str, float] = {}
    for ticker in candidatos:
        volume = _volume_mediano(session, ticker, data_decisao, janela_pregoes)
        if volume is None:
            continue  # nunca negociado ate a data: nao e candidato, nao e exclusao
        if volume < min_volume_mediano:
            _excluir(ticker, "iliquido")
            continue
        liquidos[ticker] = volume

    # 2. uma classe por empresa (raiz de 4 letras, classe mais liquida sobrevive)
    por_raiz: dict[str, list[str]] = {}
    for ticker in liquidos:
        por_raiz.setdefault(ticker[:ROOT_LEN], []).append(ticker)

    sobreviventes_classe: list[str] = []
    for raiz, tickers_da_raiz in por_raiz.items():
        escolhido = max(tickers_da_raiz, key=lambda t: liquidos[t])
        sobreviventes_classe.append(escolhido)
        for outro in tickers_da_raiz:
            if outro != escolhido:
                _excluir(outro, "classe_secundaria")

    # 3. identidade resolvida na data de decisao
    sobreviventes_identidade: list[tuple[str, str]] = []  # (ticker, cnpj)
    for ticker in sobreviventes_classe:
        cnpj = get_cnpj_as_of(session, ticker, data_decisao)
        if cnpj is None:
            _excluir(ticker, "identidade_nao_resolvida")
            continue
        sobreviventes_identidade.append((ticker, cnpj))

    # 4. recuperacao judicial
    sobreviventes_rj: list[tuple[str, str]] = []
    for ticker, cnpj in sobreviventes_identidade:
        if cnpj in recuperacao_judicial:
            _excluir(ticker, "recuperacao_judicial")
            continue
        sobreviventes_rj.append((ticker, cnpj))

    # 5. historico minimo
    for ticker, cnpj in sobreviventes_rj:
        if _contagem_pregoes(session, ticker, data_decisao) < min_pregoes_historico:
            _excluir(ticker, "historico_insuficiente")
            continue

        entry = UniversoElegivel(
            data_decisao=data_decisao,
            ticker=ticker,
            cnpj=cnpj,
            setor_ativ=setor_by_cnpj.get(cnpj),
            volume_mediano=liquidos[ticker],
        )
        try:
            with session.begin_nested():
                session.add(entry)
        except IntegrityError:
            stats.aceitos_rejeitados_duplicado += 1
        else:
            stats.aceitos += 1

    session.commit()
    return stats
