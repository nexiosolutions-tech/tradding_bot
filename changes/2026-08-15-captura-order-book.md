# Change Proposal — 2026-08-15 — Captura de order book (BTCUSDT, sem features ainda)

**Status:** aplicada

## Evidência (origem)
- Ligada a: 12ª rodada (`specs/11-roadmap-e-fases.md`) — quatro rodadas seguidas
  (9ª a 12ª) iterando só sobre o próprio preço/volume da série OHLCV não
  fecharam o gap de promoção. Order book é a primeira fonte de informação
  que não é uma transformação do mesmo dado.
- Pedido explícito do usuário: "aceito também a sua recomendação" (referente
  à proposta de investigar order book como próxima frente de arquitetura),
  seguido de "Sim, podemos prosseguir" confirmando o formato proposto
  (símbolo único, `depth20@1000ms`, amostragem de 1/minuto, serviço
  contínuo dedicado).

## Proposta
- `EventType.DEPTH` (já existia no schema, nunca implementado) ganha
  `DepthPayload` (`ingestion/schema.py`) e um cliente real
  (`ingestion/binance_depth_ws.py::BinanceDepthStream`), espelhando
  `BinanceKlineStream`.
- `ingestion/depth_sampler.py` reduz o stream (~1 update/s) a 1
  amostra/minuto e pré-computa `spread_pct`/`imbalance`/profundidade —
  puro, sem dependência de persistência, testável isoladamente.
- Tabela nova `order_book_snapshots` (`persistence/models.py`) + função de
  repositório `record_order_book_snapshot`.
- `scripts/run_depth_capture.py` — processo contínuo novo, só leitura de
  mercado (sem `BINANCE_API_KEY`/`SECRET`, nunca importa
  `tradingbot.execution`, mesma separação que o loop de aprendizado já
  segue — specs/09).
- **O que não muda**: nenhuma feature nova em `FEATURE_NAMES`/
  `model/dataset.py` nesta rodada — é só captura. Motivo: a Binance não
  expõe order book histórico (`GET /api/v3/depth` rejeita timestamp
  passado, confirmado 2026-08-15), então não há como validar uma feature
  agora contra dado real — precisa acumular primeiro.

## Classificação de risco da mudança
- [x] Mudança de arquitetura (novo tipo de evento implementado, nova
  tabela, novo serviço — `CLAUDE.md` regra 7, spec 02/03 atualizadas antes
  do código).
- Não é mudança de parâmetro de risco/execução.
- Não toca `tradingbot.execution` nem a estratégia ao vivo — puramente
  aditivo, roda em processo separado do bot de execução.

## Validação
- Confirmado contra `testnet.binance.vision` real: mensagem do stream
  parseada corretamente (formato `{"stream": ..., "data": {...}}`,
  símbolo extraído do nome do stream já que o payload de depth não traz
  campo de símbolo nem de timestamp).
- 15 testes novos (parsing de mensagem malformada/válida, amostragem
  1x/minuto, round-trip de persistência) + suíte completa: 215 passando.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-15
- Justificativa: continuação direta da recomendação aceita. Como não há
  histórico retroativo possível, a captura tem que começar o quanto antes
  — o desenho da feature em cima disso fica para quando houver dado
  acumulado suficiente (não decidido nesta rodada).
