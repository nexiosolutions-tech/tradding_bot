# Change Proposal — 2026-08-10 — Stop-loss preencheu de verdade, mas avg_fill_price ficava None e travava o fechamento

**Status:** aplicada

## Evidência (origem)
- Reportado pelo usuário: print do dashboard mostrando
  `Erro inesperado processando evento: unsupported operand type(s) for -:
  'NoneType' and 'float'` repetindo a cada candle, com `"BTCUSDT @ ... —
  monitorando posição aberta"` — mesmo padrão estrutural do incidente de
  `changes/2026-08-09-posicao-travada-cancel-order-sem-tratamento.md`, erro
  diferente.
- Consultado o stop-loss real da posição travada (`get_order` direto
  contra testnet.binance.vision, credenciais do serviço via `railway run`):
  a ordem **preencheu de verdade** —
  `status: "FILLED"`, `executedQty: "0.00308000"`,
  `cummulativeQuoteQty: "196.98404880"` — o preço tinha dipado abaixo do
  stop (`stopPrice: 64019.88`) e recuperado, um fill real e correto do
  ponto de vista da exchange. **A proteção estrutural funcionou.**

## Causa raiz
- `execution/client.py::_to_order_result` calculava `avg_fill_price` só a
  partir do campo `fills` da resposta bruta. `GET /api/v3/order` (o que
  `get_order_status` chama) **nunca** inclui `fills` — esse campo só existe
  na resposta de `create_order`. Resultado: `avg_fill_price` ficava `None`
  para **qualquer** ordem consultada por status, mesmo genuinamente
  `FILLED`.
- `execution/orchestrator.py::_finalize_exit` calcula
  `pnl = (exit_order.avg_fill_price - pos.entry_price) * pos.size` — com
  `avg_fill_price=None`, isso é exatamente o `TypeError` observado.
  Acontece **antes** de `self._position` ser limpo (só no fim da função),
  então o próximo candle repete a mesma consulta, o mesmo cálculo, o mesmo
  erro — para sempre, mesmo já sabendo (`status: FILLED`) que a posição
  deveria ter fechado.

## Proposta
- `_to_order_result`: `avg_fill_price` agora vem de
  `cummulativeQuoteQty / executedQty` quando `executedQty > 0` — campo
  presente tanto em respostas de consulta (`get_order`) quanto de criação
  (`create_order`), e matematicamente equivalente à média ponderada de
  `fills`. Só cai de volta em somar `fills` se `cummulativeQuoteQty`
  estiver ausente (não deveria acontecer na prática, mas evita regressão
  silenciosa). `executedQty == 0` (ordem ainda não preenchida) continua
  corretamente retornando `None`, sem dividir por zero.
- **O que não muda**: nenhum parâmetro de risco/execução — é correção de
  parsing de resposta da API, mesma classe dos outros dois bugs
  encontrados nesta mesma investigação mais ampla.

## Classificação de risco da mudança
- [ ] Não é mudança de parâmetro de risco/execução nem de arquitetura —
  correção de bug crítico de parsing na camada de execução. Severidade
  alta pelo mesmo motivo do incidente anterior: uma posição real, já
  protegida corretamente pelo stop-loss, não conseguia ser fechada no
  nosso sistema.

## Validação proposta
- Dois testes novos em `test_execution_client.py`: um reproduz
  exatamente a resposta real capturada da testnet (`FILLED`,
  `cummulativeQuoteQty` presente, sem `fills`) e confirma
  `avg_fill_price` calculado corretamente; outro confirma que uma ordem
  `NEW` (`executedQty=0`) continua retornando `None`, sem erro de divisão
  por zero.
- Suíte completa: 200 passed, 1 deselected (rede) — sem regressão.
- Como o dado da exchange está correto e intacto desta vez (sem reset de
  testnet envolvido, ao contrário do incidente anterior), **não foi
  necessária intervenção manual no banco** — o próximo redeploy deve deixar
  `_check_exit` processar o fill real corretamente e fechar a posição
  sozinho, sem reconciliação manual.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-10
- Justificativa: bug crítico real de produção, reportado pelo usuário com
  print do dashboard, mesma urgência dos incidentes anteriores desta
  semana.
