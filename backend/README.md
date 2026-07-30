# Backend

Implementação das Fases 1–5 do roadmap (`specs/11-roadmap-e-fases.md`):
ingestão (spec 02), features (spec 03), modelo ML (spec 04), risco (spec 05),
execução (spec 06), backtesting (spec 07), API do dashboard (spec 08),
aprendizado contínuo (spec 09).

## Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Rodar os testes

```bash
python -m pytest -q
```

Todo código que envolve dinheiro (sizing, custos, P&L, drawdown, circuit breaker,
execução de ordens) tem teste unitário em `tests/`, conforme exigido em
[`CLAUDE.md`](../CLAUDE.md). A camada de execução é testada contra um
`FakeExchangeClient` em memória (`tests/fakes.py`) — nunca contra a rede.

## Scripts

| Script | Fase | O que faz |
|---|---|---|
| `run_backtest.py --symbol BTCUSDT --interval 1m --days 7` | 1 | Backtest de ponta a ponta com dados reais da Binance (endpoint público, sem API key) |
| `train_model.py --symbol BTCUSDT --interval 1m --days 45` | 2 | Treina com walk-forward; só salva o modelo se vencer o baseline em **todos** os folds |
| `run_live.py` | 4 | Worker standalone: conecta no testnet e roda o `Orchestrator` (alternativa a rodar tudo dentro da API) |
| `run_daily_learning.py [--date AAAA-MM-DD]` | 5 | Analisa trades do dia, gera `learnings/` e rascunha `changes/` — pensado para cron diário |

Relatórios/modelos vão para `../results/` (gitignored). `run_backtest.py` e
`train_model.py` não precisam de credenciais; `run_live.py` e a API (abaixo)
precisam.

## Subir a API + dashboard localmente

```bash
uvicorn tradingbot.api.app:app --reload
```

Sem `BINANCE_API_KEY`/`BINANCE_API_SECRET` no ambiente, a API sobe normalmente
e todas as views que dependem de `results/`/banco funcionam — só a view "Live"
mostra "engine não configurado". Para ligar a execução real (Fase 4), gere
chaves em [testnet.binance.vision](https://testnet.binance.vision) e exporte:

```bash
export BINANCE_API_KEY=...
export BINANCE_API_SECRET=...
# BINANCE_TESTNET=false exigiria mainnet — bloqueado por padrão (CLAUDE.md regra 1/6)
```

O engine sempre inicia **pausado**; ligar a execução é uma ação explícita no
dashboard (Play), nunca automática ao subir o processo.

## Estratégia ativa

Enquanto nenhum modelo (Fase 2) for promovido, `bootstrap.load_active_strategy()`
usa `RsiBollingerPlaceholderStrategy` (`src/tradingbot/backtesting/strategy.py`)
— uma regra simples de mean-reversion que existe só para exercitar a
infraestrutura de ponta a ponta, não é uma recomendação de estratégia.

## Lacunas conhecidas antes de qualquer capital real

Ver [`specs/06-camada-de-execucao.md`](../specs/06-camada-de-execucao.md#status-de-implementação-fase-4)
para o detalhe: contabilização de taxas em ordens reais ainda é `0.0`
(sinalizado, não fabricado), e reconciliação de ordem de entrada perdida por
crash entre confirmação da exchange e persistência local ainda não é tratada.

## Persistência

`src/tradingbot/persistence/` usa SQLAlchemy — SQLite local por padrão
(`../results/tradingbot.db`, gitignored), PostgreSQL em produção via
`DATABASE_URL` (Railway). Nenhuma query muda entre os dois.
