# Change Proposal — 2026-07-31 — Stop-loss real falhava em 100% das tentativas (PRICE_FILTER no limit price)

**Status:** aplicada

## Evidência (origem)
- Ligada a: log real do engine em testnet, colado pelo usuário — três posições abertas
  em sequência, cada uma com as 3 tentativas de `place_stop_loss_order` falhando com
  `APIError(code=-1013): Filter failure: PRICE_FILTER`, seguidas de fechamento de
  emergência (`emergency_close_no_stop_loss`) em todas.
- `execution/client.py`, `place_stop_loss_order`: o `stopPrice` já chegava arredondado ao
  `tickSize` (fix de 30/07/2026 — validação de regras de exchange), mas o **limit price**
  (`stop_price * 0.999` para venda) nunca passava pelo mesmo arredondamento. Multiplicar
  um preço já alinhado ao tick por `0.999` quase sempre produz um valor com muito mais
  casas decimais que o tick permite — a Binance rejeita por `PRICE_FILTER`.
- Consequência prática: o bot nunca conseguia manter uma posição real aberta — toda
  entrada era imediatamente seguida de fechamento de emergência. O mecanismo de
  emergência (fix de 30/07/2026 — tratamento de exceção) funcionou exatamente como
  projetado como rede de segurança, mas a causa raiz impedia o sistema de operar como
  pretendido.

## Proposta
- `place_stop_loss_order` (Protocol, `BinanceTestnetClient`, `FakeExchangeClient`) ganha
  um parâmetro opcional `tick_size: Decimal`. Quando fornecido, o limit price também é
  arredondado via `round_to_tick` antes de ser enviado — mesma função já usada para o
  `stopPrice`.
- `Orchestrator._try_enter`/`_place_stop_loss_with_retry` passam `filters.tick_size`
  (já buscado e cacheado para a validação de LOT_SIZE/MIN_NOTIONAL) para a chamada.
- **O que não muda:** a lógica de "limit price uma fração abaixo do stop" continua
  igual (`* 0.999`/`* 1.001`); nenhum parâmetro de risco (`stop_loss_pct`) é alterado —
  é puramente uma correção de arredondamento para a ordem ser aceita pela exchange.

## Classificação de risco da mudança
- [x] Parâmetro de risco/execução (requer revisão humana obrigatória) — afeta
  diretamente se uma ordem de stop-loss real consegue ser colocada na exchange.

## Validação proposta
- Teste unitário (`test_execution_client.py`) com um cliente fake capturando os
  argumentos de `create_order`, confirmando que o limit price fica alinhado ao tick
  quando `tick_size` é passado (o teste falharia com o código antigo — `round(limit, 2)
  != limit` para o exemplo real do log).
- Suíte completa sem regressão.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-07-31
- Justificativa: aprovação implícita ao pedir análise do log real mostrando o bot
  incapaz de manter qualquer posição — corrigido imediatamente por ser bug estrutural
  que impede o comportamento já aprovado (stop-loss real funcionando), não uma mudança
  de parâmetro de risco em si.
