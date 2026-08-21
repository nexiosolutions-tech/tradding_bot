"""`cnpj_ticker_map` — terceira consulta as-of da Fase 1, spec 14, Seção 5.4/5.5/5.6.
Costura identidade (CNPJ, fundamento) com ticker (preço), a peça que faltava antes da
Seção 6 poder juntar as três fundações point-in-time numa data de decisão.

Identidade em ordem de confiança: FCA direto (`fonte='fca'`, ~92-95% de cobertura na era
confiável 2018+, 100% de precisão auditada) → propagação por raiz de ticker
(`fonte='raiz_propagacao'`, mesma raiz de 4 letras = mesma empresa, classes diferentes —
`VALE5`/`VALE3`) → reconciliação por nome histórico (`fonte='reconciliacao_nome'`, único
caminho para tickers que trocaram de código antes da era confiável, ex. `KROT3`→`COGN3`;
menor confiança, exige match exato de todos os tokens significativos, nunca crédito
parcial em token genérico — o bug que produziu 53% de erro na rodada anterior).

Vigência sempre da COTAHIST (bordas), nunca do FCA (cujas datas medem outra coisa — Seção
5.6). Tolerância de 180 dias sem pregão antes de fechar vigência, para não fragmentar
identidade de papel ilíquido.
"""

from __future__ import annotations

import csv
import re
import unicodedata
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tradingbot.acoes.cotahist_ingestion import parse_cotahist_year
from tradingbot.acoes.models import CnpjTickerMap, UnresolvedTicker

ROOT_LEN = 4
GAP_TOLERANCE_DAYS = 180

_GENERIC_NAME_TOKENS = {
    "PART", "PARTICIPACOES", "SA", "S", "A", "HOLDING", "HOLDINGS", "GRUPO",
    "CIA", "COMPANHIA", "BRASIL", "BRASILEIRA", "NACIONAL", "EMPREENDIMENTOS",
    "COMERCIO", "INDUSTRIA", "INDUSTRIAS", "DE", "DO", "DA",
    # Achados por auditoria manual dos 50 matches de reconciliacao_nome (2026-08-20),
    # não são genéricos por forma gramatical (como PART/HOLDING acima) — cada um
    # colidiu de fato com uma empresa não relacionada no dado real, então tratados como
    # permanentemente não confiáveis como único token de desambiguação:
    # TELEC: BRTO3 "BRASIL TELEC" (Brasil Telecom) casou com CNPJ da TELEBRÁS —
    #   empresas distintas, ambas abreviam "telecomunicações" da mesma forma.
    # IMOB: CCIM3 "CC DES IMOB" casou com BRPR56 Securitizadora — abreviação
    #   genérica de "imobiliário", sem relação real entre as duas.
    # CRUZEIRO: CZRS4 "CRUZEIRO SUL" (Banco Cruzeiro do Sul, CNPJ
    #   62.136.254/0001-99, massa falida) casou com CNPJ 62.984.091/0001-02
    #   (Cruzeiro do Sul Educacional) — confirmado via cad_cia_aberta.csv que são
    #   duas empresas com CNPJs diferentes, coincidência de nome de marca.
    # RAIA: RAIA3 (Droga Raia, pré-fusão 2010) casou com o CNPJ pós-fusão da
    #   RaiaDrogasil (mesmo CNPJ que DROG3/Drogasil resolve) — nome consolidado
    #   pós-evento societário vazando para tickers pré-evento de uma empresa que
    #   era, à época, legalmente distinta.
    "TELEC", "IMOB", "CRUZEIRO", "RAIA",
}


# --------------------------------------------------------------------------- identidade

@dataclass
class FcaIdentity:
    ticker_to_cnpj: dict[str, set[str]] = field(default_factory=dict)
    root_to_cnpj: dict[str, set[str]] = field(default_factory=dict)
    name_history: dict[str, set[str]] = field(default_factory=dict)  # cnpj -> nomes normalizados


def _normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _significant_tokens(name: str) -> set[str]:
    return {
        t for t in _normalize_name(name).split()
        if len(t) >= 4 and t not in _GENERIC_NAME_TOKENS
    }


def load_fca_identity(fca_csv_paths: list[Path]) -> FcaIdentity:
    """Lê `fca_cia_aberta_valor_mobiliario_AAAA.csv` de qualquer ano (não só a era
    confiável — `Nome_Empresarial` vem preenchido mesmo nos anos em que
    `Codigo_Negociacao` vem vazio, o que é exatamente o que a reconciliação por nome
    histórico precisa para casos como `KROT3`→`COGN3`)."""
    identity = FcaIdentity()
    for path in fca_csv_paths:
        with open(path, encoding="latin-1") as f:
            for row in csv.DictReader(f, delimiter=";"):
                cnpj = row["CNPJ_Companhia"].strip()
                if not cnpj:
                    continue
                ticker = row["Codigo_Negociacao"].strip()
                if ticker:
                    identity.ticker_to_cnpj.setdefault(ticker, set()).add(cnpj)
                    identity.root_to_cnpj.setdefault(ticker[:ROOT_LEN], set()).add(cnpj)
                name = row["Nome_Empresarial"].strip()
                if name:
                    identity.name_history.setdefault(cnpj, set()).add(_normalize_name(name))
    return identity


