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

## Configurar as chaves da testnet

1. Acesse [testnet.binance.vision](https://testnet.binance.vision) e faça login
   com sua conta do GitHub (é a única forma de login lá).
2. Clique em "Generate HMAC_SHA256 Key", dê um nome qualquer e gere.
3. O **Secret Key só é mostrado uma vez** — copie API Key e Secret Key
   imediatamente.
4. Copie `backend/.env.example` para `backend/.env` (se ainda não tiver feito)
   e cole as duas chaves em `BINANCE_API_KEY`/`BINANCE_API_SECRET`. O arquivo
   `.env` já está no `.gitignore` — nunca vai pro commit.

`bootstrap.py` carrega `backend/.env` automaticamente (via `python-dotenv`)
sempre que a API ou `run_live.py` sobem — não precisa exportar nada na mão.

## Subir a API + dashboard localmente

```bash
uvicorn tradingbot.api.app:app --reload
```

Sem `BINANCE_API_KEY`/`BINANCE_API_SECRET` configuradas, a API sobe normalmente
e todas as views que dependem de `results/`/banco funcionam — só a view "Live"
mostra "engine não configurado". Com as chaves no `.env`, a ingestão conecta
de verdade no testnet e a view "Live" mostra `configured: true`.

O engine sempre inicia **pausado**; ligar a execução é uma ação explícita no
dashboard (Play), nunca automática ao subir o processo. `BINANCE_TESTNET=false`
exigiria mainnet e é bloqueado por padrão (`CLAUDE.md` regra 1/6).

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

## Deploy no Railway

Projeto usa 3 serviços no mesmo ambiente Railway: `tradding_bot` (esta API,
`rootDirectory=backend`), `dashboard` (`frontend/dashboard`, ver seu próprio
README) e `Postgres` (addon oficial). Configuração feita via mutation
`serviceInstanceUpdate` da API GraphQL da Railway (não há `railway.json` no
repo) — variáveis de serviço obrigatórias no `tradding_bot`:

| Variável | Valor |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (referência, não hardcoded) |
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | Segredos — setar manualmente, nunca via commit |
| `BINANCE_TESTNET` | `true` |
| `SYMBOL`, `INITIAL_EQUITY`, `DASHBOARD_ORIGIN` | Ver `.env.example` |
| **`RAILPACK_DEPLOY_APT_PACKAGES`** | **`libgomp1 libpq5`** |

Essa é a que trava sem aviso óbvio, e trava em duas partes: `lightgbm` precisa
de `libgomp.so.1` (runtime OpenMP) e `psycopg2-binary` precisa de `libpq.so.5`
(cliente Postgres) — ambos em tempo de **execução**, não só de build. A
imagem padrão do Railpack não inclui nenhuma das duas, e sem essa variável o
processo crasha em loop logo no primeiro `import lightgbm` ou na primeira
tentativa de `create_engine` com uma URL Postgres (o build em si aparece como
`SUCCESS`, só o container morre ao subir — dois incidentes reais, corrigidos
um de cada vez). `RAILPACK_DEPLOY_APT_PACKAGES` (não
`RAILPACK_BUILD_APT_PACKAGES`) instala no estágio final da imagem, que é o
que roda em produção.

Build command do `dashboard`: **`npm run build`**, não `npm ci && npm run
build` — o Railpack já roda sua própria etapa de install antes do
`buildCommand`; rodar `npm ci` de novo colide com o cache dessa etapa
(`EBUSY` em `node_modules/.vite`).

Contas free/hobby da Railway podem ter deploys enfileirados durante picos de
demanda ("Deployments paused - limited access") — isso é do lado da Railway,
não da configuração deste projeto; reprocessa sozinho quando a capacidade
libera.
