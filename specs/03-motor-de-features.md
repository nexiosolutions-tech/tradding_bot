# 03 — Motor de Features

## Objetivo

Transformar o stream de eventos normalizados em vetores de features consumíveis
pelo modelo, de forma incremental (sem recalcular séries inteiras a cada tick) e
determinística (reproduzível em backtesting).

## Requisitos funcionais

1. Indicadores calculados de forma **incremental/rolling**, não recalculados do
   zero a cada novo dado — usar estruturas como `collections.deque` de tamanho
   fixo ou acumuladores incrementais (ex.: EMA já é naturalmente incremental;
   RSI/MACD precisam de implementação incremental própria).
2. Cada feature tem timestamp de "fechamento de conhecimento" igual ao timestamp
   do último evento usado para calculá-la — nunca usa dado futuro relativo ao
   momento da decisão (prevenção de data leakage).
3. O mesmo código de cálculo de features é usado em backtesting e em produção
   (não pode haver duas implementações divergentes — essa é uma das causas mais
   comuns de resultado de backtest não se repetir em produção).

## Features iniciais (MVP)

Indicadores técnicos clássicos como features de entrada do modelo, não como
regras de decisão isoladas:

- Médias móveis (SMA/EMA) em múltiplas janelas
- RSI
- MACD
- Bandas de Bollinger (posição do preço relativa à banda)
- Volume relativo (volume atual vs. média)
- Spread bid-ask e profundidade (quando order book estiver disponível)
- Volatilidade realizada em janela curta
- ATR (Average True Range), normalizado — captura range intrabar (pavios),
  que a volatilidade de close-to-close ignora por completo (2026-07-31)
- Features cíclicas de hora-do-dia e dia-da-semana (`sin`/`cos`), derivadas
  do timestamp de fechamento do candle — sem risco de leakage, já que o
  horário é sempre conhecido de antemão (2026-07-31)
- `trend_regime_pct` — distância do close a uma EMA de período longo (4h),
  proxy de tendência de prazo mais longo que os indicadores de entrada
  (EMA 12/26, MACD) enxergam (2026-07-31, ver seção própria abaixo)

Novas features entram via `changes/` após o motor de aprendizado identificar
sinal de que agregam valor — não são adicionadas ad-hoc sem justificativa
registrada.

### Invariante de escala (2026-07-31)

Toda feature derivada de nível de preço (EMA, MACD, posição de Bollinger)
**deve ser expressa em termos relativos ao close** (percentual), nunca como
preço absoluto. Achado real: `ema_fast`/`ema_slow`/`macd`/`macd_signal`/
`macd_hist`/`bollinger_mid`/`upper`/`lower` eram expostas em escala de preço
absoluto (dezenas de milhares de dólares para BTC) — um modelo treinado
majoritariamente numa janela de preço (ex. BTC a ~$60-70k) tende a ancorar
em níveis absolutos que não se transferem para um regime de preço muito
diferente (~$20k ou ~$100k+). `rsi` (0-100), `bollinger_percent_b` (posição
relativa à banda) e `relative_volume` já eram exemplos corretos desse
princípio — o conjunto de features de nível de preço foi normalizado para
segui-lo (`ema_fast_dist_pct`, `ema_slow_dist_pct`, `ema_cross_pct`,
`macd_pct`, `macd_signal_pct`, `macd_hist_pct`). Ver
`changes/2026-07-31-normalizacao-features-escala-preco.md`. ATR (adicionado
depois) já nasce seguindo essa mesma regra: exposto como `atr_pct` (ATR
dividido pelo close), nunca em valor absoluto.

### Features cíclicas de tempo (2026-07-31)

