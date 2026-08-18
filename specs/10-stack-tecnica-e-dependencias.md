# 10 — Stack Técnica e Estrutura de Pastas

## Stack

### Backend / dados / ML
- **Python** (versão a fixar no ambiente de desenvolvimento) para ingestão,
  features, modelo e execução.
- **`python-binance`** e/ou **`ccxt`** para integração com a Binance (REST +
  WebSocket). `ccxt` mantém a porta aberta para múltiplas exchanges no futuro
  sem custo de reescrita.
- **`asyncio` + `websockets`** para o caminho crítico de ingestão em tempo
  real (evitar wrappers pesados nesse caminho).
- **`collections.deque`** / estruturas rolling em memória para o motor de
  features no MVP.
- **`ta-lib`** (ou implementação incremental própria) para indicadores
  técnicos.
- **LightGBM / XGBoost** como modelo baseline.
- **`pandas`/`numpy`** para prototipagem e backtesting offline.
- **`shap`** (2026-08-01) — importância de features via `TreeExplainer`, usado por
  `model/importance.py` e pelo script de diagnóstico `scripts/feature_importance.py`
  (spec 04/11). Só roda offline (treino/diagnóstico), nunca no caminho de execução.
- **`anthropic`** (2026-08-01) — SDK oficial, usado por
  `learning_engine/agentic_loop.py` (`AnthropicReasoningClient`) para o loop agêntico
  de aprendizado contínuo (spec 09). Requer `ANTHROPIC_API_KEY`; roda só no ciclo de
  investigação (`scripts/run_agentic_learning.py`), nunca no caminho de execução —
  mesma separação estrutural de `execution/` que já vale para o resto do projeto.

### Persistência
- **SQLAlchemy** (`backend/src/tradingbot/persistence/`) sobre **SQLite** em
  desenvolvimento local (`results/tradingbot.db`, gitignored) e **PostgreSQL**
  em produção via addon do Railway — troca de banco é só a variável
  `DATABASE_URL`, nenhum model/query muda. Schema (Fase 4): `orders`,
  `trades`, `circuit_breaker_events`, `engine_events` — ver
  `persistence/models.py` para os campos exatos. **Todo timestamp é epoch em
  milissegundos e usa `BigInteger`, nunca `Integer`** — um `INTEGER` de 32
  bits do Postgres estoura com epoch-ms (~1.7e12 > ~2.1e9), bug real
  encontrado em produção na primeira escrita real em `engine_events`
  (2026-08-01, `changes/2026-08-01-timestamps-integer-overflow-postgres.md`);
  SQLite não pega esse erro em dev local porque seu `INTEGER` não tem largura
  fixa. Projeto não usa Alembic — mudança de schema em coluna já existente em
  produção precisa de `ALTER TABLE` manual, `Base.metadata.create_all()` só
  cria tabelas novas.
- Artefatos de modelo (spec 04) continuam versionados como arquivos em
  `results/models/<version>/` (`model.joblib` + `metadata.json`), não no
  banco — são grandes, binários, e já têm seu próprio versionamento por
  pasta.
- Relatórios de backtest (spec 07) continuam em `results/<run>/report.{json,md}`.

### Hospedagem
- **Railway** é a plataforma de deploy alvo. Decisão tomada na Fase 3: **um
  único serviço** roda a API (FastAPI) e o `Orchestrator` (ingestão +
  execução) juntos, no mesmo processo — `Orchestrator` inicia como task de
  background no lifespan do FastAPI (`backend/src/tradingbot/api/app.py`).
  Simplifica o deploy inicial; nada impede separar em dois serviços depois
  (um "web", um "worker" rodando `scripts/run_live.py`) se um redeploy do
  dashboard interrompendo a operação ao vivo se mostrar um problema real — aí
  vira uma proposta em `changes/`, não uma decisão especulativa de agora.
- **Status: provisionado.** Projeto Railway com serviços: `tradding_bot`
  (esta API + Orchestrator), `learning-daily-cron` (cron diário),
  `depth-capture` (captura contínua de order book), `dashboard`
  (`rootDirectory=frontend/dashboard`), `Postgres` (addon oficial,
  `DATABASE_URL` referenciado no backend via `${{Postgres.DATABASE_URL}}`).
