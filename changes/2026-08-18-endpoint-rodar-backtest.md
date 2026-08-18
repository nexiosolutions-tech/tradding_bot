# Change Proposal — 2026-08-18 — Endpoint para rodar backtest a partir do dashboard

**Status:** aplicada

## Evidência (origem)
- Pedido direto do usuário: gerar o primeiro relatório de backtest e subi-lo
  para produção, pra aparecer na view Performance real.
- Ao investigar, `results/` está no `.gitignore` e o serviço `tradding_bot`
  no Railway não tem volume persistente — é armazenamento local do
  container. Rodar `scripts/run_backtest.py` na máquina do operador nunca
  alimentaria a view Performance em produção: o relatório fica só no disco
  local, o deploy leva código, não `results/`. Pra popular a view de
  verdade, o backtest precisa rodar *dentro* do processo que serve a API.

## Proposta
- `backtesting/runner.py::run_and_save_backtest` — extrai a lógica de
  buscar klines da Binance + rodar `BacktestEngine` + `save_report` que
  antes vivia só em `scripts/run_backtest.py`, agora reusável.
  `scripts/run_backtest.py` passa a chamar essa função (comportamento de
  CLI idêntico, sem duplicação de lógica).
- `POST /api/backtests/run` (novo) — recebe `symbol`/`interval`/`days`,
  chama `run_and_save_backtest` contra `RESULTS_DIR` do próprio processo,
  retorna o resumo do run (mesmo formato de `GET /api/backtests`).
  Protegido pela mesma `DASHBOARD_API_KEY` opcional já usada em
  pause/resume/acknowledge_circuit_breaker (mesmo padrão de
  `changes/2026-07-30-autenticacao-endpoints-controle.md`). `days` limitado
  a 1–90 pra não permitir um fetch enorme por engano. Roda como handler
  síncrono (`def`, não `async def`) — o FastAPI já executa esses em thread
  separada, então a busca na Binance não trava o loop de eventos do
  Orchestrator ao vivo.
- Frontend: `PerformanceView` ganha um botão "Rodar backtest" (estado vazio
  e toolbar da lista) que chama o endpoint, recarrega a lista e seleciona o
  run novo.
- **O que não muda:** nenhum contato com `execution/orchestrator.py`, banco
  de trades reais, ou lógica de risco — é uma instância isolada de
  `BacktestEngine` rodando contra dado histórico público da Binance, igual
  ao script CLI que já existia.

## Classificação de risco da mudança
- [ ] Não é mudança de parâmetro de risco/execução — não toca a camada de
  execução (`06-camada-de-execucao.md`), não abre nem fecha posição real,
  não altera sizing. É uma ferramenta de geração de relatório, protegida
  pela mesma chave de API dos outros comandos por padrão de consistência,
  não porque afete capital.

## Validação
- 273 testes passando (6 novos: `runner.py` isolado com fetch mockado —
  sucesso e "sem klines retornadas" — e o endpoint via `TestClient`: sucesso
  com resumo correto, 502 sem klines, 400 fora do range de `days`, 401 sem
  API key quando configurada).
- Testado de ponta a ponta contra a API real rodando localmente (não
  mockado): `POST /api/backtests/run` com `days=1` buscou klines reais da
  Binance, gerou o relatório, e `GET /api/backtests` refletiu o run na
  sequência.
- Frontend: `tsc -b && vite build` sem erros.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-18
- Justificativa: resposta direta a "quer que eu investigue essa segunda
  opção?" / "Sim, por favor" — depois do deploy anterior (correção de taxa,
  perfis de risco, feature cross-asset) mostrar que `results/` não persiste
  em produção e não alimenta a view Performance sozinho.
