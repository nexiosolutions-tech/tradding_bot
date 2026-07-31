# Change Proposal — 2026-07-31 — Vazamento de sessão DB nos endpoints REST (QueuePool exhaustion)

**Status:** aplicada

## Evidência (origem)
- Ligada a: log real do engine em testnet, colado pelo usuário —
  `Erro inesperado processando evento: QueuePool limit of size 5 overflow 10 reached,
  connection timed out, timeout 30.00`.
- `api/app.py`, endpoints `/api/engine/events` e `/api/trades`: chamavam
  `app.state.session_factory()` diretamente, sem `with`/`.close()`. Cada requisição HTTP
  vazava uma conexão do pool, nunca devolvida.
- Com o dashboard pollando `/api/engine/events` a cada 5s (e `/api/trades` a cada 15s,
  desde a mudança de 31/07 que ligou a tabela de trades), o pool padrão do SQLAlchemy
  (5 + overflow 10 = 15) se esgota em poucos minutos de uso contínuo do dashboard —
  batendo exatamente no número do erro (`size 5 overflow 10`).
- Só não derrubou o engine por completo porque o tratamento de exceção amplo em
  `on_event`/`_handle_event` (fix de 30/07/2026) capturou o erro como aviso no log em
  vez de matar a task de processamento de eventos.

## Proposta
- Os dois endpoints passam a usar `with app.state.session_factory() as session:`,
  garantindo que a sessão (e a conexão do pool) seja devolvida ao final de cada
  requisição — mesmo padrão já usado em todo o resto do código (`orchestrator.py`,
  `run_daily_learning.py`).
- **O que não muda:** nenhuma lógica de negócio ou parâmetro de risco — é puramente
  gerenciamento de recurso (conexão de banco).

## Classificação de risco da mudança
- [ ] Nova feature (requer revisão humana antes de entrar em specs/03) — não se aplica
  exatamente; é correção de bug de infraestrutura (vazamento de conexão), sem
  classificação de risco de execução, mas registrado aqui por ter sido descoberto e
  corrigido junto com uma mudança de execução no mesmo lote.

## Validação proposta
- Teste (`test_api.py`) monitorando `Session.close` via monkeypatch, confirmando que
  ambos os endpoints fecham a sessão — o teste falharia com o código antigo (zero
  chamadas a `close`).
- Suíte completa sem regressão.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-07-31
- Justificativa: aprovação implícita ao pedir análise do log real mostrando o erro —
  corrigido imediatamente por ser bug de infraestrutura que afeta a operação contínua
  do dashboard/engine.
