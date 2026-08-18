# Change Proposal — 2026-08-18 — Captura de aggTrade (fluxo de ordens / volume por lado)

**Status:** aplicada (código, revisado numa segunda rodada com 4 checagens pedidas pelo
usuário antes de provisionar). Push e provisionamento do serviço contínuo no Railway
aprovados pelo usuário ("push: sim, sem ressalva" / "provisionar: sim") — ver seção final.

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
  de 1 segundo (`buy_volume`, `sell_volume`, `buy_count`, `sell_count`, `vwap`, `notional`),
  decidindo o lado agressor pelo campo `is_buyer_maker` da Binance (`true` = comprador era
  maker = trade iniciado pelo vendedor). Só emite o bucket quando o próximo já começou —
  mesmo padrão anti-vazamento do `_TimeframeAggregator` de `03-motor-de-features.md`.
  Diferente de `DepthSampler` (que amostra, descartando o resto): aqui cada trade é um
  incremento do período, não um estado instantâneo completo, então acumula em vez de
  descartar.
- **`agg_trade_buckets`** (`persistence/models.py` + `repository.py`) — 1 linha/segundo,
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

## Segunda rodada: 4 checagens pedidas antes de provisionar

Antes de aprovar o provisionamento do serviço contínuo, o usuário pediu 4 checagens
explícitas — não por suspeita de que faltassem (é mirror do `depth-capture`), mas porque
são caras de corrigir retroativamente, o mesmo critério de reversibilidade que guiou a
decisão de priorizar esta captura. As 4:

1. **Granularidade do bucket** — mudada de 1 minuto para **1 segundo**
   (`BUCKET_INTERVAL_MS`). Bucket size é irreversível (dá pra agregar mais grosso depois
   somando linhas, nunca mais fino a partir de uma linha já gravada) — errar para o lado
   granular. `AggTradeBucketFields` ganhou `notional` (preço×quantidade somado, não só o
   vwap já dividido) precisamente para permitir merges exatos depois (ver item 2). Custo:
   ~86 400 linhas/dia no pior caso para BTCUSDT — trivial para o Postgres do Railway,
   ordem de grandeza consistente com o que `order_book_snapshots` já roda sem problema
   (essa já opera há 3 dias em produção sem qualquer sinal de custo/degradação).
2. **Detecção de gap + backfill via REST** — `agg_trade_id` é monotônico, então
   `BinanceAggTradeStream` compara cada novo id contra o último visto e emite
   `MarketEvent(GAP, {"expected_from_id", "found_id", "missing_count"})` a cada salto.
   `fetch_agg_trades` (novo em `binance_rest.py`) pagina via `fromId` até um `to_id`
   (é o único dos 3 métodos REST do arquivo com um teto de correção pelo lado de cima,
   diferente de `fetch_klines`/`fetch_exchange_info`/`fetch_24h_tickers`, mas necessário
   aqui porque sabemos exatamente onde o buraco termina). `run_aggtrade_capture.py` roda
   esse backfill via `asyncio.to_thread` (a REST é síncrona/bloqueante; chamá-la direto no
   event loop travaria o ping/pong do WebSocket ao vivo, arriscando um novo disconnect
   *causado pelo próprio backfill*) e faz merge nos buckets já persistidos via
   `upsert_agg_trade_bucket` (soma os campos brutos, recalcula vwap a partir do notional
   total — não a partir de uma média de vwaps já perdidos, que não reproduziria o valor
   exato). Gaps maiores que `MAX_BACKFILL_TRADES` (50 000 — a REST da Binance só serve uma
   janela recente) são logados e aceitos como buraco conhecido, não perseguidos
   indefinidamente — dado nunca capturável de volta não é o mesmo problema que dado
   temporariamente furado.
3. **Timestamp da exchange** — já herdado desde a primeira rodada
   (`exchange_ts=payload.trade_time`, o campo `T` da Binance), confirmado por leitura
   direta do código, não por suposição.
4. **Liveness** — nem `depth-capture` nem `aggtrade-capture` tinham nenhum sinal de "o
   coletor morreu calado" (só o kline stream tinha `_maybe_gap_event`, tempo desde a
   última mensagem, checado a cada reconexão). Espelhado agora nos dois
   (`BinanceDepthStream`/`BinanceAggTradeStream`), logado via `logger.error` quando
   nenhuma mensagem chega por mais de 10s antes de uma reconexão. **Limitação honesta,
   não resolvida**: este projeto não tem canal de alerta externo configurado (sem Slack/
   e-mail/pager) — o sinal fica visível em log, não como notificação ativa. Cobre um modo
   de falha diferente do que o `restartPolicyType=ALWAYS` do Railway já cobre (esse
   recupera de crash; o heartbeat cobre "processo vivo mas silencioso").

