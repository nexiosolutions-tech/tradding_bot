# Backend — Fase 1

Implementação de ingestão (spec 02), motor de features (spec 03), gestão de risco
(spec 05) e backtesting event-driven (spec 07), conforme
[`specs/11-roadmap-e-fases.md`](../specs/11-roadmap-e-fases.md).

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

Todo código que envolve dinheiro (sizing, custos, P&L, drawdown, circuit breaker)
tem teste unitário em `tests/`, conforme exigido em [`CLAUDE.md`](../CLAUDE.md).

## Rodar um backtest de ponta a ponta

Busca klines históricos reais da Binance (endpoint público, sem necessidade de
API key) e roda o backtest completo:

```bash
python scripts/run_backtest.py --symbol BTCUSDT --interval 1m --days 7
```

O relatório é salvo em `../results/<run_name>/report.md` (+ `report.json` com os
dados brutos). Use `--testnet` para apontar para `testnet.binance.vision`.

## Rodar o treino do modelo (Fase 2)

Busca histórico real, constrói o dataset rotulado, treina com validação
walk-forward e só salva uma versão se ela vencer o baseline da Fase 1 em
**todos** os folds out-of-sample:

```bash
python scripts/train_model.py --symbol BTCUSDT --interval 1m --days 45
```

Se promovido, o artefato vai para `../results/models/<version>/` (`model.joblib`
+ `metadata.json` com dataset/hiperparâmetros/thresholds/validação). Se não for
promovido, nada é salvo — isso é esperado e correto quando o modelo não supera
o baseline de forma consistente, não uma falha do script.

## Estratégia usada nesta fase

`RsiBollingerPlaceholderStrategy` (`src/tradingbot/backtesting/strategy.py`) é uma
regra simples de mean-reversion (RSI + Bandas de Bollinger), existe **apenas para
validar a infraestrutura de ponta a ponta** — não é o modelo de ML previsto em
`specs/04-modelo-ml-e-scoring.md`, que é a próxima fase. Ela pode (e provavelmente
vai) perder dinheiro em backtest; isso não é o critério de saída desta fase. O
critério é o pipeline rodar de ponta a ponta com custos reais modelados.

## O que ainda não está implementado

- Modelo de ML **promovido** (spec 04) — infraestrutura da Fase 2 pronta, mas
  nenhuma versão passou ainda no critério de promoção (ver
  `specs/11-roadmap-e-fases.md`).
- Camada de execução real contra testnet (spec 06) — Fase 4.
- Motor de aprendizado contínuo (spec 09) — Fase 5.
- Dashboard (spec 08) — Fase 3.
- Persistência em banco relacional (spec 10 prevê PostgreSQL via addon do
  Railway, que é a plataforma de hospedagem alvo). Nesta fase, resultados de
  backtest são gravados como arquivos em `results/` — suficiente para o
  critério de saída da Fase 1 (pipeline de backtesting ponta a ponta), sem exigir
  infraestrutura de banco antes de haver dado de produção real para persistir.