def resolve_identity(ticker: str, nomres: str, identity: FcaIdentity) -> tuple[str, str] | None:
    """Devolve `(cnpj, fonte)` ou `None`. Cada caminho só resolve se o resultado for
    **inequívoco** — mais de um CNPJ candidato é tratado como não resolvido, nunca como
    "escolhe o primeiro" (a causa raiz do erro de 53% na reconciliação por nome anterior)."""
    cnpjs = identity.ticker_to_cnpj.get(ticker)
    if cnpjs and len(cnpjs) == 1:
        return next(iter(cnpjs)), "fca"

    root_cnpjs = identity.root_to_cnpj.get(ticker[:ROOT_LEN])
    if root_cnpjs and len(root_cnpjs) == 1:
        return next(iter(root_cnpjs)), "raiz_propagacao"

    query_tokens = _significant_tokens(nomres)
    if query_tokens:
        matches = {
            cnpj
            for cnpj, names in identity.name_history.items()
            if any(query_tokens <= _significant_tokens(name) for name in names)
        }
        if len(matches) == 1:
            return next(iter(matches)), "reconciliacao_nome"

    return None


# ---------------------------------------------------------------------------- vigência

def compute_vigencia(
    cotahist_zip_paths: list[Path], gap_tolerance_days: int = GAP_TOLERANCE_DAYS
) -> dict[str, tuple[date, date | None]]:
    """Bordas de vigência de cada ticker, derivadas só da COTAHIST — primeira e última
    data de pregão. `data_fim=None` (ainda vigente) se a última data de pregão está a
    `gap_tolerance_days` ou menos do fim da cobertura ingerida; senão, `data_fim` é a
    última data real de pregão (o ticker ficou em silêncio antes do fim da janela
    observada — evidência de saída, não de pausa)."""
    dates_by_ticker: dict[str, list[date]] = defaultdict(list)
    max_date_overall = date.min
    for path in cotahist_zip_paths:
        for raw in parse_cotahist_year(path):
            dates_by_ticker[raw.ticker].append(raw.trade_date)
            if raw.trade_date > max_date_overall:
                max_date_overall = raw.trade_date

    result: dict[str, tuple[date, date | None]] = {}
    for ticker, dates in dates_by_ticker.items():
        dates.sort()
        start, last = dates[0], dates[-1]
        if (max_date_overall - last).days > gap_tolerance_days:
            result[ticker] = (start, last)
        else:
            result[ticker] = (start, None)
    return result


# --------------------------------------------------------------------------- construção

@dataclass
class CnpjTickerMapStats:
    resolved_inserted: int = 0
    resolved_rejected_duplicate: int = 0
    unresolved_inserted: int = 0
    unresolved_rejected_duplicate: int = 0


def build_cnpj_ticker_map(
    session: Session,
    identity: FcaIdentity,
    vigencia: dict[str, tuple[date, date | None]],
    tickers_by_year: dict[int, dict[str, str]],
    data_coleta: date,
) -> CnpjTickerMapStats:
    """`tickers_by_year`: `{ano: {ticker: nomres}}` — o universo elegível (Seção 6) de
    cada ano, já filtrado por liquidez, o único conjunto que precisa de identidade
    resolvida. Um ticker sem vigência calculada (nunca visto na COTAHIST fornecida) é
    pulado — não é o caso de "sem CNPJ", é ausência de dado de preço, erro de outra
    camada."""
    stats = CnpjTickerMapStats()
    seen_tickers: set[str] = set()

    for year, tickers in tickers_by_year.items():
        for ticker, nomres in tickers.items():
            if ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)

            if ticker not in vigencia:
                continue

            resolved = resolve_identity(ticker, nomres, identity)
            data_inicio, data_fim = vigencia[ticker]

            if resolved is None:
                unresolved = UnresolvedTicker(
                    ticker=ticker, checked_year=year, reason="cnpj_nao_resolvido"
                )
                try:
                    with session.begin_nested():
                        session.add(unresolved)
                except IntegrityError:
                    stats.unresolved_rejected_duplicate += 1
                else:
                    stats.unresolved_inserted += 1
                continue

            cnpj, fonte = resolved
            entry = CnpjTickerMap(
                cnpj=cnpj,
                ticker=ticker,
                data_inicio_vigencia=data_inicio,
                data_fim_vigencia=data_fim,
                fonte=fonte,
                data_coleta=data_coleta,
            )
            try:
                with session.begin_nested():
                    session.add(entry)
            except IntegrityError:
                stats.resolved_rejected_duplicate += 1
            else:
                stats.resolved_inserted += 1

    session.commit()
    return stats


# ------------------------------------------------------------------------- consulta as-of

def get_cnpj_as_of(session: Session, ticker: str, data_decisao: date) -> str | None:
    """Mesma convenção de fronteira de `get_filing_as_of` (Seção 5.2): o limite inicial é
    inclusivo (`data_inicio_vigencia <= data_decisao`). O limite final também é inclusivo
    (`data_fim_vigencia >= data_decisao`, ou `NULL` = ainda vigente) — a última data de
    pregão de um ticker é o último dia em que ele de fato representava aquele CNPJ, não o
    primeiro dia em que já não representava. `KROT3` vigente até 2019-10-10 inclusive,
    `COGN3` vigente a partir de 2019-10-11 inclusive — sem sobreposição, sem vão."""
    stmt = (
        select(CnpjTickerMap)
        .where(
            CnpjTickerMap.ticker == ticker,
            CnpjTickerMap.data_inicio_vigencia <= data_decisao,
            or_(
                CnpjTickerMap.data_fim_vigencia.is_(None),
                CnpjTickerMap.data_fim_vigencia >= data_decisao,
            ),
        )
        .order_by(CnpjTickerMap.data_inicio_vigencia.desc())
        .limit(1)
    )
    row = session.execute(stmt).scalar_one_or_none()
    return row.cnpj if row else None