- **`tradding_bot` e `learning-daily-cron` buildam via `Dockerfile.backend`
  a partir da raiz do repo (2026-08-18), não `rootDirectory=backend` +
  Railpack.** Os dois precisam ler `learnings/`/`changes/` em runtime
  (`Path(__file__).resolve().parents[4]`, assume esses diretórios como irmãos
  de `backend/`) — com `rootDirectory=backend`, a Railway nunca inclui esses
  diretórios no build daquele serviço (isolamento de monorepo documentado da
  própria Railway, não um bug de configuração). O Dockerfile copia
  `backend/`, `learnings/` e `changes/` lado a lado na imagem, replicando o
  layout do checkout local sem mudar o código de resolução de caminho. Ver
  `changes/2026-08-18-monorepo-root-learnings-changes.md` e
  `backend/README.md#deploy-no-railway`. `depth-capture` e `dashboard`
  continuam em Railpack normal — nenhum dos dois lê `learnings/`/`changes/`.
- Variáveis de ambiente necessárias em produção: `BINANCE_API_KEY`,
  `BINANCE_API_SECRET`, `BINANCE_TESTNET` (default `true` — só pode ser
  `false` com decisão humana explícita, `bootstrap.py` bloqueia isso por
  padrão), `SYMBOL`, `INITIAL_EQUITY`, `DATABASE_URL`, `DASHBOARD_ORIGIN`
  (CORS do frontend), e **`RAILPACK_DEPLOY_APT_PACKAGES=libgomp1 libpq5`** —
  sem essas duas, o processo crasha em loop em runtime (`import lightgbm` e
  `psycopg2`/Postgres, respectivamente — dois incidentes reais, não
  hipotéticos; detalhe em `backend/README.md#deploy-no-railway`).

### Frontend / Dashboard
- **React + Vite + TypeScript** (`frontend/dashboard/`), **TradingView
  Lightweight Charts** (curva de capital) + **Recharts** (gráficos de barra).
- **WebSocket** (`/ws/engine`) para updates ao vivo, com fallback automático
  para polling REST se o socket cair; REST para consultas históricas.
- Skills de UI de terceiros instaladas conforme [`CLAUDE.md`](../CLAUDE.md)
  (`npx -y skills add ... --agent claude-code`, confirmado funcionando via
  Claude Code CLI direto neste projeto).

### Ambientes de execução
- **Testnet Binance** (`testnet.binance.vision`) — obrigatório antes de
  qualquer mudança em produção (`06-camada-de-execucao.md`).
- Ambiente local de desenvolvimento com variáveis de ambiente separadas por
  ambiente (testnet/mainnet) — nunca a mesma credencial/config usada nos dois.
  Em produção (Railway), essa separação é feita por environment do próprio
  Railway (ex.: `staging`/`production`), cada um com seu próprio conjunto de
  variáveis.

## Estrutura de pastas

Estrutura real a partir da Fase 5 (atualizada nesta spec conforme `CLAUDE.md`
regra 4 a cada fase que adicionou módulos novos):

```
/
├── CLAUDE.md
├── README.md
├── specs/                    # especificações (este diretório)
├── learnings/                 # relatórios diários do motor de aprendizado
├── changes/                   # backlog de mudanças propostas, pendentes de revisão
├── backend/
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── README.md              # setup, como rodar testes/scripts
│   ├── src/tradingbot/
│   │   ├── ingestion/         # spec 02
│   │   ├── features/          # spec 03
│   │   ├── model/              # spec 04
│   │   ├── risk/                # spec 05 — usado por backtesting E pelo orchestrator
│   │   ├── backtesting/          # spec 07
│   │   ├── execution/             # spec 06 — client.py, orchestrator.py, bootstrap.py
│   │   ├── persistence/            # spec 10 — SQLAlchemy models/db/repository
│   │   ├── api/                     # spec 08 — FastAPI app (serve o dashboard)
│   │   └── learning_engine/          # spec 09 — daily_report.py, change_proposals.py
│   ├── scripts/                       # run_backtest.py, train_model.py, run_live.py,
│   │                                    # run_daily_learning.py
│   └── tests/                          # um teste por função que envolve dinheiro (CLAUDE.md)
├── frontend/
│   └── dashboard/                       # spec 08 — React + Vite + TypeScript
└── results/                              # artefatos gerados (gitignored):
    ├── tradingbot.db                      # SQLite local (Postgres em produção)
    ├── <run>/report.{json,md}              # relatórios de backtest
    └── models/<version>/                    # modelos versionados (spec 04)
```

## Gestão de segredos

- Credenciais de API (testnet e mainnet) nunca commitadas — via variáveis de
  ambiente/arquivo de secrets ignorado pelo controle de versão.
- Credenciais de mainnet só configuradas no ambiente que efetivamente vai
  operar com capital real, após todos os gates de `06-camada-de-execucao.md`.

## Nota sobre versões

Este documento intencionalmente não fixa números de versão exatos de cada
biblioteca — isso é decidido e registrado no `requirements.txt`/`package.json`
no momento da implementação (fase 1 do roadmap), para usar as versões estáveis
disponíveis naquele momento.
