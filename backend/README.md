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

## Módulo de Ações (spec 14) — rodar localmente

**Mesmo comando de cima** (`uvicorn tradingbot.api.app:app --reload`) já serve
`/api/acoes/*` — é o mesmo processo FastAPI, `acoes/api.py` é só um
`APIRouter` a mais montado nele (nunca reusa `session_factory`/`orchestrator`
do bot). O frontend é o mesmo dashboard (`frontend/dashboard`, `npm run dev`)
— a aba "Ações" troca a sidebar inteira, ver `specs/08`.

**Persistência é local por escolha, não por omissão** — decisão registrada em
`specs/14-modulo-acoes-b3.md`, Seção 11.12. `../results/acoes.db` (SQLite,
gitignored, **mesmo padrão e mesmo diretório** de `../results/tradingbot.db`
acima — raiz do repo, irmão de `backend/`, não `backend/results/`; confirme
com `python -c "from tradingbot.acoes.persistence import DEFAULT_SQLITE_PATH;
print(DEFAULT_SQLITE_PATH)"` antes de assumir onde ele está, achado real desta
rodada: uma checagem no caminho errado quase virou um relato de "dado
perdido" que não era verdade). Sem volume persistente ou Postgres no Railway,
o deploy em produção sobe com o banco vazio (ver "Comportamento sem dado"
abaixo) — isso é esperado, não um bug.

**Comportamento sem dado**: toda rota de `/api/acoes/*` detecta banco vazio e
responde `503` com uma mensagem clara (`"módulo de Ações sem dado neste
ambiente"`), nunca um 500 mudo. `GET /api/acoes/disponivel` é a checagem
barata que o frontend usa para desabilitar a aba antes de o erro acontecer.

**Se precisar popular `../results/acoes.db` do zero** (banco corrompido,
apagado por engano, ou primeira vez numa máquina nova): não existe hoje um
script único e commitado que reconstrói a série completa 2015-2026 — a
ingestão real (COTAHIST, DFP/ITR da CVM, FCA, CDI, IPCA) foi orquestrada em
scripts ad hoc de sessão de agente (nunca promovidos a `scripts/`), que vivem
em `/tmp` e **não sobrevivem entre sessões** — achado real (2026-08-27): isso
quase foi confundido com o próprio banco de dados tendo sumido, e não tinha.
As *funções* de ingestão são todas testadas e reais
(`acoes/cotahist_ingestion.py`, `acoes/cvm_ingestion.py`,
`acoes/cnpj_ticker_map.py`, `acoes/ipca.py`, `acoes/cdi.py`) — falta só a
orquestração ano a ano (Seção 7.7 da spec 14 documenta o que ela fazia:
ingestão point-in-time por ano fiscal, `UniversoElegivel` idempotente com
guarda de retry, sanidade contra `n_transversal` conhecido). Reescrever isso
como script commitado (não ad hoc) é a forma de nunca mais depender de uma
sessão de agente para popular o banco de novo.

**Para só confirmar que a interface funciona** sem precisar do banco de
produção, a fixture real pequena já commitada em `backend/tests/fixtures/`
(ITUB4/BBAS3/PETR4, 2016) basta — reusa `test_acoes_api.py::_popular_fixture`
num banco à parte (nunca aponte para `../results/acoes.db` ao fazer isso, ou
vai sobrescrever o de produção):

```bash
cd backend
uv run python -c "
import sys; sys.path.insert(0, 'tests')
from tradingbot.acoes.persistence import get_session_factory
import test_acoes_api as t
session = get_session_factory('sqlite:////tmp/acoes-fixture.db')()
t._popular_fixture(session)
"
ACOES_DATABASE_URL=sqlite:////tmp/acoes-fixture.db uvicorn tradingbot.api.app:app --reload
```

## Deploy no Railway

Projeto usa 5 serviços no mesmo ambiente Railway: `tradding_bot` (esta API),
`learning-daily-cron` (`scripts/run_daily_learning.py`, cron diário),
`depth-capture` (`scripts/run_depth_capture.py`, contínuo), `dashboard`
(`frontend/dashboard`, ver seu próprio README) e `Postgres` (addon oficial).
Configuração feita via mutation `serviceInstanceUpdate` da API GraphQL da
Railway (não há `railway.json` no repo).

**`tradding_bot` e `learning-daily-cron` buildam a partir da raiz do repo**
com `Dockerfile.backend` (`rootDirectory=/`, `dockerfilePath=Dockerfile.backend`),
não mais via Railpack com `rootDirectory=backend` (2026-08-18, ver
`changes/2026-08-18-monorepo-root-learnings-changes.md`). Motivo: os dois
precisam ler `learnings/`/`changes/` (via `Path(__file__).resolve().parents[4]`
em `api/app.py`, `daily_report.py`, `change_proposals.py`, `tools.py`) — esses
diretórios são irmãos de `backend/` no repo, e com `rootDirectory=backend` a
Railway nunca baixa esses arquivos pro build daquele serviço (comportamento
documentado da Railway para "isolated monorepo", não um bug). O Dockerfile
resolve isso copiando `backend/`, `learnings/` e `changes/` lado a lado dentro
da imagem, replicando o layout do checkout local — o código não precisou
mudar. `depth-capture` e `dashboard` continuam em Railpack normal
(`rootDirectory=backend` / `frontend/dashboard`) — nenhum dos dois lê
`learnings/`/`changes/`.

Variáveis de serviço obrigatórias no `tradding_bot`:

| Variável | Valor |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (referência, não hardcoded) |
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | Segredos — setar manualmente, nunca via commit |
| `BINANCE_TESTNET` | `true` |
| `SYMBOL`, `INITIAL_EQUITY`, `DASHBOARD_ORIGIN` | Ver `.env.example` |

`libgomp1`/`libpq5` (necessários em runtime para `lightgbm` e
`psycopg2-binary` — sem eles o processo crasha em loop logo no primeiro
`import lightgbm` ou na primeira tentativa de `create_engine`, mesmo com build
`SUCCESS`) agora são instalados diretamente no `Dockerfile.backend`, não mais
via `RAILPACK_DEPLOY_APT_PACKAGES` — essa variável só importa nos serviços que
continuam em Railpack (`depth-capture`).

**Depois de mudar `startCommand`/config de um serviço via API, force um
deployment novo (git push) — não `redeploy`.** `redeploy` reaproveita o
deployment mais recente como ele estava congelado (imagem + comando
resolvidos no momento em que foi criado); mudanças de config feitas depois
não afetam deployments já existentes, só os próximos a serem criados. Um
`redeploy` logo após mudar `startCommand` reproduz o comando antigo
inalterado — incidente real em 2026-08-18 (ver
`changes/2026-08-18-monorepo-root-learnings-changes.md`).

**Refinamento confirmado num segundo incidente (2026-08-18, mesma data):** a regra acima
vale especificamente quando o deployment mais recente teve **sucesso**. Quando o mais
recente **falhou** (`FAILED`), `redeploy` builda do zero e pega a config atual — reproduzido
duas vezes no mesmo dia (`changes/2026-08-18-captura-aggtrade-fluxo-ordens.md`). Na prática:
`redeploy` só é confiável pra aplicar config nova logo depois de um deployment que falhou;
em cima de um deployment saudável, só um push novo força o rebuild.

Build command do `dashboard`: **`npm run build`**, não `npm ci && npm run
build` — o Railpack já roda sua própria etapa de install antes do
`buildCommand`; rodar `npm ci` de novo colide com o cache dessa etapa
(`EBUSY` em `node_modules/.vite`).

Contas free/hobby da Railway podem ter deploys enfileirados durante picos de
demanda ("Deployments paused - limited access") — isso é do lado da Railway,
não da configuração deste projeto; reprocessa sozinho quando a capacidade
libera.
