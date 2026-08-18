# Change Proposal — 2026-08-18 — Captura de aggTrade (fluxo de ordens / volume por lado)

**Status:** aplicada (código); provisionamento do serviço contínuo no Railway pendente de
confirmação do usuário (infra nova, ver seção própria abaixo).

## Evidência (origem)

Discussão de priorização de melhorias de rigor estatístico e coleta de dado (2026-08-18),
iniciada a partir de pesquisa externa trazida pelo usuário sobre práticas de engenharia de
bots de trading (DSR, PBO/CSCV, custo de execução realista, coleta de order book/funding/
liquidação/on-chain/volume-por-lado, meta-labeling, detecção de regime, camada de risco
independente, MLOps, benchmark, segurança operacional). Mapeamento do código existente
contra essa lista mostrou order book em captura (`2026-08-15`) mas nenhuma captura de
fluxo de ordens/aggressor-side ainda.

O usuário corrigiu a ordenação proposta inicialmente: o eixo certo para sequenciar
captura-de-dado vs. trabalho-de-cálculo é **reversibilidade**, não esforço/alavancagem —
dado de captura tem prazo de validade (cada dia sem captar é um dia de dado perdido para
sempre, já que a Binance não expõe order book/aggTrade histórico retroativo), enquanto
cálculo sobre dado já persistido pode ser adiado indefinidamente com resultado idêntico.
Por esse critério, aggTrade sobe para junto da prioridade mais alta, em paralelo, não
depois do trabalho de validação estatística (DSR/PBO) — spot-only, sem book completo,
deixa order book + fluxo de ordens agressor como as únicas fontes de microestrutura
disponíveis (perpetual futures teria funding/OI/liquidação; não é o caso aqui).

## Proposta

- **`AggTradePayload`** (`ingestion/schema.py`) — payload normalizado do stream
  `<symbol>@aggTrade`, reusando `EventType.TRADE` (já existia no schema desde o desenho
  inicial, nunca implementado). Diferente de `DepthPayload`, tem timestamp (`T`) e id
  monotônico (`a`) autoritativos da própria exchange — sem aproximação por horário local.
- **`BinanceAggTradeStream`** (`ingestion/binance_aggtrade_ws.py`) — mirror direto de
  `BinanceDepthStream`: reconexão com backoff exponencial, parse defensivo (mensagem
  malformada é descartada, não derruba o stream), normalização em `MarketEvent` antes de
  qualquer coisa downstream ver o payload bruto da Binance (spec 02, requisito 3).
- **`AggTradeAggregator`** (`ingestion/aggtrade_aggregator.py`) — acumula trades num bucket
  de 1 minuto (`buy_volume`, `sell_volume`, `buy_count`, `sell_count`, `vwap`), decidindo o
  lado agressor pelo campo `is_buyer_maker` da Binance (`true` = comprador era maker =
  trade iniciado pelo vendedor). Só emite o bucket quando o próximo já começou — mesmo
  padrão anti-vazamento do `_TimeframeAggregator` de `03-motor-de-features.md`. Diferente
  de `DepthSampler` (que amostra, descartando o resto): aqui cada trade é um incremento do
  período, não um estado instantâneo completo, então acumula em vez de descartar.
- **`agg_trade_buckets`** (`persistence/models.py` + `repository.py`) — 1 linha/minuto,
  mesmo padrão de `order_book_snapshots`.
- **`scripts/run_aggtrade_capture.py`** — mirror de `run_depth_capture.py`: roda
  continuamente contra testnet, sem `BINANCE_API_KEY`/`SECRET` (dado de mercado é
  público), nunca importa `tradingbot.execution` (mesmo isolamento do resto da captura e
  do loop de aprendizado, specs 02/09).
- **`specs/02`**: nova seção "Trades agregados / fluxo de ordens (2026-08-18)", espelhando
  a seção de order book de 2026-08-15.
- **`specs/03`**: nova seção "Fluxo de ordens / volume por lado (captura iniciada em
  2026-08-18, sem features ainda)" — só captura, nenhuma feature nova em `FEATURE_NAMES`
  nesta rodada (mesma decisão tomada para order book: sem histórico acumulado, não há como
  validar empiricamente uma feature agora).

## Achado correlato: estado real do loop agentic em produção

Durante a discussão de priorização, o usuário perguntou explicitamente se
`experiment_log.py` persiste série por trial ou só agregado (pergunta que decidiria a
ordem DSR-vs-PBO). Investigação direta do código encontrou:

- `learnings/experiments.jsonl` **nunca foi criado** — o loop agentic
  (`scripts/run_agentic_learning.py`) nunca rodou contra a API real da Anthropic neste
  ambiente, confirmando o aviso já presente no próprio docstring do script.
- O serviço `learning-daily-cron` no Railway roda `scripts/run_daily_learning.py` (o loop
  de relatório diário mais simples, não o loop agentic com raciocínio) — sem
  `ANTHROPIC_API_KEY` configurada nas variáveis do serviço. O loop agentic não está
  agendado em nenhum serviço de produção hoje.
- Isso significa que a divergência de sequenciamento DSR-vs-PBO discutida era sobre uma
  diferença de dado que **não existe ainda** — nenhum dos dois tem trial real logado. O
  gap de implementação real é o mesmo para os dois: `FoldSummary`/`evaluate_fold`
  (`model/evaluation.py`) descarta o PnL por trade dentro do fold, guardando só o agregado
  (`profit_factor`). Fica registrado aqui por afetar diretamente a ordem revisada de
  prioridades (ver mensagem do usuário em 2026-08-18 para a ordem completa) — não é ação
  desta rodada, só o achado que a fundamenta.

## Classificação de risco da mudança

- [ ] Não é mudança de parâmetro de risco/execução — é ingestão de dado de mercado
  público, somente leitura, nunca importa `tradingbot.execution`. Mesma classificação de
  risco que a captura de order book (2026-08-15).

## Validação

- Suíte completa do backend: 285 testes, todos passando (12 novos: 6 de
  `test_binance_aggtrade_ws.py`, 6 de `test_aggtrade_aggregator.py`).
- Testes cobrem: parse de mensagem válida/malformada/campo faltante, extração de símbolo,
  decodificação do lado agressor (`is_buyer_maker`), acumulação dentro do bucket sem
  emissão prematura, emissão só no rollover com totais corretos, VWAP ponderado por
  notional, `ts` do bucket é o início do intervalo (não o timestamp do último trade),
  símbolos rastreados independentemente.
- Sem validação empírica contra dado real ainda — mesma situação em que order book estava
  em 2026-08-15: é captura sem histórico prévio possível, nada para validar contra até
  acumular.

## Pendente de confirmação explícita do usuário

- **Push para o repositório remoto** — código local, não commitado ainda no momento em que
  este arquivo foi escrito.
- **Provisionamento do serviço contínuo no Railway** (`aggtrade-capture`, mirror de
  `depth-capture`: builder Railpack, `rootDirectory=backend`,
  `startCommand=python scripts/run_aggtrade_capture.py`, variáveis `SYMBOL`/
  `DATABASE_URL`) — criação de infraestrutura nova com custo/consumo contínuo, fora do
  escopo de "implementar e commitar localmente" sem confirmação explícita.

## Decisão

- Aprovado por: Brian (usuário, dono do projeto) — "Confirmado — pode começar pelo
  aggTrade" / "Toca o aggTrade" (2026-08-18).
- Justificativa: reversibilidade de captura de dado como eixo de priorização, item
  confirmado como independente e sem dependência das demais mudanças da ordem revisada.
