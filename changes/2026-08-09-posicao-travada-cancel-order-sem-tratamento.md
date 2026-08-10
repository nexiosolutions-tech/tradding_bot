# Change Proposal — 2026-08-09 — Posição travada 7 dias: cancel_order sem tratamento trava a saída para sempre

**Status:** aplicada

## Evidência (origem)
- Reportado pelo usuário: log real do dashboard mostrando
  `Erro inesperado processando evento: APIError(code=-2011): Unknown order sent.`
  repetindo a cada ~1 minuto, junto com `"BTCUSDT @ ... — monitorando posição
  aberta"` — desde o 3º dia de uma operação de 7 dias em testnet.
- Confirmado via `GET /api/engine/state` em produção: a posição reportada
  (`entry_price=62772.01`, `entry_ts` correspondente a 2026-08-03 13:12 UTC)
  seguia aberta 7 dias depois (2026-08-10), com o mesmo erro se repetindo a
  cada candle. **Nenhum trade novo foi possível durante todo esse período**
  — o motor só entra em posição nova quando está flat.
- Logs do Railway daquela janela específica (03/08) já tinham expirado por
  retenção quando a investigação começou (7 dias depois) — a causa raiz foi
  determinada por leitura de código e confirmada consultando a testnet
  diretamente (`get_order` real via `python-binance`, credenciais do
  serviço via `railway run`): tanto a ordem de entrada quanto a de
  stop-loss retornam `APIError(code=-2013): Order does not exist`, e o
  saldo da conta está em `1.00000000 BTC` / `10000.00000000 USDT` — os
  valores padrão de uma conta nova. **A causa raiz de origem é um reset de
  dado da testnet da Binance** (comportamento documentado/periódico de
  `testnet.binance.vision`, fora do nosso controle) — o bug real, que é
  nosso, é a ausência total de resiliência do código a essa classe de
  evento.

## Causa raiz
- `execution/orchestrator.py::_check_exit` (saída por sinal): ao decidir
  sair, chamava `await self.exchange.cancel_order(...)` **sem nenhum
  tratamento de exceção**, antes de vender a mercado. Se essa chamada
  falhar por qualquer motivo — e falha com certeza se a exchange não
  reconhece mais aquela ordem — a exceção propaga por `_handle_event` até
  o handler amplo de `on_event`, que só loga e segue para o próximo
  candle. `self._position` nunca é limpo (só acontece dentro de
  `_finalize_exit`, nunca alcançado). Resultado: todo candle seguinte
  repete exatamente a mesma tentativa e a mesma falha, para sempre — nem a
  checagem de preenchimento do stop-loss nem a saída por sinal conseguem
  completar.
- Agravante: `execution/client.py::get_order_status` tinha
  `except Exception: return None` — qualquer falha (rede, rate limit, ou
  ordem de fato inexistente) virava `None` igualmente, misturando "esta
  ordem definitivamente não existe" com "não consegui checar agora". Isso
  tira do chamador a informação que precisaria para decidir com segurança
  o que fazer.
- Binance usa **dois códigos diferentes** para "não há registro dessa
  ordem", dependendo do endpoint: `-2011` ("Unknown order sent") do
  endpoint de cancelamento, `-2013` ("Order does not exist") do endpoint de
  consulta — que é o que `get_order_status` realmente chama. A primeira
  versão deste fix só tratava `-2011`; a consulta direta à testnet real
  (acima) mostrou que o código de fato retornado pela consulta é `-2013` —
  corrigido para tratar os dois.

## Proposta
- `execution/client.py::get_order_status`: só os códigos `-2011`/`-2013`
  viram `None` (resposta legítima de "não encontrada"); qualquer outra
  `BinanceAPIException` (ou falha de rede) propaga — o handler amplo de
  `on_event` já loga e tenta de novo no próximo candle, mais seguro que
  interpretar uma falha transitória como "a ordem não existe".
- `execution/orchestrator.py::_check_exit`: o `cancel_order` antes da venda
  a mercado agora tem tratamento — se falhar, re-checa o status da ordem:
  - Se **preenchida**: a posição já fechou via stop-loss; finaliza como
    `stop_loss` e **não** tenta vender de novo (evita venda duplicada).
  - Se **não preenchida** (ordem sumiu por outro motivo): loga aviso e
    prossegue com a venda a mercado mesmo assim — a estratégia já decidiu
    sair e não há stop funcional pra confiar de qualquer forma; travar a
    saída indefinidamente é estritamente pior que fechar a posição sem uma
    ordem de stop pra cancelar.
- **O que não muda**: nenhum parâmetro de risco/sizing/stop-loss. É
  tratamento de erro na camada de execução — mesma classificação de
  `changes/2026-07-30-tratamento-excecao-execucao.md`.

## Classificação de risco da mudança
- [ ] Não é mudança de parâmetro de risco/execução nem de arquitetura —
  correção de bug crítico de resiliência na camada de execução, mesma
  classe dos incidentes de produção anteriores (PRICE_FILTER, vazamento de
  sessão DB, overflow de INTEGER). Registrado aqui pela severidade (posição
  presa por 7 dias, `CLAUDE.md` regra 2 efetivamente violada durante esse
  período — a proteção estrutural existia no código de entrada mas não
  sobrevivia a essa falha específica no caminho de saída).

## Validação proposta
- Dois testes de regressão em `test_orchestrator.py`, usando
  `FakeExchangeClient.fail_cancel_times` (novo hook de teste):
  1. `cancel_order` falha porque o stop **já preenchido** → finaliza como
     `stop_loss`, sem venda a mercado redundante (`place_market_order`
     chamado só 1x, na entrada).
  2. `cancel_order` falha e o stop **não foi preenchido** (ordem
     removida do fake, simulando sumiço) → reproduz o incidente real e
     confirma que agora a posição fecha (`state == ANALISANDO`,
     `exit_reason == "signal_exit"`) em vez de ficar presa.
- Testes novos em `test_execution_client.py` para `get_order_status`,
  parametrizados em `-2011` e `-2013`: ambos viram `None`; qualquer outro
  código propaga.
- Suíte completa: 196 passed, 1 deselected (rede) — sem regressão.
- **Ressalva sobre o dado gerado quando a posição travada for finalmente
  fechada**: como a testnet resetou o saldo da conta, o trade que vai
  fechar essa posição específica (assim que `should_exit` disparar, ou
  imediatamente se já estiver disparando) vai calcular P&L real
  (`preço_de_saída_atual - preço_de_entrada_de_uma_semana_atrás`), mas sem
  corresponder a um holding contínuo de verdade — é aritmeticamente
  correto, mas não é um dado econômico representativo. Recomendado tratar
  esse trade específico como outlier/artefato na análise da semana, não
  como sinal real da estratégia.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-09
- Justificativa: bug crítico real de produção, reportado pelo usuário com
  evidência de log. Corrigido com a mesma urgência dos incidentes anteriores
  dessa classe (PRICE_FILTER, vazamento de sessão DB, overflow de INTEGER).
  **Pendente**: aplicar em produção exige push + redeploy, o que conflita
  com o pedido explícito do usuário de não interromper o engine durante a
  semana de coleta de dado — decisão de quando fazer o deploy fica com o
  usuário, não tomada unilateralmente aqui.
