# Change Proposal — 2026-07-31 — Critério de promoção não exige expectância líquida positiva do próprio candidato

**Status:** aplicada

## Evidência (origem)
- Ligada a: investigação do usuário sobre o backtest `BTCUSDT_1m_7d`, que
  revelou que o baseline placeholder (`RsiBollingerPlaceholderStrategy`) tem
  expectância estruturalmente negativa (taxa de acerto líquida entre 0% e 9%
  em três janelas históricas distintas — ver
  `07-backtesting-e-validacao.md`, seção "Limitação conhecida").
- `model/promotion.py` (`evaluate_fold`) só comparava o candidato **contra o
  baseline**: `candidate_metrics.profit_factor <= baseline_metrics.profit_factor
  + min_profit_factor_improvement`. Nunca checava se o profit factor do
  próprio candidato era maior que 1 (ou seja, se ele próprio tinha
  expectância líquida positiva).
- Consequência prática: com um baseline estruturalmente quebrado (profit
  factor bem abaixo de 1, às vezes 0.0 quando nunca vence nenhum trade), um
  candidato só precisa ser "menos ruim" — pode ter profit factor 0.5, 0.7,
  continuar perdendo dinheiro líquido, e ainda assim "vencer" o critério de
  promoção hoje existente. Isso tornaria "superar o baseline" um critério
  fraco o suficiente para promover um modelo genuinamente não-lucrativo.

## Proposta
- `PromotionCriteria` ganha um novo campo `min_profit_factor: float = 1.0`.
- `evaluate_fold` ganha um novo gate **absoluto**, independente da comparação
  com o baseline: se `candidate_metrics.profit_factor < criteria.min_profit_factor`,
  o fold é rejeitado com motivo explícito ("expectância líquida do candidato
  não é positiva... não basta ser 'menos ruim' que o baseline"), antes mesmo
  de comparar com o baseline.
- **O que não muda:** os critérios já existentes (superar o baseline,
  não degradar em regime único, drawdown) continuam exatamente como estavam
  — este é um gate adicional, não uma substituição. `decide_promotion`
  (exigir vitória em todos os folds) também não muda.

## Classificação de risco da mudança
- [x] Mudança de arquitetura/target do modelo (requer processo SDD completo)
  — altera o critério objetivo de promoção definido em
  `07-backtesting-e-validacao.md`, que rege quando um modelo pode ser
  considerado candidato a produção.

## Validação proposta
- Teste com uma estratégia real (não stub) que produz um trade set
  parcialmente vencedor mas com profit factor < 1 (perdedor líquido) contra
  um baseline que nunca opera (profit factor 0.0 por construção) — confirma
  que o novo gate rejeita mesmo quando o candidato "venceria" a comparação
  relativa antiga.
- Suíte completa de `model/promotion.py` sem regressão nos testes
  existentes (que já cobriam amostra insuficiente, drawdown pior que
  baseline, e promoção legítima).

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-07-31
- Justificativa: aprovação explícita em conversa ("4. Proposta adicional em
  changes/: reforçar o critério de promoção de
  07-backtesting-e-validacao.md para exigir também expectância líquida
  positiva..."), após investigação do bug do backtest de BTCUSDT_1m_7d que
  revelou a fraqueza do baseline placeholder.
