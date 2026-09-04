# 2026-09-04 — Frescor do motor e volta das duas capturas ao mainnet via WebSocket

## Contexto

Execução dos passos 1 e 2 do plano que Brian propôs em resposta ao inventário de
2026-09-01 (`changes/2026-09-01-inventario-pos-pausa.md`), com duas reordenações
explícitas dele: a asserção de frescor entra antes da mudança de região (instrumento
ligado antes de mexer no que ele deveria vigiar), e as duas capturas são tratadas como
mudanças separadas, não uma só, para que uma falha na primeira não vire dois problemas
simultâneos.

---

## 1. Asserção de frescor do `engine_events` no relatório diário

O achado mais preocupante do inventário foi um gap de 151h em `engine_events` que
ninguém percebeu — o relatório diário (`daily_report.py`, cron às 03:00 UTC, nunca
falhou em rodar) já tinha um mecanismo de frescor (`CAPTURE_FRESHNESS_TARGETS`) para
`order_book_snapshots` e `agg_trade_buckets`, mas nunca cobriu a liveness do próprio
motor.

Estendido o mesmo mecanismo:

- `repository.py::count_engine_events_in_range` — nova função de contagem, mesmo padrão
  das duas existentes; `environment` no assinatura só por uniformidade (`EngineEvent`
  não tem essa coluna — é sempre o processo real, nunca sintético).
- `ENGINE_EVENTS_DAILY_FLOOR = 3` — piso medido na distribuição real (mínimo de 7/dia em
  dias genuínos, zero nos dias do apagão), com a mesma margem de segurança generosa (bem
  abaixo do mínimo real, bem acima de zero) já usada nos outros dois pisos.
- `CaptureFreshness.environment` passou a aceitar `None`, e o rótulo no markdown omite
  o `(ambiente)` quando ausente.

`test_daily_report.py` atualizado para semear `EngineEvent` no teste de frescor —
suite completa (12 testes do arquivo): 12 passed.

Commit: `bc6b778`.

---

## 2. As duas capturas de volta ao WebSocket direto, mainnet

### Achado que viabiliza a mudança

O inventário confirmou (handshake WS real + REST 200, testado via socket bruto de
`europe-west4`, não só chamada de biblioteca) que `stream.binance.com`/
`api.binance.com` respondem plenamente dessa região — o HTTP 451 que tirou o
`aggtrade-capture` do WS em 18/08 (`changes/2026-08-18-captura-aggtrade-fluxo-ordens.md`)
era específico de `us-east4`.

### Sequência seguida (por cuidado explícito do Brian: "a captura não pode parar no
meio")

Confirmado via documentação oficial do Railway (`docs.railway.com/deployments/regions`)
que troca de região é *in-place e sem downtime*, desde que o serviço não tenha volume
anexado (nenhuma das duas capturas tem) — não é recriar+desligar. Sequência usada para
cada serviço, nessa ordem, e as duas capturas tratadas em rodadas separadas:

1. `railway scale <região-nova>=1 <região-velha>=0` — região muda, código antigo
   continua rodando sem alteração (zero risco de comportamento).
2. Confirmado `SUCCESS` na nova região via `get-logs`/`get-service-config` antes de
   qualquer commit.
3. Só então o código muda (toggle testnet→mainnet ou reescrita WS-primário), commit,
   push, redeploy — nunca uma janela com região nova e código incompatível, nem o
   inverso.

`aggtrade-capture` primeiro (mudança pequena — só o toggle `USE_TESTNET`); confirmado
gravando mainnet de verdade antes de tocar no `depth-capture`.

### `aggtrade-capture`

- Região: `us-east4-eqdc4a` → `europe-west4-drams3a`.
- `USE_TESTNET = False` (`run_aggtrade_capture.py:58`) — comanda o stream WS, o cliente
  REST de backfill e o rótulo `environment` gravado em cada linha, os três nunca podem
  divergir entre si.
- `.vision` mantido como fallback de backfill (`_backfill_gap`), não removido.
- Verificado no Postgres (2026-09-04, ~34h de dado mainnet acumulado): 77.065 buckets,
  defasagem do último bucket em relação a agora de 4,0s, gap mediano de 1,0s (o
  esperado). 1.103 gaps >2s (1,4%) presos em ~3s cada, sem crescer com o tempo,
  concentrados nas horas de menor volume de negociação (06h–08h UTC) — assinatura de
  segundos genuinamente sem trade, não de escrita atrasada.
