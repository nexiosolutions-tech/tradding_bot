# Dashboard — Fase 3

Implementação de [`specs/08-dashboard-e-visualizacao.md`](../../specs/08-dashboard-e-visualizacao.md):
4 views (Live, Performance, Modelo, Aprendizado) consumindo a API do backend
(`backend/src/tradingbot/api/app.py`).

## Setup

```bash
cd frontend/dashboard
npm install
npm run dev
```

Por padrão aponta para `http://localhost:8000` (ver `.env.development`). Suba o
backend antes (`cd ../../backend && source .venv/bin/activate && uvicorn tradingbot.api.app:app --reload`).

## Views

- **Live** — estado do engine (máquina de estados de `specs/01`), timers de
  uptime e de operação aberta, posição atual, play/pause/reconhecer circuit
  breaker, log de eventos. Mostra "engine não configurado" até que
  `BINANCE_API_KEY`/`BINANCE_API_SECRET` existam no backend — as demais views
  não dependem disso.
- **Performance** — lista de backtests (`results/*/report.json`), curva de
  capital (TradingView Lightweight Charts) e P&L por horário (Recharts).
- **Modelo** — versões de modelo promovidas (`results/models/*/metadata.json`),
  profit factor por fold walk-forward, features usadas.
- **Aprendizado** — navega `learnings/*.md` e `changes/*.md` (spec 09).

## Decisões de UI

Segue as skills instaladas conforme `CLAUDE.md`: elementos de alta frequência
(o timer, o preço) não animam; transições de interação ficam sob 150–200ms;
paleta escura restrita (verde/vermelho só para P&L, âmbar só para
pausado/circuit breaker) para não competir com os dados.

## Build de produção

```bash
npm run build
```

Gera `dist/` — um único serviço estático que pode ser hospedado no Railway
junto ou separado do backend (ver `specs/10-stack-tecnica-e-dependencias.md`,
seção Hospedagem).
