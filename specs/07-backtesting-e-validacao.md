# 07 — Backtesting e Validação

## Objetivo

Garantir que qualquer resultado promissor observado em simulação tenha chance
real de se repetir em produção — o ponto onde a maioria dos projetos de trading
algorítmico falha silenciosamente.

## Requisitos da simulação

1. **Event-driven, não vetorizada.** A simulação processa eventos na ordem
   cronológica exata em que ocorreriam, respeitando a mesma lógica de
   decisão/execução usada em produção — não um cálculo vetorizado sobre a
   série histórica inteira de uma vez, que esconde efeitos de ordem e timing.
2. **Mesmo código de features e de modelo usado em produção** (ver
   `03-motor-de-features.md`) — nunca uma reimplementação separada "só para
   backtest".
3. **Custos realistas incluídos sempre:**
   - Taxas maker/taker da Binance.
   - Slippage (nunca assumir preço de execução perfeito ao preço do sinal).
   - Latência de rede simulada entre sinal e execução.
4. **Validação walk-forward:** treino em uma janela, teste na janela
   imediatamente seguinte (nunca vista no treino), avança a janela, repete.
   Nunca validação cruzada aleatória — vaza informação do futuro para o passado
   e infla resultado de forma enganosa.

## Critérios de promoção de modelo/estratégia

Uma nova versão (de modelo ou de parâmetro de decisão) só é promovida a
candidata de produção se, no backtest out-of-sample walk-forward:

- **Ter expectância líquida positiva por si só** (profit factor ≥ 1, líquido
  de taxas e slippage) — gate absoluto, independente de como o baseline
  performou. "Superar o baseline" não é suficiente sozinho: um candidato
  pode ser "menos ruim" que um baseline com expectância estruturalmente
  quebrada e ainda assim perder dinheiro líquido (ver limitação conhecida
  abaixo, adicionada em 2026-07-31 após achado real nesse sentido). Sem esse
  gate, o critério seguinte (superar o baseline) é necessário mas não
  suficiente.
- Superar a versão em produção nas métricas definidas como primárias (ex.:
  profit factor e drawdown máximo — a lista exata de métricas e limiares é
  definida em `changes/` e versionada).
- Não apresentar degradação de performance concentrada em um único regime de
  mercado (checar performance segmentada por volatilidade/tendência, não só
  agregada).
- Passar por um período mínimo de validação em testnet (ver
  `06-camada-de-execucao.md`) antes de qualquer capital real.

## Sinais de alerta de overfitting (a checar sempre)

- Performance "perfeita" ou muito acima de qualquer baseline simples.
- Sensibilidade alta a pequenas mudanças de hiperparâmetro (indica ajuste ao
  ruído do dataset específico, não a um padrão real).
- Divergência entre performance em backtest e em paper trading/testnet ao
  vivo — quando isso ocorre, a causa é investigada (bug de leakage, mudança de
  regime de mercado, ou diferença sutil entre implementação de backtest e
  produção) antes de qualquer nova promoção.

## Limitação conhecida: baseline placeholder estruturalmente fraco (2026-07-31)

Investigação de um backtest real (`BTCUSDT_1m_7d`, 65 trades, 0% win rate,
100% das saídas via `signal_exit`) confirmou que a regra-placeholder de
`backtesting/strategy.py` (`RsiBollingerPlaceholderStrategy`) **perde
estruturalmente**, não por bug de direção/custo/timing (essas hipóteses
foram checadas e descartadas — ver `changes/2026-07-31-stop-loss-intrabar-backtest-engine.md`
para o único bug real encontrado nessa investigação, que não é a causa
disto). A causa: a saída por "RSI voltou à linha média (50)" fecha a posição
assim que o momentum recupera, o que tipicamente acontece **antes** do preço
se mover o suficiente para cobrir o custo de round-trip (~0.3% = 0.2% de
taxa + ~0.1% de slippage nos dois lados). Reproduzido em 3 janelas históricas
distintas e não sobrepostas (30-37, 60-67 e 90-97 dias atrás): taxa de
acerto líquida entre 0% e 9%, mesmo em uma janela onde o buy-and-hold do
período foi levemente positivo — ou seja, não é característica de um
regime de mercado específico (tendência de baixa), é o próprio desenho da
regra de saída.

**Implicação para `specs/11-roadmap-e-fases.md`, critério de saída da Fase
2:** "superar o baseline ingênuo" é um critério fraco enquanto esse baseline
tiver expectância estruturalmente negativa — um modelo candidato pode vencer
essa régua só por ser "menos ruim", sem ter expectância líquida positiva de
verdade. Ver critério adicional de expectância líquida positiva,
proposto em `changes/2026-07-31-criterio-promocao-expectancia-positiva.md`.

## Métricas obrigatórias no relatório de backtest

- Equity curve completa (não só retorno final).
- Win rate, profit factor, drawdown máximo e duração do drawdown.
- Distribuição de resultados por horário/dia da semana.
- Número de trades (amostra pequena não sustenta conclusão estatística —
  limite mínimo de trades para considerar um resultado significativo é
  definido em `changes/`).

## Relação com o dashboard e o motor de aprendizado

- Todo relatório de backtest gerado (seja de validação de mudança, seja
  automático no ciclo de retreino) é persistido e fica acessível na view
  "Modelo" do dashboard (`08-dashboard-e-visualizacao.md`).
- Divergência entre backtest e produção real é um dos inputs centrais do motor
  de aprendizado contínuo (`09-aprendizado-continuo.md`).
