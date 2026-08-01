# Change Proposal — 2026-08-01 — Timestamps em ms estouravam INTEGER (Postgres) em produção

**Status:** aplicada

## Evidência (origem)
- Ligada a: primeira tentativa real de religar o engine em produção (Railway),
  pedida pelo usuário após confirmar que o processo estava rodando pausado desde
  o deploy (`self.state = EngineState.PAUSADO` — boots paused por design, exige
  `POST /api/engine/resume` humano).
- `POST /api/engine/resume` retornou 500. Log real do deploy:
  `sqlalchemy.exc.DataError: (psycopg2.errors.NumericValueOutOfRange) integer out
  of range` ao inserir em `engine_events` — `ts=1785599289475` (epoch em
  milissegundos, ~1.78e12) estourando o limite de `INTEGER` de 32 bits do Postgres
  (~2.1e9).
- `persistence/models.py` usava `Integer` para todo timestamp em milissegundos
  (`now_fn=lambda: int(time.time() * 1000)`, `bootstrap.py`). Nunca apareceu em
  desenvolvimento local porque SQLite não tem largura fixa de `INTEGER` (aceita
  qualquer inteiro Python) — só surgiu contra Postgres real, e só agora porque
  essa foi a primeira transição de estado (`engine_events`) realmente persistida
  em produção desde o deploy.
- Mesma classe de bug presente em mais 4 colunas que nunca tinham sido exercitadas
  com dado real ainda: `trades.entry_ts`, `trades.exit_ts`,
  `circuit_breaker_events.triggered_at`, `circuit_breaker_events.acknowledged_at`
  — o primeiro trade fechado ou o primeiro circuit breaker real teriam quebrado
  do mesmo jeito.

## Proposta
- `persistence/models.py`: as 5 colunas trocam de `Integer` para `BigInteger`.
- Sem migração automática no código (projeto não usa Alembic, só
  `Base.metadata.create_all()`, que não altera tabelas já existentes) — as 3
  tabelas afetadas (`engine_events`, `trades`, `circuit_breaker_events`) estavam
  vazias (0 linhas, confirmado via `psql` antes da mudança), então a correção foi
  aplicada diretamente em produção com `ALTER TABLE ... ALTER COLUMN ... TYPE
  BIGINT` (widening, sem perda de dado) via `railway run` + `psql` contra a
  `DATABASE_PUBLIC_URL` do addon Postgres.
- **O que não muda**: nenhuma lógica de negócio, parâmetro de risco ou schema de
  outras colunas — é puramente correção de tipo de dado para um valor que já era
  sempre epoch-ms em todo o resto do código.

## Classificação de risco da mudança
- [ ] Não é mudança de parâmetro de risco/execução nem de arquitetura — correção
  de bug de infraestrutura (tipo de coluna incompatível com o dado real que
  sempre foi gravado), descoberta e corrigida durante uma ação operacional
  (religar o engine).

## Validação proposta
- Suíte completa sem regressão (nenhum teste assume `Integer` vs `BigInteger`
  diretamente — SQLite não distingue).
- Validação real: `POST /api/engine/resume` em produção, que falhava com 500
  antes da correção, retornou 200 (`{"state": "ANALISANDO"}`) depois.
- Verificado via `psql \d` que as 5 colunas nas 3 tabelas de produção agora são
  `bigint`.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-01
- Justificativa: bug bloqueava diretamente a ação pedida ("ligue o engine
  agora") e teria bloqueado o primeiro trade real ou circuit breaker de
  qualquer forma — corrigido como parte da mesma operação, mesmo padrão dos
  bugs de produção anteriores (PRICE_FILTER, vazamento de sessão DB) descobertos
  via log real e corrigidos no mesmo lote.
