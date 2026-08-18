# Change Proposal — 2026-08-18 — Build a partir da raiz do repo (learnings/changes vazios em produção)

**Status:** aplicada

## Evidência (origem)
- Usuário reportou as abas Learnings e Changes vazias na view Aprendizado em
  produção, logo depois do primeiro deploy do endpoint de backtest.
- Investigação: `tradding_bot` e `learning-daily-cron` têm
  `rootDirectory=backend` no Railway. Confirmado nos logs de build (via MCP
  `get-logs`) que o container final (`/app`) contém só o que está dentro de
  `backend/` — nenhum rastro de `learnings/`, `changes/`, `specs/` ou
  `frontend/`. A documentação da própria Railway confirma isso é
  intencional: "Root Directory... Railway will only pull down files from
  that directory when creating new deployments" (deployments/monorepo).
- `api/app.py`, `daily_report.py`, `change_proposals.py` e `tools.py`
  localizam `learnings/`/`changes/` via
  `Path(__file__).resolve().parents[4]`, assumindo esses diretórios como
  irmãos de `backend/` (verdade no checkout local). Em produção,
  `app.py` fica em `/app/src/tradingbot/api/app.py` — `parents[4]` sobe pra
  `/` (raiz do container), que não tem `learnings/`/`changes/` porque eles
  nunca entraram no build. `/results` no mesmo `/` funciona por coincidência:
  é criado em runtime (`mkdir`), não depende de conteúdo pré-existente do
  git.

## Proposta
- `Dockerfile.backend` (novo, raiz do repo) — builda `python:3.12-slim`,
  instala `libgomp1`/`libpq5` (mesmos pacotes de
  `RAILPACK_DEPLOY_APT_PACKAGES`), copia `backend/`, `learnings/` e
  `changes/` lado a lado dentro da imagem (`/app/backend`, `/app/learnings`,
  `/app/changes`) — replica exatamente o layout do checkout local, então o
  `Path(__file__).resolve().parents[4]` existente em quatro lugares do código
  não precisou mudar.
- `tradding_bot` e `learning-daily-cron`: `rootDirectory` trocado de
  `backend` pra `/` (raiz), `dockerfilePath=Dockerfile.backend` (via mutation
  GraphQL da Railway, `update-service`). Start command de cada serviço
  mantido como estava (`uvicorn ...` / `python scripts/run_daily_learning.py`)
  — o `WORKDIR` final do Dockerfile é `/app/backend`, então os caminhos
  relativos continuam batendo.
- `dashboard` e `depth-capture` **não mudaram** — nenhum dos dois lê
  `learnings/`/`changes/`, ficam em Railpack normal.
- `backend/README.md` e `specs/10` atualizados com a nova topologia de build
  e o porquê.

## Classificação de risco da mudança
- [ ] Não é mudança de parâmetro de risco/execução — é infraestrutura de
  build/deploy, não toca `execution/orchestrator.py` nem lógica de trading.
  Ainda assim tratada com cautela por ser mudança de topologia de deploy dos
  serviços de produção (ver Validação abaixo).

## Validação
- Build do `Dockerfile.backend` rodado localmente (`docker build`) até o
  fim, sem erros — instala as mesmas 60+ dependências que o Railpack já
  instala hoje, `pip install -e backend/` funciona a partir da raiz.
- Container rodado localmente (`docker run`) com `DATABASE_URL` sqlite
  temporário: `GET /api/health` → 200; `GET /api/learnings` → lista o
  arquivo real (`2026-08-11.md`); `GET /api/changes` → lista as 33 propostas
  reais do repo (incluindo esta). Confirma que o caminho `parents[4]`
  resolve certo dentro do container, sem qualquer mudança de código.
- Config aplicada via `update-service` (Railway MCP) antes do commit/push —
  a mudança só entra em vigor no próximo deploy, que é o deste commit.
- Deploy de produção acompanhado após o push (ver histórico da sessão) —
  `tradding_bot` e `learning-daily-cron` com deploy `SUCCESS`, `/api/learnings`
  e `/api/changes` conferidos contra a URL pública de produção.

## Incidente durante o rollout (mesmo dia)

O primeiro deploy com `Dockerfile.backend` (build `SUCCESS`) deixou o
`tradding_bot` em crash loop: `Error: Invalid value for '--port': '$PORT' is
not a valid integer.` — o `startCommand` configurado
(`uvicorn ... --port $PORT`) não teve `$PORT` expandido, ao contrário do
comportamento sob Railpack. View "Live" ficou vazia em produção por ~12
minutos (sem posição aberta arriscada nesse intervalo — o processo nunca
chegou a inicializar o `Orchestrator`, então não tomou nenhuma decisão, só
ficou fora do ar).

Correção: `startCommand` do `tradding_bot` mudado pra
`sh -c "uvicorn tradingbot.api.app:app --host 0.0.0.0 --port $PORT"`
(via `update-service`). **Lição operacional importante:** `redeploy`
reaproveita o deployment mais recente *como estava congelado* (imagem +
comando resolvido no momento em que foi criado) — mudar a config do serviço
via `update-service` não afeta deployments já existentes, só os próximos.
Um `redeploy` logo após o `update-service` reproduziu o erro antigo
inalterado. A correção só entrou em vigor com um deployment genuinamente
novo (disparado por outro `git push`, que também trouxe o `CMD` do
`Dockerfile.backend` em shell form como defesa em profundidade). Daqui pra
frente: depois de um `update-service` que muda `startCommand`, confirmar via
`get-service-config` que a mudança está salva, mas **sempre forçar um
deployment novo** (push, não `redeploy`) pra ter certeza que ela está em
vigor.

Confirmado recuperado com dado real: `/api/health` → 200, `/api/engine/state`
mostrando o `Orchestrator` avaliando candles e tendo fechado um trade
normalmente, `/api/learnings`/`/api/changes` com conteúdo real (34 changes).

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-18
- Justificativa: "Implemente e suba, só diagnóstico não resolve o problema" —
  em resposta direta ao diagnóstico das abas Learnings/Changes vazias.