`hour_sin`/`hour_cos`/`dow_sin`/`dow_cos` são calculadas a partir do
`knowledge_ts` do candle (hora do dia e dia da semana em UTC, codificadas em
seno/cosseno para que o modelo veja um ciclo contínuo — 23h e 00h ficam
próximas no espaço de features, não distantes como um inteiro cru de
hora-do-dia sugeriria). Motivação: os próprios relatórios de backtest já
mostravam `pnl_by_hour`/`pnl_by_weekday` desiguais (mercado cripto tem
padrões conhecidos de volume/volatilidade por sessão) — sem essas features
o modelo não tinha como aprender esse efeito de sessão, só tratá-lo como
ruído. `dow` segue a mesma convenção de `datetime.weekday()` (segunda=0) já
usada em `pnl_by_weekday` (`backtesting/metrics.py`), para os dois ficarem
comparáveis.

### Regime de tendência (2026-07-31)

Investigação da variação de profit factor entre folds do walk-forward
(ver `11-roadmap-e-fases.md`) encontrou correlação clara entre desempenho
do candidato e a direção da tendência de mercado no período: PF médio 1.02
em folds de alta, 0.29 em folds de baixa (BTCUSDT, 90 dias, 5 folds). Faz
sentido mecanicamente — a estratégia é long-only (spot sem margem, ver
`06-camada-de-execucao.md`), sem forma estrutural de se proteger de uma
tendência de baixa.

- `trend_regime_pct = (close - ema_longa) / close`, com `ema_longa` num
  período bem maior (240 candles de 1 minuto = 4h) que as EMAs de entrada
  (12/26 candles) — captura tendência de prazo mais longo que o timing de
  entrada em si não enxerga. Positivo quando o preço está acima da média de
  longo prazo (regime de alta), negativo quando abaixo (regime de baixa).
  Segue a mesma regra de normalização das demais features de nível de
  preço (`Invariante de escala` acima).
- Diferente das demais features desta spec, `trend_regime_pct` **não é
  input do modelo** — `model/dataset.MODEL_FEATURE_NAMES` a exclui
  deliberadamente do que o LightGBM treina, mesmo continuando disponível no
  snapshot. Ela alimenta só um **filtro explícito na camada de decisão**
  (`04-modelo-ml-e-scoring.md`, `RegimeFilteredStrategy`), que suprime
  novas entradas quando o regime detectado é de baixa. Testado
  empiricamente: dar essa feature diretamente ao modelo (em vez de só ao
  filtro) fazia o LightGBM grudar nesse sinal macro lento e disparar
  entradas em excesso e correlacionadas em qualquer período de tendência
  favorável — gatear *quando* operar por ela funciona; deixar o modelo
  tratá-la como só mais um input, não.

### Confluência multi-timeframe (2026-08-12)

Após 10 rodadas de iteração em `11-roadmap-e-fases.md` sem fechar o gap de
promoção, e uma análise de poder estatístico (11ª rodada) que aponta para
um teto real de capacidade preditiva do conjunto de features/arquitetura
atual (não falta de amostra), a próxima alavanca testada é dar ao modelo
contexto de prazos mais longos que o candle de entrada (1 minuto) — a
mesma leitura clássica de "RSI sobrevendido no candle de 1 min **e também**
no candle de 15 min" que um único candle de 1 minuto não consegue
expressar sozinho.

- `rsi_5m`, `rsi_15m`, `bollinger_percent_b_5m`, `bollinger_percent_b_15m`
  — os mesmos indicadores `RSI(14)`/`BollingerBands(20)` já usados na
  escala de 1 minuto, recalculados sobre candles sintéticos de 5 e 15
  minutos, construídos agregando os candles de 1 minuto que chegam
  (`features/engine.py::_TimeframeAggregator`).
- **Invariante de anti-vazamento, reforçado aqui deliberadamente**: o
  valor de um candle de 5/15 minutos só é considerado "fechado" (e só
  então alimenta o RSI/Bollinger daquele timeframe) no instante em que o
  primeiro candle de 1 minuto do bucket **seguinte** chega — nunca durante
  a formação do próprio bucket. Na prática, isso significa que o valor de
  `rsi_5m` exposto num dado candle de 1 minuto é sempre o do último candle
  de 5 minutos já fechado, podendo estar "atrasado" em até quase 5 (ou 15)
  minutos em relação ao candle atual — exatamente como um trader real só
  sabe o fechamento de um candle de 15 minutos quando ele de fato fecha,
  nunca antes.
