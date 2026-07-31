# Change Proposal — 2026-07-30 — Falha de rede pode deixar posição real sem stop-loss

**Status:** aplicada

## Evidência (origem)
- Ligada a: auditoria técnica completa de 30/07/2026.
- `execution/orchestrator.py` só tem um `try/except` em todo o arquivo (ao redor
  de `MissingStopLossError`). Se `place_stop_loss_order` falhar depois que
  `place_market_order` já preencheu a entrada (rede, 5xx da exchange, timeout),
  a exceção sobe e mata a task que processa eventos — com a posição já real e
  aberta na exchange, sem nenhum stop-loss sequer tentado.
- Cenário relacionado, mesma raiz: `client.py` só preenche `avg_fill_price` se a
  resposta tiver `fills` não-vazio; uma resposta malformada com status
  "FILLED" mas `fills` vazio deixa `avg_fill_price=None`, e a conta do preço do
  stop (`orchestrator.py:162`) estoura `TypeError` — mesmo resultado.
- Isso é mais grave que a lacuna já documentada em specs/06 (reconciliação de
  fill perdido por crash): aquela assume que a ordem de stop foi tentada. Este
  cenário é a tentativa em si falhando.

## Proposta
- `_try_enter`: colocar `place_stop_loss_order` atrás de uma função com retry
  limitado (3 tentativas, log de cada falha no feed de atividade). Se todas as
  tentativas falharem, a posição já está aberta e desprotegida — a ação mais
  seguraé fechá-la de emergência a mercado (vender de volta) em vez de deixá-la
  aberta sem stop. Se até o fechamento de emergência falhar, registrar isso
  como alerta crítico no log de atividade (nível `warning`) — é o limite do que
  software pode fazer sozinho; a partir daí precisa de intervenção humana.
- `on_event`: envolver o corpo inteiro num `try/except Exception` amplo que
  loga e segue, em vez de deixar uma exceção matar a task de processamento de
  eventos para sempre. Isso não esconde o erro — ele vira uma linha no feed de
  atividade — só garante que o *próximo* candle ainda é processado.
- `binance_ws.py`: o parsing de cada mensagem do WebSocket ganha um
  `try/except` por mensagem (loga e ignora essa mensagem específica), em vez
  de deixar um payload inesperado matar a conexão inteira.
- **O que não muda:** a regra estrutural de que toda ordem precisa de
  stop-loss continua absoluta — esta mudança é sobre o que fazer quando a
  *tentativa* de cumprir essa regra falha, não sobre relaxar a regra.

## Classificação de risco da mudança
- [x] Parâmetro de risco/execução (requer revisão humana obrigatória)

## Validação proposta
- Teste com `FakeExchangeClient` configurado para falhar `place_stop_loss_order`
  N vezes — confirmar retry, e confirmar fechamento de emergência quando todas
  as tentativas falham.
- Teste confirmando que uma exceção genérica dentro de `on_event` não impede o
  processamento do próximo evento.
- Teste confirmando que um payload malformado no WS não derruba a conexão.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-07-30
- Justificativa: aprovação explícita em conversa, após revisão do achado da
  auditoria técnica.
