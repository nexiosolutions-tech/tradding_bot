# Change Proposal — 2026-08-15 — Triagem e ranking de moedas (ferramenta de pesquisa, sem execução)

**Status:** aplicada

## Evidência (origem)
- Pedido do usuário para elaborar um System Design Document completo de
  arquitetura multi-ativos escalável (RL, Kafka, TimescaleDB,
  microsserviços, motor de descoberta em tempo real).
- Avaliação honesta antes de aceitar o pedido como está: nenhum modelo de
  ML foi promovido em nenhum par até hoje (`folds_won` nunca 5/5 em 12
  rodadas, `11-roadmap-e-fases.md`), a estratégia que roda ao vivo tem
  expectância líquida negativa confirmada (~1% win rate líquido em 75
  trades reais), e a captura de order book começou no mesmo dia, sem
  nenhuma validação empírica ainda. Uma arquitetura distribuída
  multi-ativos com RL nesse momento aumentaria risco e complexidade sem
  nenhuma evidência de que o problema central (sinal insuficiente) esteja
  resolvido — e RL especificamente é uma categoria de risco mais difícil
  de auditar/limitar que o classificador supervisionado + regras fixas já
  em uso (`CLAUDE.md`, regras 2/4/5).
- Recomendação alternativa apresentada ao usuário e aprovada: decompor no
  menor passo possível, seguindo o método já validado nas 12 rodadas
  (spec pequena → validação empírica real → decidir), começando por uma
  ferramenta de pesquisa só-leitura.

## Proposta
- `specs/12-triagem-e-descoberta-de-moedas.md` (nova) — contrato completo
  do módulo.
- `BinanceRestClient.fetch_exchange_info()`/`fetch_24h_tickers()` —
  universo negociável e volume/preço 24h.
- `screening/discovery.py` (novo) — `filter_candidate_universe`,
  `compute_correlation`, `rank_candidates`, puro e testável sem rede.
- `scripts/run_coin_discovery.py` — orquestra: universo → filtro → top N
  por volume → `evaluate_config` (mesma config de referência de
  BTCUSDT) por candidato → correlação com BTC → tabela ordenada.
- **O que não muda**: nenhuma mudança em `execution/`, `risk/`, nenhuma
  credencial nova, nenhuma promoção automática de par para operação ao
  vivo, nenhuma infraestrutura nova (sem Kafka/TimescaleDB/RL/microsserviço).

## Classificação de risco da mudança
- [ ] Não é mudança de parâmetro de risco/execução nem de arquitetura do
  modelo em produção — é uma ferramenta de pesquisa nova, só leitura,
  isolada de `tradingbot.execution` (mesmo padrão de specs/02/09).
- Resultado de um candidato bem avaliado aqui **não** promove
  automaticamente nada — continua exigindo seu próprio ciclo `changes/`
  + aprovação humana antes de qualquer capital real (`CLAUDE.md` regra 6).

## Validação
- Smoke test real contra a Binance (`--days 2 --top-by-volume 3
  --n-splits 2 --min-trades 3`): universo/filtro/klines/backtest/ranking
  funcionando ponta a ponta.
- **Achado durante o smoke test**: `USDCUSDT` (par stablecoin-stablecoin)
  passava em todos os filtros e ficava #1 em volume, gastando um
  backtest inteiro num par com volatilidade ~zero por construção — sem
  flag limpa da API da Binance para "é stablecoin". Corrigido com lista
  curada de exclusão (`STABLECOIN_BASE_ASSETS`, mesmo padrão dos tokens
  alavancados), documentado em specs/12. Confirmado que some da lista
  após o fix.
- 233 testes passando (18 novos: filtro de universo, correlação, ranking,
  exchangeInfo/ticker 24h).

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-15
- Justificativa: aprovação explícita da recomendação de escopo reduzido
  ("Gostei e aprovo a sua recomendação"). O desejo de longo prazo de um
  bot multi-moedas fica registrado em specs/12 como direção futura,
  condicionada a (a) algum modelo vencer o gate de promoção pelo menos
  uma vez em BTCUSDT e (b) este módulo mostrar diferença de sinal real
  entre moedas — nenhuma das duas condições satisfeita hoje.