- Escopo deliberadamente contido: só RSI e Bollinger %B (não todo o
  conjunto de 15 features original) em cada timeframe extra — evita
  triplicar a dimensionalidade do vetor de features de uma vez, o que
  arriscaria diluir ainda mais o sinal que o modelo já tem dificuldade de
  extrair (achado do SHAP, 8ª rodada: mais features nem sempre ajuda,
  `atr_pct` já dominava a decisão sozinho).
- Aumenta o warm-up necessário: `rsi_15m` só fica disponível depois de 14
  candles de 15 minutos fechados (210 minutos), `bollinger_percent_b_15m`
  depois de 20 (300 minutos) — o maior warm-up entre todas as features
  hoje (era `trend_regime_pct`, sem warm-up, e `atr_pct`, 14 minutos).
- Resultado empírico: ver `11-roadmap-e-fases.md` (12ª rodada) — inconclusivo
  (`folds_won=0/5` com e sem as features novas, mesma janela de 90 dias),
  mantido no pipeline por motivação mecanística e ausência de piora além do
  ruído já observado entre janelas.

### Order book (captura iniciada em 2026-08-15, sem features ainda)

Resposta à limitação identificada nas 9ª-12ª rodadas (`11-roadmap-e-fases.md`):
todo o conjunto de features até aqui deriva só do preço/volume da própria
série OHLCV da BTCUSDT — indicadores técnicos clássicos, públicos e bem
conhecidos, com pouco sinal direcional líquido de custo demonstrado depois
de 4 rodadas seguidas de iteração. Order book (spread, profundidade,
desequilíbrio bid/ask) é a primeira fonte de informação que não é uma
transformação do mesmo preço de fechamento.

- **Captura, não features**: `02-ingestao-de-dados.md` descreve a captura
  (`scripts/run_depth_capture.py`, 1 snapshot/minuto, tabela
  `order_book_snapshots`). Esta seção existe só para registrar a intenção
  e evitar que a tabela pareça órfã — nenhuma feature nova entra em
  `FEATURE_NAMES` nesta rodada.
- **Por que não implementar a feature já**: diferente de toda mudança
  anterior deste arquivo, aqui não há histórico para validar contra
  (`02-ingestao-de-dados.md` — Binance não expõe order book retroativo).
  Escrever a feature agora seria código sem forma de validação empírica
  até acumular dado suficiente — foge do padrão que este projeto seguiu
  em todas as rodadas anteriores (nunca adotar sem validação real).
- **Candidatas prováveis, a confirmar quando houver dado**: `spread_pct`
  (`(best_ask - best_bid) / best_bid`), `order_book_imbalance`
  (desequilíbrio de profundidade entre os 20 melhores níveis de bid e
  ask) — ambas já pré-computadas e persistidas em
  `order_book_snapshots` junto com os níveis brutos, para não precisar
  reprocessar o bruto quando chegar a hora de desenhar a feature de
  verdade.
- Próximo passo (não desta rodada): quando houver histórico suficiente
  (a definir — provavelmente algumas semanas), desenhar e validar a
  feature contra um backtest real, seguindo o mesmo processo das rodadas
  anteriores (`evaluate_config`, ablação controlada).

## Feature store

- Toda feature calculada em produção é persistida junto com o timestamp e o
  símbolo, para permitir:
  - Auditoria: reconstruir exatamente o que o modelo "viu" em qualquer decisão
    passada.
  - Retreino: gerar datasets de treino a partir de dados de produção real, não
    só de backfill histórico.

## Invariantes

- Cálculo determinístico: dado o mesmo histórico de eventos, o motor sempre
  produz o mesmo vetor de features (requisito para backtesting confiável).
- Nenhuma feature pode depender de informação com timestamp posterior ao
  timestamp da decisão que a consome.

## Fora de escopo no MVP

- Features de dados alternativos (notícias, redes sociais).
- Feature store distribuído/dedicado (ex.: Feast) — MVP usa a mesma
  persistência do restante do sistema (`10-stack-tecnica-e-dependencias.md`).