- **Cuidado do Brian sobre latência Postgres verificado e descartado como risco atual**:
  as capturas pagam ~87ms de travessia até o Postgres em `us-east4` agora que rodam na
  Europa; para o `aggtrade-capture` (1 bucket/s) isso poderia acumular atraso, mas os
  números acima mostram que não está acontecendo. Sem necessidade de lote por enquanto —
  revisitar se a defasagem do último bucket começar a crescer de forma sustentada.

Commit: `b57a6ec`.

### `depth-capture`

Mudança maior que um toggle: reescrita para WS-primário/REST-fallback (o serviço
sempre foi mainnet via `data-api.binance.vision`, nunca teve o bloqueio de região do
aggTrade — a mudança aqui é abandonar REST puro pelo WS como caminho principal).

- `run_depth_capture.py` reescrito: tarefa de fundo consome `BinanceDepthStream`
  continuamente, atualizando um estado compartilhado (`latest`/`latest_local_ts`); o
  laço de amostragem (1/60s) decide via `deve_usar_ws(latest_local_ts, agora, limiar=90s)`
  — pura, testável sem asyncio/rede — se persiste o snapshot do WS ou cai para uma
  chamada REST avulsa no ciclo. Nunca fica sem amostra; nunca persiste dado obsoleto do
  WS achando que é atual (limiar de 90s dá folga sobre o backoff de reconexão do próprio
  stream, até 30s).
  `.vision` mantido como fallback ativo, não removido — "acabou de provar que funciona
  quando o direto não está disponível", nas palavras do Brian.
- `test_run_depth_capture.py` (novo): 5 testes cobrindo `deve_usar_ws` isoladamente —
  sem evento ainda, evento fresco, exatamente no limiar (tratado como obsoleto,
  conservador), evento velho, limiar customizado.
- Região: `us-east4-eqdc4a` → `europe-west4-drams3a`, confirmada `SUCCESS` antes do
  commit.
- Verificado no Postgres após o deploy (2026-09-04, ~406h de histórico mainnet, a
  maior parte pré-existente ao WS já que o serviço sempre foi mainnet): 24.093
  snapshots, cadência mediana de 60,8s (esperado: 60s), só 5 gaps >120s em 24.092
  intervalos (0,02%), defasagem do último snapshot de 15,7s, preços e spread reais e
  plausíveis (~$79.500, spread ~1,26e-7). Deploy logs mostram 4 reconexões de WS em
  ~24h de operação ("no close frame received or sent, reconnecting in 1.0s") — o
  backoff automático do próprio `BinanceDepthStream` funcionando como projetado, não
  falha.

Commit: `7c90652`.

---

## O que fica para a próxima rodada

Histórico pré-corte (18/08–01/09 do aggTrade, e o testnet anterior do depth) permanece
não migrado — recuperável via `data.binance.vision`, confirmado no inventário. Backfill
fica para depois da região estabilizar (já estabilizou; ainda não feito), com o
requisito explícito do Brian: bucketização precisa ser a mesma função nos dois
caminhos (vivo e arquivo), validada por um teste que force saída idêntica para o mesmo
lote bruto — sem isso, quebra silenciosa de regime na fronteira entre as duas eras.

Também pendentes, sem relação com esta rodada: persistir `equity_curve`/`total_pnl`/
`gross_profit`/`gross_loss` em `learning_engine/tools.py` (passo 3 do plano); redimensionar
o walk-forward (passo 5).

---

## Decisão

- Aprovado por: Brian — autorizou a execução com duas reordenações explícitas: inverter
  a ordem (frescor antes da região, "ligar o instrumento antes de mexer no que ele
  deveria vigiar") e tratar as duas capturas como mudanças separadas, não uma só
  ("mover as duas juntas transforma um problema em dois simultâneos"). Deu três
  cuidados específicos para a mudança de região (captura não pode parar no meio; manter
  `.vision` como fallback documentado; verificar se a latência extra até o Postgres não
  causa atraso no `aggtrade-capture`) — os três endereçados e verificados nesta rodada
  (2026-09-04).
- Justificativa: um serviço de captura de produção só deve mudar de região com o
  instrumento que vigia sua saúde já ligado, e uma mudança de infraestrutura arriscada
  se divide em partes que falham independentemente, não em um bloco só — a mesma
  disciplina de "medir antes de mudar" aplicada à infraestrutura, não só ao código.
