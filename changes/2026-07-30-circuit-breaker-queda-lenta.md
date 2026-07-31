# Change Proposal — 2026-07-30 — Circuit breaker não detecta queda lenta acumulada

**Status:** aplicada

## Evidência (origem)
- Ligada a: auditoria técnica completa de 30/07/2026 (não um `learnings/` diário —
  ainda não há trade real suficiente para isso; achado veio de revisão de código
  sob pedido explícito do usuário).
- `risk/manager.py:63-78` (`record_equity`) descarta pontos mais antigos que
  `circuit_breaker_window_minutes` (60min) antes de calcular o pico de referência.
  Verificado por simulação: uma perda de 1% a cada 10 minutos por 5 horas (queda
  acumulada de 26%) nunca aciona um breaker configurado para 10% em 60 minutos,
  porque nenhuma janela de 60 minutos isolada chega a mostrar 10% de queda — o
  "pico" de referência escorrega junto com a queda.
- Reconsiderando com calma: isso não é bug de lógica (o cálculo de "perdeu X% em
  qualquer janela de Y minutos" está matematicamente correto para essa definição
  literal). É uma lacuna de cobertura — um breaker de janela curta, sozinho, não
  protege contra decaimento lento ao longo de um dia inteiro de operação, que é
  um modo de falha real para um bot com um modelo ruim.

## Proposta
- Adicionar um segundo gatilho, complementar ao existente: um "pico de sessão"
  que nunca é descartado por tempo (só reseta quando um humano reconhece o
  circuit breaker). Se o drawdown desde esse pico (sem janela) atingir
  `circuit_breaker_loss_pct`, o breaker aciona — mesmo que nenhuma janela de 60
  minutos isolada mostre a queda.
- O gatilho existente (janela rolante) é mantido exatamente como está — a
  mudança é estritamente aditiva, nunca reduz a proteção atual, só fecha o
  buraco da queda lenta.
- Ao reconhecer o circuit breaker (`acknowledge_circuit_breaker`), o pico de
  sessão é reiniciado para o capital atual — sem isso, a primeira atualização
  de capital após retomar re-acionaria o breaker instantaneamente (o pico
  antigo ainda estaria lá, e o capital ainda não teria se recuperado).
- **O que não muda:** o valor de `circuit_breaker_loss_pct` (10% default) e
  `circuit_breaker_window_minutes` (60min default) — não estou alterando o
  limiar de risco em si, só fechando uma lacuna de detecção com o mesmo limiar
  já aprovado.

## Classificação de risco da mudança
- [x] Parâmetro de risco/execução (requer revisão humana obrigatória)

## Validação proposta
- Teste unitário reproduzindo a simulação de queda lenta (26% ao longo de 5h),
  confirmando que agora aciona.
- Teste unitário confirmando que reconhecer o breaker reinicia o pico de sessão
  e não re-aciona instantaneamente com o mesmo capital.
- Suíte completa de `risk/manager.py` e `execution/orchestrator.py` sem
  regressão.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-07-30
- Justificativa: aprovação explícita em conversa, após revisão do achado da
  auditoria técnica — "Pode redigir e implementar as entradas de changes/".
