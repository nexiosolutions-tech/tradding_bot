# 12 — Triagem e Descoberta de Moedas (Coin Screening)

## Objetivo

Ferramenta de pesquisa, só leitura, para avaliar empiricamente se outras
moedas negociadas na Binance (além de BTCUSDT) têm sinal explorável pela
mesma arquitetura já validada — sem tocar em execução, risco ou capital
real.

Resposta direta a um pedido do usuário de expandir para uma arquitetura
multi-ativos (RL, Kafka, TimescaleDB, microsserviços, motor de descoberta
em tempo real). Decomposto deliberadamente no menor passo possível,
seguindo o mesmo método já usado em todas as rodadas de
`11-roadmap-e-fases.md` (spec pequena → validação empírica contra dado
real → decidir), em vez de um redesenho completo de arquitetura antes de
haver qualquer evidência de que compensa. Ver
`changes/2026-08-15-triagem-de-moedas.md` para o raciocínio completo dessa
decisão de escopo.

## Fora de escopo (deliberado)

- **Não executa ordens, não importa `tradingbot.execution`, não precisa de
  `BINANCE_API_KEY`/`SECRET`** — mesmo isolamento já usado pelo loop de
  aprendizado (`09-aprendizado-continuo.md`) e pela captura de order book
  (`02-ingestao-de-dados.md`).
- **Não promove uma moeda para operação ao vivo automaticamente.** Um
  resultado bom aqui é insumo para uma decisão humana — passar a operar
  uma moeda nova em `06-camada-de-execucao.md` exige seu próprio ciclo
  `changes/` → aprovação humana explícita → spec atualizada, igual a
  qualquer mudança de risco/execução (`CLAUDE.md`, regra 6).
- **Não é infraestrutura nova.** Sem Kafka, sem TimescaleDB, sem RL, sem
  microsserviço novo — reaproveita `BinanceRestClient` e
  `model/evaluation.py::evaluate_config` já existentes, mesmo processo
  Python, mesmo Postgres. Rodado sob demanda (como `sweep_thresholds.py`),
  não como serviço contínuo.
- **A ambição de longo prazo de um bot realmente multi-moedas fica
  registrada aqui como direção futura, não como esta rodada.** Só faz
  sentido revisitar depois que, no mínimo: (a) algum modelo vencer o gate
  de promoção (`folds_won=5/5`) pelo menos uma vez em BTCUSDT — ainda não
  aconteceu em 12 rodadas (`11-roadmap-e-fases.md`) — e (b) este próprio
  módulo mostrar diferença de sinal real entre moedas que justifique a
  complexidade adicional. Nenhuma das duas condições está satisfeita hoje.

## Universo negociável (filtro determinístico, não é scoring)

1. `GET /api/v3/exchangeInfo` — símbolos com `status=TRADING`,
   `quoteAsset=USDT`, `isSpotTradingAllowed=true`. `USDT` fixo (não
   configurável nesta rodada) — consistente com o resto do sistema, evita
   lógica de conversão entre moedas de cotação.
2. Exclui tokens alavancados (sufixo `UP`/`DOWN`/`BULL`/`BEAR` no
   `baseAsset`) — instrumentos com decaimento estrutural por design, não
   comparáveis à arquitetura atual (spot, sem margem — `06-camada-de-execucao.md`).
   Exclui também stablecoins (`USDC`, `FDUSD`, `TUSD`, `DAI`, `USDP`,
   `BUSD`, `EUR`, `GBP`, `AEUR` como `baseAsset`) — achado empírico ao
   rodar o script pela primeira vez: `USDCUSDT` passava em todos os outros
   filtros e ficava #1 em volume (par contra stablecoin tem volume nominal
   enorme), gastando um backtest walk-forward inteiro num par com
   volatilidade ~zero por construção. Não há flag limpa da API da Binance
   para "é stablecoin" — lista curada, mesmo padrão dos tokens alavancados.
3. `GET /api/v3/ticker/24hr` sem símbolo (devolve o universo inteiro numa
   chamada só) — filtra por `quoteVolume` mínimo (piso de liquidez) e
   `lastPrice` mínimo (evita moedas de preço unitário extremo, risco de
   erro de precisão/step size na Binance).
4. Limiares (`min_quote_volume_24h`, `min_price`) são parâmetros do
   script, sem default "mágico" pré-decidido — a calibrar na primeira
   rodada real contra dado de verdade, não adivinhados nesta spec.

## Correlação com BTC (contexto para decisão, não filtro automático)

- Para cada candidato que passa o filtro de universo: retorno percentual
  candle-a-candle (mesma janela do backtest) correlacionado (Pearson) com
  o retorno de BTCUSDT no mesmo período.
- **Não exclui candidatos automaticamente nesta rodada** — é reportado
  junto ao ranking para decisão humana. Moedas com correlação alta (>0.8,
  valor a calibrar) tendem a herdar a mesma limitação já documentada de
  BTCUSDT (estratégia long-only, sem proteção estrutural contra tendência
  de baixa — `03-motor-de-features.md`, seção "Regime de tendência") sem
  adicionar diversificação real.

## Ranking por backtest (reaproveita o pipeline já validado, não cria um novo)

- Para cada candidato: `model/evaluation.py::evaluate_config` com **a
  mesma config de referência já validada para BTCUSDT**
  (`horizon_minutes=45`, `entry_percentile=99`, sem filtro de regime —
  `11-roadmap-e-fases.md`, 9ª/10ª rodadas), sobre klines reais buscados
  via `BinanceRestClient.fetch_klines`.
- Métrica de ranking: `folds_won` primeiro (o mesmo critério do gate de
  promoção real, `07-backtesting-e-validacao.md`), `mean_profit_factor`
  como desempate. Nenhum modelo de scoring/ML novo para isso — seria
  abstração especulativa sobre um problema que ainda não confirmamos que
  existe (`CLAUDE.md`).
- Saída: tabela ordenada (símbolo, volume 24h, correlação com BTC,
  `folds_won`, `mean_pf`, `min_pf`, `label_rate`), impressa pelo script —
  mesmo padrão de `sweep_thresholds.py`. Sem tabela nova no Postgres: é
  pesquisa pontual, não pipeline de produção.

## Invariantes

- Determinístico dado o mesmo histórico (mesma garantia de
  `03-motor-de-features.md`/`07-backtesting-e-validacao.md`).
- Nunca lê nem escreve estado de execução (posições, ordens, risco) — só
  dado histórico de mercado, via REST.
- `evaluate_config` é a mesma função usada pelo gate de promoção real
  (`07-backtesting-e-validacao.md`) — sem lógica de scoring paralela e
  potencialmente divergente.

## Próximo passo (fora desta rodada)

Se algum candidato bater `folds_won=5/5` — o que nenhum símbolo, incluindo
BTCUSDT, jamais bateu até aqui (`11-roadmap-e-fases.md`) — decidir com o
usuário se promove esse par para operação ao vivo. Isso segue o mesmo
processo de `CLAUDE.md` regra 6/7 (`changes/` → aprovação humana explícita
→ `06-camada-de-execucao.md` atualizada), nunca automático a partir do
resultado deste módulo.
