# Change Proposal — 2026-07-30 — Ordens sem validação de lote mínimo / notional da exchange

**Status:** aplicada

## Evidência (origem)
- Ligada a: auditoria técnica completa de 30/07/2026.
- `risk/manager.py` (`position_size`, `cap_to_max_exposure`) retorna um float
  bruto, sem arredondar para o `stepSize` (LOT_SIZE) do par, sem checar
  `tickSize` (PRICE_FILTER) no preço do stop, sem validar `MIN_NOTIONAL`. Busca
  no repo inteiro por "stepSize/LOT_SIZE/minNotional/tickSize": zero
  ocorrências.
- Na Binance, violar esses filtros é rejeição dura da ordem, não aviso. Hoje
  "funciona" para BTCUSDT só porque a escala do capital configurado
  coincidentemente produz quantidades que passam — não por verificação.

## Proposta
- Adicionar `get_symbol_filters(symbol)` na interface `ExchangeClient`
  (implementado via `exchangeInfo` da Binance no cliente real, e um valor
  configurável no `FakeExchangeClient` de teste).
- Antes de enviar qualquer ordem, `Orchestrator` busca (e cacheia) os filtros
  do símbolo, arredonda a quantidade para baixo no `stepSize` (usando
  `Decimal`, não float puro, para evitar erro de precisão), arredonda o preço
  do stop para o `tickSize`, e valida notional mínimo.
- Se o sinal, depois de arredondado, ficar abaixo do notional mínimo, a
  entrada é rejeitada com um log claro no feed de atividade — em vez de
  enviar uma ordem fadada à rejeição pela exchange.

## Classificação de risco da mudança
- [x] Parâmetro de risco/execução (requer revisão humana obrigatória)

## Validação proposta
- Teste unitário para o arredondamento (`Decimal`) contra casos conhecidos de
  imprecisão de float.
- Teste confirmando que um sinal cujo notional fica abaixo do mínimo é
  rejeitado sem chegar a `place_market_order`.
- Suíte completa do `execution/` sem regressão.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-07-30
- Justificativa: aprovação explícita em conversa, após revisão do achado da
  auditoria técnica.
