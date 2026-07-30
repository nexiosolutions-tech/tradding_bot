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