Efeito colateral do item 2 que também vale registrar: `AggTradeAggregator` ganhou
`flush(symbol)`, que fecha o bucket em formação sem esperar o próximo trade — usado tanto
pelo backfill (que processa um lote finito, sem "próximo trade" natural para disparar o
rollover) quanto por `run_aggtrade_capture.py` num `finally` ao encerrar o processo, o que
incidentalmente também corrige uma perda pré-existente (até 1s de dado perdido a cada
restart/deploy, que antes desta mudança era descartado silenciosamente).

## Classificação de risco da mudança

- [ ] Não é mudança de parâmetro de risco/execução — é ingestão de dado de mercado
  público, somente leitura, nunca importa `tradingbot.execution`. Mesma classificação de
  risco que a captura de order book (2026-08-15).

## Validação

- Suíte completa do backend: 302 testes, todos passando (29 novos no total das duas
  rodadas: parsing/aggressor-side/malformado, acumulação e rollover do bucket, VWAP e
  notional exatos, `flush()`, gap por id (com e sem buraco, e no primeiro trade da
  conexão), heartbeat de liveness (com e sem gap), paginação de `fetch_agg_trades`
  (página cheia, página curta, corte em `to_id`, resposta vazia), `upsert_agg_trade_bucket`
  (insert novo, merge em bucket existente com soma exata dos campos brutos, isolamento por
  symbol/ts diferentes).
- Sem validação empírica contra dado real ainda — mesma situação em que order book estava
  em 2026-08-15: é captura sem histórico prévio possível, nada para validar contra até
  acumular.

## Incidente durante o provisionamento: build quebrado por Python 3.13 sem pin

Ao provisionar `aggtrade-capture` no Railway (serviço novo, sem cache de build
reaproveitável), o primeiro deploy falhou — não por causa de `rootDirectory`/config (essa
parte funcionou, o Railpack detectou corretamente `backend/` na segunda tentativa) mas por
`psycopg2-binary==2.9.9` falhar ao compilar contra Python 3.13 (`_PyInterpreterState_Get`,
removida da API pública do CPython 3.13 — o pacote não tem wheel pré-compilada para essa
versão e cai para build de fonte, que quebra). O builder Railpack usa `mise` e, sem pin
explícito, instala o Python mais recente disponível — este projeto nunca fixou uma versão.

**Isso não é exclusivo do `aggtrade-capture`** — é um risco latente para todo serviço
Python do projeto (`tradding_bot`, `depth-capture`, `learning-daily-cron`). Eles só não
sentiram ainda porque reaproveitam cache de builds anteriores, feitos antes do Railpack
apontar para 3.13 por padrão; qualquer rebuild 100% frio deles (mudança de dependência,
cache do Railway invalidado/expirado) bateria no mesmo erro — incluindo `tradding_bot`, que
tem capital real em jogo.

**Fix**: `backend/.python-version` (novo arquivo, conteúdo `3.12`) — mesma versão que já
roda localmente (`.venv` em 3.12.3). Aplica-se a todos os 4 serviços com
`rootDirectory=backend` (mesmo arquivo compartilhado), fechando o risco latente nos outros
três de brinde, não só no novo.

**Nota sobre a mecânica de deploy do Railway** (achado técnico, reforça a lição já
registrada em `changes/2026-08-18-monorepo-root-learnings-changes.md`): `redeploy` **não**
sempre reusa a build anterior sem re-executar o pipeline — quando chamado num serviço cujo
deployment mais recente falhou, ele efetivamente builda de novo (confirmado aqui: usou o
`rootDirectory` corrigido via `update-service` na tentativa seguinte, gerando um
`snapshotId` novo). A ressalva já documentada (redeploy não reaplica mudança de
`startCommand` num deployment que já teve sucesso) continua válida — são mecânicas
diferentes dependendo do estado anterior do deployment.

## Pendente

- **Provisionamento do serviço contínuo no Railway** (`aggtrade-capture`, mirror de
  `depth-capture`: builder Railpack, `rootDirectory=backend`,
  `startCommand=python scripts/run_aggtrade_capture.py`, variáveis `SYMBOL`/
  `DATABASE_URL`) — próximo passo desta mesma sessão, já aprovado pelo usuário.

## Decisão

- Aprovado por: Brian (usuário, dono do projeto) — "Confirmado — pode começar pelo
  aggTrade" / "Toca o aggTrade" (primeira rodada); "push: sim, sem ressalva" / "provisionar
  o aggtrade-capture: sim" condicionado às 4 checagens acima (segunda rodada), ambas em
  2026-08-18.
- Justificativa: reversibilidade de captura de dado como eixo de priorização; as 4
  checagens da segunda rodada são caras de corrigir depois de o serviço já estar
  acumulando dado com o desenho errado (bucket grosso demais, gap silencioso, coletor
  morrendo sem sinal) — mesmo raciocínio de custo-de-correção-retroativa que já guiava a
  decisão original.
