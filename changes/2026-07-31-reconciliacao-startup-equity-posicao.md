# Change Proposal — 2026-07-31 — Restart esquece posição aberta e reseta equity

**Status:** aplicada

## Evidência (origem)
- Ligada a: pergunta do usuário sobre se valeria rodar o bot continuamente
  no Railway (apontado para testnet) em vez de localmente, para evitar
  "perder o histórico diário de aprendizado" a cada restart durante o
  desenvolvimento ativo.
- Investigação revelou dois problemas reais em `bootstrap.build_orchestrator`/
  `Orchestrator.__init__`, **independentes de onde o processo roda**:
  1. `equity` sempre inicializa com `INITIAL_EQUITY` (env var, default 1000)
     — nunca reconstruído a partir do P&L real já persistido em
     `TradeRecord`. Um restart qualquer apaga a métrica de volta ao valor
     de configuração, mesmo que o bot tenha operado dias e acumulado P&L
     real.
  2. Nenhuma reconciliação de posição aberta contra a exchange no startup —
     `self._position` sempre começa `None`. Se o processo reiniciar com uma
     posição real aberta, o sistema perde o rastro dela: pode abrir uma
     entrada nova em cima de exposição já existente, e nunca vai detectar
     nem registrar o fechamento da posição antiga.
- Confirmado que o Railway já está configurado para redeploy automático a
  cada push na `main` (deployment mais recente do serviço `tradding_bot`
  bate exatamente com o commit do sweep de hoje) — ou seja, mover para
  Railway não reduziria a frequência de restarts durante iteração ativa,
  só mudaria onde o mesmo problema acontece. A causa raiz não é "onde
  rodar", é a ausência de recuperação de estado no boot.

## Proposta
- `bootstrap.build_orchestrator`: soma `repository.sum_realized_pnl(session, symbol)`
  ao `INITIAL_EQUITY` de configuração antes de construir o `Orchestrator`.
- Novo `Orchestrator.reconcile_position_on_startup()` (async, chamado uma
  vez logo após a construção, antes do stream de eventos começar — em
  `api/app.py` e `scripts/run_live.py`):
  - Busca a entrada preenchida mais recente sem `TradeRecord` correspondente
    (`repository.latest_unclosed_entry`) e o stop-loss persistido depois
    dela (`repository.latest_stop_loss_after`).
  - Sem entrada pendente: segue flat, nada muda.
  - Entrada pendente sem stop-loss registrado, ou com preço de stop não
    recuperável do `raw_response`: alerta crítico + pausa — mesmo princípio
    de `_emergency_close_unprotected` (30/07), nunca adivinha.
  - Stop já disparado na exchange enquanto o processo estava fora do ar
    (checado via `get_order_status`, a exchange como fonte de verdade):
    finaliza o trade agora, reaproveitando `_finalize_exit`.
  - Stop ainda ativo: reconstrói `OpenPositionLive` e retoma monitoramento
    (transição para `POSICAO_ABERTA`).
- Novos helpers em `persistence/repository.py`: `sum_realized_pnl`,
  `latest_unclosed_entry`, `latest_stop_loss_after`.
- **O que não muda:** nenhum parâmetro de risco (`stop_loss_pct`,
  `circuit_breaker_*`, sizing) é alterado — é puramente recuperação de
  estado no boot. Não cobre o caso estreito de crash exatamente entre a
  exchange confirmar o fill e o `OrderRecord` da entrada ser persistido
  (lacuna já documentada, permanece em aberto).

## Classificação de risco da mudança
- [x] Parâmetro de risco/execução (requer revisão humana obrigatória) —
  afeta diretamente como o sistema trata capital e posições reais após
  qualquer interrupção de processo.

## Validação proposta
- Testes unitários (`test_bootstrap.py`, `test_orchestrator.py`): equity
  reconstruído a partir de trades persistidos; reconciliação fica flat sem
  entrada pendente; retoma monitoramento de posição ainda aberta; finaliza
  trade cujo stop já disparou fora do ar; pausa com alerta crítico quando
  não há stop-loss registrado para uma entrada pendente.
- Suíte completa sem regressão.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-07-31
- Justificativa: aprovação explícita em conversa ("Sim, vamos corrigir esse
  gap"), após pergunta sobre infraestrutura Railway vs. local revelar o
  problema estrutural real.
