"""Universo elegível — spec 14, Seção 6.

Primeiro artefato que junta as três fundações point-in-time da Fase 1 numa única data de
decisão: identidade (`cnpj_ticker_map.get_cnpj_as_of`), preço (`CotahistPrice`,
persistida) e, separadamente demonstrado no teste de aceite, publicação
(`pointintime.get_latest_filing_as_of`). Opera sobre as tabelas já persistidas pelos
módulos anteriores — nunca re-parseia ZIP da COTAHIST aqui, essa camada já foi ingerida.

Também materializa `setor_ativ` (CVM, `SETOR_ATIV` — cobertura de 100% sobre CNPJ
resolvido, mas taxonomia mais granular que a produção assume) e, lado a lado,
`setor_b3`/`subsetor_b3`/`segmento_b3` (`b3_setor.get_latest_b3_classification` — taxonomia
de produção real, mas só cobre empresa listada hoje, Seção 6.2). Quando não há
classificação B3 para o CNPJ, os três campos ficam `None` — fallback declarado, nunca
adivinhado; a Seção 7 decide como usar os dois lados (provavelmente B3 quando disponível,
CVM como fallback), a Seção 6 só materializa o que é conhecido de cada fonte.

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

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from tradingbot.acoes.b3_setor import get_latest_b3_classification_lote
from tradingbot.acoes.cnpj_ticker_map import get_cnpj_as_of_lote
from tradingbot.acoes.ipca import deflacionar_piso
from tradingbot.acoes.models import CotahistPrice, UniversoElegivel, UniversoExclusao

ROOT_LEN = 4
JANELA_PREGOES_PADRAO = 63
MIN_VOLUME_MEDIANO_PADRAO = 500_000.0
MIN_PREGOES_HISTORICO_PADRAO = 252

# Ancora do piso de liquidez (Seção 6.3) — primeira data de decisão confirmada da série,
# mesma âncora que fecha a fronteira de identidade (Seção 5.6). R$500 mil vale isso em
# reais de 2015-02-27; para qualquer outra data_decisao, o piso é reexpresso pelo IPCA
# acumulado desde então, para não afrouxar sozinho ao longo de uma série que atravessa
# mais de uma década de inflação.
DATA_BASE_LIQUIDEZ = date(2015, 2, 27)

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


def volume_mediano_as_of(session: Session, ticker: str, data_decisao: date, janela_pregoes: int) -> float | None:
    """Pública (não só uso interno do filtro de liquidez) — `backtest.py` (Seção 9)
    reusa a mesma consulta para a checagem mensal da regra de saída por perda de
    liquidez (Seção 8), nunca reimplementada lá."""
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


def volume_mediano_as_of_lote(
    session: Session, tickers: list[str], data_decisao: date, janela_pregoes: int
) -> dict[str, float | None]:
    """Mesma semântica de `volume_mediano_as_of` (mediana dos últimos `janela_pregoes`
    pregões até `data_decisao`), para todos os `tickers` de uma vez — parte da reescrita
    em lote (2026-08-29, achado da Fase 1: 662 round trips desta consulta sozinha para um
    único `build_decisao`). `ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY trade_date
    DESC)` reproduz exatamente o `ORDER BY trade_date DESC LIMIT janela_pregoes` por
    ticker, numa consulta só — não uma aproximação por janela de calendário, que poderia
    cortar pregões de um ticker com histórico intermitente e mudar a mediana."""
    if not tickers:
        return {}
    rn = (
        func.row_number()
        .over(partition_by=CotahistPrice.ticker, order_by=CotahistPrice.trade_date.desc())
        .label("rn")
    )
    subq = (
        select(CotahistPrice.ticker, CotahistPrice.financial_volume, rn)
        .where(CotahistPrice.ticker.in_(tickers), CotahistPrice.trade_date <= data_decisao)
        .subquery()
    )
    stmt = select(subq.c.ticker, subq.c.financial_volume).where(subq.c.rn <= janela_pregoes)
    volumes_por_ticker: dict[str, list[float]] = defaultdict(list)
    for ticker, volume in session.execute(stmt).all():
        volumes_por_ticker[ticker].append(volume)
    return {ticker: _mediana(volumes_por_ticker[ticker]) if volumes_por_ticker[ticker] else None for ticker in tickers}


def contagem_pregoes_lote(
    session: Session, tickers: list[str], data_decisao: date
) -> dict[str, int]:
    """Mesma semântica de `_contagem_pregoes`, para todos os `tickers` de uma vez."""
    if not tickers:
        return {}
    stmt = (
        select(CotahistPrice.ticker, func.count(CotahistPrice.id))
        .where(CotahistPrice.ticker.in_(tickers), CotahistPrice.trade_date <= data_decisao)
        .group_by(CotahistPrice.ticker)
    )
    contagens = {ticker: 0 for ticker in tickers}
    for ticker, n in session.execute(stmt).all():
        contagens[ticker] = n
    return contagens


def _insert_lote_ignorando_duplicata(
    session: Session, model, index_elements: list[str], linhas: list[dict]
) -> tuple[int, int]:
    """`INSERT ... ON CONFLICT DO NOTHING` em lote — substitui o padrão de uma
    `session.begin_nested()` por candidato (achado real da Fase 1 da reescrita em lote,
    2026-08-29: 856 round trips de `SAVEPOINT`/`ROLLBACK TO SAVEPOINT`/`RELEASE
    SAVEPOINT`, 24,6% do tempo em banco de um único `build_decisao`). `ON CONFLICT DO
    NOTHING` (índice `index_elements`, a mesma `UniqueConstraint` de sempre) cobre o caso
    de duplicata **na mesma tabela** — reprocessar uma data já materializada continua
    silenciosamente ignorando o que já existe, mesmo comportamento de antes.

    **Não cobre, de propósito, o conflito entre tabelas** (a trigger de exclusão mútua,
    `models.py`) — essa é responsabilidade de uma constraint diferente (entre
    `universo_elegivel` e `universo_exclusao`, não dentro de uma delas), e `ON CONFLICT`
    só sabe ignorar o índice que foi declarado. Se a trigger disparar aqui, o `INSERT`
    inteiro falha com `IntegrityError` — o lote inteiro, não só a linha conflitante. Isso
    é uma mudança de comportamento real em relação ao insert por candidato (que isolava
    cada tentativa na própria `SAVEPOINT`), mas só se manifesta se este mesmo `ticker`
    já tiver sido escrito do lado oposto por uma execução *anterior* para a mesma
    `data_decisao` — dentro de uma única chamada de `build_universo_elegivel`, um
    candidato nunca é tentado nos dois lados (a precedência de exclusão garante um
    caminho só). Se isso disparar, é o mesmo tipo de corrupção que a trigger existe para
    pegar — falhar o lote inteiro, ruidosamente, é o comportamento correto, não um bug."""
    if not linhas:
        return 0, 0
    dialeto = session.get_bind().dialect.name
    if dialeto == "postgresql":
        stmt = pg_insert(model).values(linhas).on_conflict_do_nothing(index_elements=index_elements)
    elif dialeto == "sqlite":
        stmt = sqlite_insert(model).values(linhas).on_conflict_do_nothing(index_elements=index_elements)
    else:
        raise RuntimeError(f"dialeto nao suportado para insert em lote: {dialeto}")
    resultado = session.execute(stmt.returning(model.id))
    inseridos = len(resultado.fetchall())
    return inseridos, len(linhas) - inseridos


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
    """Reescrita em lote (2026-08-29) — mesma precedência de exclusão, mesmas cinco
    regras, na mesma ordem sequencial (Seção 6). O que muda é só *como* o dado chega:
    cada estágio busca de uma vez, para todos os candidatos ainda vivos naquele estágio,
    em vez de uma consulta por candidato. Nenhuma regra de negócio foi alterada — ver
    `changes/`, 2026-08-29, para a medição que motivou a reescrita e a validação contra
    as doze datas-âncora."""
    stats = UniversoElegivelStats()
    exclusoes: list[dict] = []  # acumuladas em memoria, uma unica insercao em lote ao final

    def _excluir(ticker: str, motivo: str) -> None:
        exclusoes.append({"data_decisao": data_decisao, "ticker": ticker, "motivo": motivo})

    candidatos = _candidatos(session, data_decisao)

    # 1. liquidez — piso deflacionado pelo IPCA (Seção 6.3): min_volume_mediano é sempre
    # em reais de DATA_BASE_LIQUIDEZ, reexpresso em nominais de data_decisao aqui, uma
    # vez só (não depende do ticker). Degrada para min_volume_mediano sem ajuste se o
    # IPCA não estiver ingerido.
    piso_liquidez = deflacionar_piso(min_volume_mediano, DATA_BASE_LIQUIDEZ, data_decisao, session)

    volumes = volume_mediano_as_of_lote(session, candidatos, data_decisao, janela_pregoes)
    liquidos: dict[str, float] = {}
    for ticker in candidatos:
        volume = volumes[ticker]
        if volume is None:
            continue  # nunca negociado ate a data: nao e candidato, nao e exclusao
        if volume < piso_liquidez:
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
    cnpj_por_ticker = get_cnpj_as_of_lote(session, sobreviventes_classe, data_decisao)
    sobreviventes_identidade: list[tuple[str, str]] = []  # (ticker, cnpj)
    for ticker in sobreviventes_classe:
        cnpj = cnpj_por_ticker[ticker]
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
    contagens = contagem_pregoes_lote(session, [t for t, _ in sobreviventes_rj], data_decisao)
    sobreviventes_historico: list[tuple[str, str]] = []
    for ticker, cnpj in sobreviventes_rj:
        if contagens[ticker] < min_pregoes_historico:
            _excluir(ticker, "historico_insuficiente")
            continue
        sobreviventes_historico.append((ticker, cnpj))

    classificacoes = get_latest_b3_classification_lote(
        session, [cnpj for _, cnpj in sobreviventes_historico]
    )
    aceitos: list[dict] = []
    for ticker, cnpj in sobreviventes_historico:
        b3_classificacao = classificacoes[cnpj]
        aceitos.append({
            "data_decisao": data_decisao,
            "ticker": ticker,
            "cnpj": cnpj,
            "setor_ativ": setor_by_cnpj.get(cnpj),
            "setor_b3": b3_classificacao.setor if b3_classificacao else None,
            "subsetor_b3": b3_classificacao.subsetor if b3_classificacao else None,
            "segmento_b3": b3_classificacao.segmento if b3_classificacao else None,
            "volume_mediano": liquidos[ticker],
        })

    stats.excluidos, stats.excluidos_rejeitados_duplicado = _insert_lote_ignorando_duplicata(
        session, UniversoExclusao, ["data_decisao", "ticker"], exclusoes
    )
    stats.aceitos, stats.aceitos_rejeitados_duplicado = _insert_lote_ignorando_duplicata(
        session, UniversoElegivel, ["data_decisao", "ticker"], aceitos
    )

    session.commit()
    return stats
