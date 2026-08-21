"""Sanidade da série de preço bruto — spec 14, Seção 5.3. Nenhum retorno diário deveria
exceder um limiar de plausibilidade sem uma quebra de nível conhecida explicando —
FATCOT mal normalizado e evento societário não tratado produzem exatamente esse padrão
(salto grande, sem contrapartida em `CorporateEventFlag`), e o pipeline deve **detectar
isso explicitamente**, não deixar passar como um dado de mercado normal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.acoes.models import CorporateEventFlag, CotahistPrice

DEFAULT_IMPLAUSIBLE_RETURN_THRESHOLD = 0.60


@dataclass(frozen=True)
class ImplausibleReturn:
    ticker: str
    date_from: date
    date_to: date
    close_from: float
    close_to: float
    pct_change: float


def find_implausible_returns(
    session: Session, threshold: float = DEFAULT_IMPLAUSIBLE_RETURN_THRESHOLD
) -> list[ImplausibleReturn]:
    prices = session.execute(
        select(CotahistPrice).order_by(CotahistPrice.ticker, CotahistPrice.trade_date)
    ).scalars().all()

    level_break_dates: dict[str, set[date]] = {}
    for event in session.execute(
        select(CorporateEventFlag).where(CorporateEventFlag.is_level_break.is_(True))
    ).scalars():
        level_break_dates.setdefault(event.ticker, set()).add(event.event_date)

    anomalies: list[ImplausibleReturn] = []
    previous: CotahistPrice | None = None
    for price in prices:
        if previous is not None and previous.ticker == price.ticker and previous.close:
            pct_change = (price.close - previous.close) / previous.close
            if abs(pct_change) > threshold and price.trade_date not in level_break_dates.get(
                price.ticker, set()
            ):
                anomalies.append(
                    ImplausibleReturn(
                        ticker=price.ticker,
                        date_from=previous.trade_date,
                        date_to=price.trade_date,
                        close_from=previous.close,
                        close_to=price.close,
                        pct_change=pct_change,
                    )
                )
        previous = price
    return anomalies
