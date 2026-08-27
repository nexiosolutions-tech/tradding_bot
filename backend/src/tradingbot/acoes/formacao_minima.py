"""Formação mínima de carteira — spec 14, Seção 8 (preâmbulo 2026-08-26)/9.

Top-N por score composto, peso igual, rebalanceada mensalmente — o suficiente para o
backtest (Seção 9) responder "o ranking tem sinal?" sem precisar do motor de carteira
completo (tetos por ativo/setor, sobra não alocada, lote fracionário, decomposição por
fator), que só compensa construir depois que esta pergunta tiver resposta.
"""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.acoes.decisao import DecisaoEmpresa, DecisaoResultado

N_PADRAO = 20


@dataclass(frozen=True)
class PosicaoCarteira:
    ticker: str
    cnpj: str
    peso: float
    score_composto: float


def formar_carteira_minima(
    resultado: DecisaoResultado, *, n: int = N_PADRAO
) -> list[PosicaoCarteira]:
    """As `n` empresas de maior `score_composto`, peso igual entre elas. Empresa sem
    score computável (`score_composto is None` — Seção 7.6, caso degenerado de nenhum
    fator aplicável) nunca entra, mesmo que sobrasse vaga — carteira não força posição
    em quem não tem ranking.

    Desempate por ticker (ordem alfabética) quando o score composto empata exatamente —
    raro com float, mas determinístico é melhor que depender da ordem de iteração do
    banco, que não é uma garantia em nenhum lugar desta spec.

    Se o universo com score computável tiver menos de `n` empresas, a carteira sai menor
    que `n`, peso igual entre as que existem — nunca preenche vaga com quem não tem
    score, mesma disciplina de "nunca adivinha" do resto da spec."""
    elegveis: list[DecisaoEmpresa] = [e for e in resultado.empresas if e.score_composto is not None]
    ordenadas = sorted(elegveis, key=lambda e: (-e.score_composto, e.ticker))
    escolhidas = ordenadas[:n]

    if not escolhidas:
        return []

    peso = 1.0 / len(escolhidas)
    return [
        PosicaoCarteira(ticker=e.ticker, cnpj=e.cnpj, peso=peso, score_composto=e.score_composto)
        for e in escolhidas
    ]
