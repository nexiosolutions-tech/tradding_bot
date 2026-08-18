# Change Proposal — 2026-08-18 — Captura de aggTrade e order book (fluxo de ordens)

**Status:** aplicada e em produção. `depth-capture` roda em **mainnet real** (REST via
`data-api.binance.vision`, desde a sexta rodada). `aggtrade-capture` continua em
**testnet** por ora (conversão planejada, não urgente — arquivo histórico cobre o atraso).
Seis rodadas: (1) implementação inicial, (2) 4 checagens pré-provisionamento
(granularidade, gap/backfill, timestamp, liveness), (3) tentativa de correção de ambiente
para mainnet + frescor real no relatório diário, (4) mainnet bloqueado geograficamente pelo
Railway (`HTTP 451`) — revertido para testnet no mesmo dia, (5) sondagem completa (rotas
concretas, handshake WS real, 3 regiões) — achado: `data-api.binance.vision` (API viva, não
arquivo) não está bloqueado nem na região atual, (6) `depth-capture` convertido para REST
mainnet no mesmo dia do achado. Ver seções cronológicas abaixo.

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

- Suíte completa do backend: 307 testes, todos passando (34 novos no total das três
  rodadas: parsing/aggressor-side/malformado, acumulação e rollover do bucket, VWAP e
  notional exatos, `flush()`, gap por id (com e sem buraco, e no primeiro trade da
  conexão), heartbeat de liveness (com e sem gap), paginação de `fetch_agg_trades`
  (página cheia, página curta, corte em `to_id`, resposta vazia), `upsert_agg_trade_bucket`
  (insert novo, merge em bucket existente com soma exata dos campos brutos, isolamento por
  symbol/ts diferentes), contagem de linhas por range (`count_order_book_snapshots_in_range`/
  `count_agg_trade_buckets_in_range`), frescor OK/ALERTA no relatório diário e isolamento
  por janela de 24h.
- Sem validação empírica contra dado real de mainnet ainda — captura acabou de trocar de
  ambiente, sem histórico prévio nesse regime pra validar contra até acumular.

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

## Terceira rodada: testnet mascarava o próprio dado que a captura existe pra pegar

O usuário identificou que os dois serviços de captura (`depth-capture` desde 2026-08-15,
`aggtrade-capture` desde esta mesma sessão) estavam rodando contra `testnet.binance.vision`
— herdado por padrão do resto do projeto sem questionar. Argumento: livro de ofertas e
fluxo agressor do testnet são movidos por um punhado de outros bots em teste, não por
participantes reais — não carregam sinal de microestrutura nenhum, é ruído sintético
gravado segundo a segundo. Paralelo direto com o achado da correção de taxa de
2026-08-16 (`fees_paid=0` no testnet mascarando lucratividade real): mesmo modo de falha —
testnet parecendo dado real e não sendo — só que ali era corrigível retroativamente com uma
constante (`FeeModel`), e aqui não é: dado de microestrutura capturado errado não se
reconstrói.

**Por que isso não fere a regra 1 do `CLAUDE.md`** ("testnet primeiro, sempre"): essa regra
governa a camada de execução (`06-camada-de-execucao.md`) — mudança que pode gerar ordem
real. `depth-capture`/`aggtrade-capture` são streams públicos de market data, sem
`BINANCE_API_KEY`/`SECRET`, sem nenhum caminho de código que chegue a
`tradingbot.execution` — não têm capital em risco, então não são a "mudança na camada de
execução" que a regra 1 protege. Ambiente de execução (`tradding_bot`, continua testnet) e
ambiente de dado (as duas capturas, agora mainnet) são independentes por design — a exceção
não é ad-hoc, decorre de a captura ser estruturalmente incapaz de originar uma ordem.

- **Fix**: `testnet=True` → `testnet=False` em `run_depth_capture.py` e
  `run_aggtrade_capture.py` (stream WS e, no caso do aggTrade, também o `BinanceRestClient`
  do backfill — precisa ser mainnet também, já que os ids de trade de testnet e mainnet são
  sequências completamente diferentes; backfillar um gap mainnet contra a REST de testnet
  devolveria dado sem relação nenhuma com o buraco real).
- **Consequência aceita, não corrigida retroativamente**: `order_book_snapshots` capturado
  entre 2026-08-15 e o deploy desta correção é testnet — não apagado (decisão de
  descartar vs. manter como referência fica para quando alguém for de fato consumir o
  dado), mas documentado como não-usável em `specs/02`/`specs/03`. Isso derruba a premissa
  original do item 7 da fila ("calibrar slippage contra o order book já capturado") só
  parcialmente: o item continua válido, só que sobre dado que começa a existir a partir de
  agora, não do que já foi acumulado.
- **Sem consequência equivalente para `agg_trade_buckets`**: o serviço só entrou em
  produção nesta mesma sessão, antes de qualquer linha real ter sido persistida em
  produção — não há janela testnet para descartar.

## Frescor da captura como sinal de liveness real

A limitação já documentada na segunda rodada ("só log, sem alerta externo") foi fechada
sem provisionar nada novo: `run_daily_learning.py` já roda diariamente
(`learning-daily-cron`) — ganhou uma asserção de frescor (`daily_report.py`) que conta
linhas gravadas em `order_book_snapshots`/`agg_trade_buckets` nas últimas 24h contra um
piso conservador (`ORDER_BOOK_SNAPSHOT_DAILY_FLOOR=500`, `AGG_TRADE_BUCKET_DAILY_FLOOR=5000`
— bem abaixo do teórico de cada captura, pra não falso-positivar num redeploy breve, mas
alto o suficiente pra pegar um coletor parado a maior parte do dia). Sempre renderizado no
relatório (`## Frescor da captura de dados`), não só quando há alerta, e também impresso no
console/log do cron quando abaixo do piso. Ver `specs/09-aprendizado-continuo.md`.

## Quinta rodada: bloqueio geográfico é bloqueador de go-live, não só de captura

O usuário reclassificou o achado do incidente abaixo: `HTTP 451` num endpoint de market
data pública — sem chave, sem ordem, sem risco, o mais permissivo que a Binance oferece —
significa que o bloqueio é de **região**, não de credencial ou rota específica. Combinado
com o bloqueio já conhecido para execução de ordens (mesma causa raiz), a conclusão é
estrutural: nesta infraestrutura, o projeto não tem caminho para operar com capital real.
No dia em que um modelo passar pelo gate de promoção (`07-backtesting-e-validacao.md`), ele
não vai ter para onde enviar a ordem. Isso reordena a fila de prioridades acima de qualquer
item estatístico — não é "resolver depois do benchmark", é pré-requisito de o projeto
existir em produção.

Duas ações baratas antes de investigar região/proxy (ambas aplicadas nesta rodada):

- **Coluna `environment`** nas duas tabelas de captura (ver `specs/02-ingestao-de-dados.md`)
  — o alçapão de irreversibilidade que estava armado: sem marcar a origem agora, o dia em
  que mainnet começasse a fluir para as mesmas tabelas misturaria sinal real com ruído
  sintético sem como separar depois.
- **Sondagem de conectividade por hostname** a partir do ambiente real do Railway (não do
  sandbox local, que não reflete o bloqueio de região) — `stream.binance.com`,
  `api.binance.com`, `data-api.binance.vision`, `data.binance.vision`. O último é o mais
  relevante: se não bloqueado, a Binance publica arquivos históricos de aggTrades para
  download, o que daria backfill de meses de fluxo agressor real de mainnet e desarmaria
  boa parte do argumento de irreversibilidade que colocou a captura ao vivo na posição
  zero. Resultado documentado abaixo, junto com o incidente que motivou a investigação.

## Resultado da investigação: sondagem de conectividade + opções de região

**Correção sobre o que cada host `.vision` é** (achado do usuário, não meu — a sondagem
original tratou os dois iguais e isso estava errado): `data-api.binance.vision` é a **API
viva** — espelho público das mesmas rotas REST de `api.binance.com` (`/api/v3/depth`,
`/api/v3/aggTrades`, `/api/v3/klines`), sem chave, sem execução. `data.binance.vision` é o
**arquivo histórico** (download de klines/trades/aggTrades já fechados). São coisas
diferentes com implicações diferentes — a sondagem v2/v3 (`scripts/probe_connectivity.py`)
testou as duas de forma distinta: rotas concretas (não só a raiz) na API viva, e o
bucket S3 por trás do arquivo (a página humana é renderizada em JS, não tem listing no
HTML puro).

**Sondagem nas 3 regiões** (3 serviços Railway descartáveis, um por região — `probe-useast`
em `us-east4` (a região atual), `probe-singapore` em `asia-southeast1`, `probe-netherlands`
em `europe-west4`, todos deletados logo depois de capturar o resultado):

| Teste | us-east4 (atual) | Singapura | Holanda |
|---|---|---|---|
| `stream.binance.com` (GET raiz) | `451` | conecta (404 na rota) | conecta (404 na rota) |
| `api.binance.com` (GET raiz) | `451` | `200` | `200` |
| **Handshake WS real** (`wss://stream.binance.com/ws/btcusdt@aggTrade`, lê 1 mensagem) | **FALHOU (451)** | **OK — mensagem real recebida** | **OK — mensagem real recebida** |
| `data-api.binance.vision` — `/api/v3/depth`, `/api/v3/aggTrades`, `/api/v3/klines` | `200` nas 3, dado real | `200` nas 3, dado real | `200` nas 3, dado real |
| `data.binance.vision`, bucket `data/spot/daily/` | `aggTrades/`, `klines/`, `trades/` — **sem `depth`** | idêntico (dado global, não geo-restrito) | idêntico |

O teste de handshake real (não só GET na raiz, que dá 404 num host só-WS mesmo sem
bloqueio — correção de um probe anterior próprio, viciado) é a evidência mais forte:
confirma que Singapura e Holanda têm acesso **completo** — REST e WS, os mesmos domínios
`.com` que hoje bloqueiam `us-east4` — e que `us-east4` é a única das três realmente
bloqueada.

**O achado maior, que muda a urgência**: `data-api.binance.vision` responde `200` com dado
real nas rotas concretas **mesmo em `us-east4`, a região bloqueada de hoje**. Isso significa
que a captura ao vivo de mainnet não depende de resolver o bloqueio geográfico — dá pra
fazer `depth-capture` via polling em `GET /api/v3/depth` (é literalmente 1 requisição/minuto,
a mesma cadência que já existe) e `aggtrade-capture` via polling em `/api/v3/aggTrades`
(reaproveitando o `fetch_agg_trades` paginado por `fromId` já escrito para o backfill, só
que contínuo em vez de sob demanda) **sem trocar região, sem proxy, sem custo novo, na
infraestrutura de hoje**. Nenhuma das duas conversões foi implementada nesta rodada — fica
como decisão do usuário, não execução automática.

**Depth não tem arquivo histórico para spot** (pergunta do usuário, respondida): o bucket
`data/spot/daily/` só tem `aggTrades`, `klines`, `trades` — **sem `depth`/`bookDepth`**. O
argumento de irreversibilidade sobre order book continua de pé mesmo se o backfill de
aggTrade for implementado — não há "arquivo" pra recuperar depth perdido, só captura ao
vivo daqui pra frente.

**Opções de região do Railway** (`railway api 'query { regions { name country location } }'`):
todas as 13 regiões disponíveis são EUA (`us-east4-eqdc4a`/`us-east-1`/`us-east4`/
`us-east4-eqdc16a`/`us-west1`/`us-west2`/`us-west2-aws`/`us-west2-cssv9a`), Singapura
(`asia-southeast1-eqsg3a`/`asia-southeast1`) ou Holanda
(`europe-west4-drams3a`/`europe-west4`/`europe-west4-drams11a`) — nenhuma opção fora dessas
três jurisdições. Trocar para outra região dos EUA não muda nada (bloqueio é por
país/jurisdição, não por datacenter específico). Confirmado (tabela acima): Singapura e
Holanda passam nos dois testes, `us-east4` falha nos dois.

**Ressalva do usuário, registrada por completude**: não presumir qual região passa a
situação regulatória da Binance por jurisdição muda e é diferente em cada uma — testar em
vez de deduzir (foi o que a sondagem fez). E hospedar fora dos EUA é escolha normal de
infraestrutura (o usuário está no Brasil, jurisdição não bloqueada; o `451` é da região do
Railway, não do usuário) — mas antes de mover **execução real** pra lá, confirmar que a
hospedagem escolhida é compatível com os termos de uso da Binance é decisão do usuário,
a checar uma vez, não a cada deploy.

**Síntese que reordenou a fila originalmente** (razão do usuário): `HTTP 451` num endpoint
de market data pública indica bloqueio de região, não de credencial — combinado com o
bloqueio já conhecido para execução, a infraestrutura atual não tinha caminho pra capital
real. O achado desta rodada (`data-api.binance.vision` aberto até em `us-east4`) refina
essa conclusão: o bloqueio de **captura** tem solução hoje, sem mexer em região; o bloqueio
de **execução** continua de pé e só se resolve com região/proxy — mas isso deixa de ser
urgente, porque não há modelo promovível ainda (`07-backtesting-e-validacao.md`).

**Nada disso foi executado** — troca de região, proxy, VPS dedicado, ou conversão de
WS para polling REST são decisões do usuário (custo, superfície nova, esforço de
implementação). Esta seção é só o levantamento pedido.

## Incidente durante a sondagem: corrida real em `upsert_agg_trade_bucket` derrubou o serviço

Efeito colateral do processo de investigação, não do achado em si: pra rodar
`probe_connectivity.py`, o `startCommand` do `aggtrade-capture` foi trocado via
`update-service` + `redeploy`. Descoberta nova (reforça a lição já registrada no incidente
abaixo): `redeploy` **não** builda/aplica config nova quando o deployment anterior já
tinha tido sucesso — ele reexecuta com o `startCommand` antigo. Na prática, isso significa
que cada `redeploy` desse tipo é uma reinicialização do serviço real, e o Railway roda a
instância antiga e a nova lado a lado por um instante — as duas colidiram tentando inserir
o mesmo bucket `(symbol, ts)` corrente, e `upsert_agg_trade_bucket` não tinha proteção
contra esse SELECT-then-INSERT não ser atômico entre processos: uma das duas estourou
`IntegrityError` não tratado e derrubou o processo (ficou parado ~4 minutos, já que
`restartPolicyType` estava temporariamente `NEVER` por causa do teste).

- **Fix**: `upsert_agg_trade_bucket` (`repository.py`) agora captura o `IntegrityError` no
  caminho de insert, re-busca a linha (que a instância concorrente acabou de gravar) e cai
  no caminho de merge — mesmo padrão já usado em
  `db.py::_ensure_capture_environment_column` pra essa mesma classe de corrida. Teste novo
  reproduz o incidente exato (uma segunda sessão insere no meio do commit da primeira).
- **Caminho final que funcionou pra rodar a sondagem de verdade**: em vez de reaproveitar
  um serviço já com deployment bem-sucedido (sujeito a essa mesma limitação do `redeploy`),
  criado um serviço Railway descartável (`probe-temp`) — todo serviço novo tem seu primeiro
  deployment genuinamente fresco, então build+config corretos na primeira tentativa útil
  (a primeiríssima, antes de configurar `rootDirectory`, falhou do mesmo jeito que
  `aggtrade-capture` original — o segundo `redeploy`, agora sobre um deployment que tinha
  **falhado**, pegou a config nova, confirmando de novo que `redeploy` só builda fresco
  quando o anterior não teve sucesso). Serviço deletado (`railway service delete`) depois
  de capturar o resultado.

## Incidente: mainnet bloqueado geograficamente — revertido para testnet no mesmo dia

O raciocínio da terceira rodada (mainnet é o ambiente certo pra captura de dado) estava
correto, mas a execução expôs um problema de infraestrutura não previsto: assim que os dois
serviços foram redeployados apontando pra mainnet, toda tentativa de conexão WebSocket
(`@aggTrade` e `@depth20@1000ms`) foi rejeitada com `HTTP 451` — bloqueio geográfico da
Binance contra a região do projeto no Railway. Mesma família de bloqueio já identificada
para execução de ordens em investigação anterior deste projeto, agora confirmada também
para market data pública (não é um bloqueio restrito a endpoints de trading).

- **Efeito em produção**: os dois serviços entraram em loop de reconexão com backoff
  exponencial (o próprio `_maybe_liveness_gap_event`/`websockets` funcionando exatamente
  como desenhado — reconectando, não travando), mas nunca conseguiram estabelecer conexão.
  Resultado: ~15-20 minutos sem capturar **nenhum** dado, nem testnet nem mainnet (o
  processo antigo, em testnet, já tinha sido substituído pelo deploy novo).
- **Detecção**: manual, via `mcp__railway__get-logs` logo depois do redeploy — a asserção
  de frescor recém-adicionada ao `run_daily_learning.py` também teria pego isso no ciclo
  seguinte do cron (piso de linhas nas últimas 24h), mas não é imediata (roda 1x/dia); vale
  registrar como um limite real do mecanismo de liveness, não só uma vantagem.
- **Fix imediato**: revertido `testnet=False` → `testnet=True` nos dois scripts (stream WS
  e, no aggTrade, também o `BinanceRestClient` do backfill — precisa casar com o ambiente
  do stream, já que as sequências de id de testnet e mainnet não têm relação nenhuma entre
  si). Push + redeploy confirmado via logs: os dois voltaram a conectar normalmente.
- **Não resolvido, fica para depois**: o bloqueio geográfico de verdade — provisionar numa
  região do Railway fora do bloqueio, ou um proxy/relay. Até lá, a captura continua em
  testnet (baixo sinal, mas não zero) e a limitação já registrada em `specs/02` permanece
  válida: `order_book_snapshots`/`agg_trade_buckets` seguem não-usáveis para calibração de
  microestrutura real enquanto isso não for resolvido.

## Sexta rodada: depth-capture convertido para REST mainnet — hoje, sem trocar região

O usuário reclassificou a sondagem de rotas concretas: `data-api.binance.vision` não é
arquivo, é a **API viva** — o mesmo espelho de `api.binance.com`, sem restrição. Já que
respondeu `200` real mesmo em `us-east4` (a região bloqueada), a captura ao vivo de mainnet
não dependia de resolver o bloqueio de região — dependia só de trocar WS por polling REST.
Isso reordenou a fila de novo: converter `depth-capture` virou o item mais urgente da
sessão, à frente até do backfill/benchmark, pela mesma lógica de reversibilidade que já
guiava tudo — depth não tem arquivo histórico (confirmado na rodada anterior), então cada
hora a mais em testnet era perda permanente, e a correção passou a custar "trocar um WS por
um GET a cada 60s", a menor razão esforço/irreversibilidade da sessão inteira.

- **`binance_rest.py`**: base mainnet trocada de `api.binance.com` para
  `data-api.binance.vision`. Confirmado antes por leitura de código que
  `BinanceRestClient` é 100% market data pública (`fetch_klines`, `fetch_agg_trades`,
  `fetch_exchange_info`, `fetch_24h_tickers` — nenhum toca ordem/conta) e só é usado por
  `backtesting/runner.py`; a execução real vive em `execution/client.py::BinanceTestnetClient`,
  classe estruturalmente separada, sem relação com esta. A troca de base é segura para
  os 4 métodos ao mesmo tempo — confirmado que `exchangeInfo`/`ticker/24hr` também
  respondem no host novo, não só `depth`/`aggTrades`/`klines`. Novo método `fetch_depth`.
- **`run_depth_capture.py`**: WS trocado por polling em `fetch_depth` a cada 60s,
  `limit=20` — escolhido deliberadamente para casar com o `@depth20@1000ms` que o WS
  capturava antes (profundidade diferente teria criado uma quebra silenciosa entre as
  duas eras, a mesma armadilha da bucketização discutida para o backfill de aggTrade, só
  que na dimensão errada). `environment="mainnet"` real a partir de agora. Reaproveita
  `compute_snapshot_fields` (já testado) construindo um `MarketEvent` a partir da
  resposta REST — mesmo formato de saída de sempre, só a fonte mudou.
- **`binance_depth_ws.py`/`BinanceDepthStream` não foram apagados** — ficam como caminho
  de fallback, testado e funcional, caso a região migre (Singapura/Holanda já validadas)
  ou caso `data-api.binance.vision` seja um dia descontinuado/limitado. Documentado no
  próprio docstring do módulo por que não está mais em uso.
- **Frescor por `(tabela, environment)`, não por tabela agregada**: com `depth-capture`
  agora mainnet e `aggtrade-capture` ainda testnet, contar "qualquer ambiente" deixaria a
  captura testnet saudável mascarar uma captura mainnet morta na mesma tabela —
  exatamente o tipo de falso-negativo que a asserção de frescor existe para evitar.
  `daily_report.py::CAPTURE_FRESHNESS_TARGETS` fixa o par esperado por tabela agora;
  atualizar essa constante é o único passo quando um serviço muda de ambiente-alvo.
- **`aggtrade-capture` fica para a próxima rodada, por conveniência, não urgência** — o
  arquivo histórico (`data.binance.vision`, confirmado na rodada anterior) cobre o
  atraso, diferente de depth. Antes de converter, medir a taxa real de chegada de trades
  em mainnet: `/api/v3/aggTrades` devolve no máximo 1000 registros/chamada, e o BTCUSDT
  de mainnet pode gerar isso em poucos segundos em horário movimentado — testnet nunca
  exercitou esse volume. Se o polling por `fromId` não acompanhar, atrasa cumulativamente
  e nunca recupera; plano B se não der conta: paralelizar por faixa de id, ou aceitar o
  arquivo como fonte primária e o polling só como cauda recente.
- **Região**: decisão registrada em `06-camada-de-execucao.md`, não executada — Singapura
  tende a ter latência bem menor que Holanda pela proximidade com a infraestrutura da
  Binance (relevante para execução, irrelevante para captura). Prazo da decisão é "antes
  de existir modelo promovível", não "quando existir".

## Pendente

- **`aggtrade-capture` → REST mainnet**, com medição de ritmo antes de assumir que o
  polling acompanha a taxa real de chegada de trades (ver rodada acima).
- **Backfill histórico de aggTrade** (`data.binance.vision`) com bucketização
  compartilhada entre o caminho ao vivo e o de backfill, e teste que passa o mesmo lote
  bruto pelos dois exigindo saída idêntica — evita a quebra silenciosa de regime na
  fronteira entre a era arquivada e a era ao vivo.
- **Região**: escolher e migrar (Singapura ou Holanda) antes de existir modelo
  promovível — decisão do usuário, não urgente hoje.
- Decisão em aberto, não bloqueante: o que fazer com a janela `order_book_snapshots` de
  2026-08-15 a 2026-08-18, toda ela testnet — manter como referência histórica filtrável
  por `ts`/`environment` ou apagar. Fica para quando alguém for de fato consumir esse
  dado.

## Decisão

- Aprovado por: Brian (usuário, dono do projeto) — "Confirmado — pode começar pelo
  aggTrade" / "Toca o aggTrade" (primeira rodada); "push: sim, sem ressalva" / "provisionar
  o aggtrade-capture: sim" condicionado às 4 checagens (segunda rodada); "Isso jumpa a
  fila" — mainnet para as duas capturas + frescor real no relatório diário (terceira
  rodada). O revert para testnet (quarta rodada, achado técnico de bloqueio geográfico) foi
  ação corretiva imediata, não uma decisão de produto — não alterou a direção aprovada,
  só constatou que a infraestrutura atual não a permite ainda. "O próximo é converter o
  depth-capture para REST mainnet, hoje" (sexta rodada, depois da sondagem completa mostrar
  que `data-api.binance.vision` não estava bloqueado). Todas em 2026-08-18.
- Justificativa: reversibilidade de captura de dado como eixo de priorização; as 4
  checagens da segunda rodada são caras de corrigir depois de o serviço já estar
  acumulando dado com o desenho errado (bucket grosso demais, gap silencioso, coletor
  morrendo sem sinal) — mesmo raciocínio de custo-de-correção-retroativa que já guiava a
  decisão original.
