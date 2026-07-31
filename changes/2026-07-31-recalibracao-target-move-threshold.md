# Change Proposal — 2026-07-31 — Alvo de lucro do label no breakeven exato do custo de round-trip

**Status:** aplicada

## Evidência (origem)
- Ligada a: revisão de features/target da Fase 2, feita a pedido do usuário
  após a base de backtest/promoção passar a significar algo real.
- `model/dataset.py` (`TargetConfig.move_threshold_pct`, default 0.003 =
  0.3%) estava **exatamente no breakeven do custo de round-trip** (~0.2% de
  taxa Binance + ~0.1% de slippage, achado direto da investigação do
  backtest de `BTCUSDT_1m_7d` em `changes/2026-07-31-stop-loss-intrabar-backtest-engine.md`).
  Um `label=1` ("oportunidade") mal cobria os custos de execução — lucro
  líquido perto de zero mesmo quando o modelo acerta a direção.
- Combinado com `stop_loss_pct=0.015` (1.5%, 5x maior), a razão
  risco:retorno de 1:5 exigiria taxa de acerto bruta de ~83% só para
  empatar — uma barra alta demais mesmo para um modelo genuinamente
  preditivo, tornando o alvo de treino pouco útil na prática independente da
  qualidade do modelo.

## Proposta
- `TargetConfig.move_threshold_pct`: 0.003 → **0.008** (0.8%, ~2.7x o custo
  de round-trip) — um `label=1` passa a representar uma margem líquida real
  depois de custos, não um empate contábil.
- CLI de `scripts/train_model.py` (`--move-threshold-pct`) atualizado para o
  mesmo default, por consistência.
- **O que este ajuste explicitamente NÃO faz:** não altera `stop_loss_pct`
  (permanece 1.5%) — esse é parâmetro de risco/execução real usado pela
  camada de execução (`05-gestao-de-risco.md`/`06-camada-de-execucao.md`),
  fora do escopo desta mudança, que é só sobre o alvo de lucro usado para
  *rotular* o dataset de treino. Com o ajuste, a razão risco:retorno passa
  de 1:5 para ~1.875:1 (taxa de acerto de breakeven ~65% em vez de ~83%),
  mas segue sendo uma decisão sobre o *label*, não sobre o *stop real*. Se a
  validação empírica ainda indicar necessidade de estreitar mais essa razão
  via mudança no `stop_loss_pct` em si, isso é proposta separada,
  explicitamente classificada como parâmetro de risco (`CLAUDE.md` regra 6).
- **Isto é mudança de target do modelo (`CLAUDE.md` regra 7), não retreino**
  — `specs/04-modelo-ml-e-scoring.md` foi atualizada antes do código,
  descrevendo a calibração como parte do contrato do label.

## Classificação de risco da mudança
- [x] Mudança de arquitetura/target do modelo (requer processo SDD completo)

## Validação proposta
- Suíte completa sem regressão (testes existentes já passam
  `move_threshold_pct` explicitamente, não dependem do default).
- Validação empírica: re-rodar walk-forward/promoção com o novo target
  (junto com a normalização de features da entrada separada em
  `changes/2026-07-31-normalizacao-features-escala-preco.md`) e comparar
  contra o critério de promoção de `07-backtesting-e-validacao.md` —
  incluindo checar a taxa de `label=1` resultante (amostra ainda viável?) e
  se a razão risco:retorno recalibrada aproxima o candidato do critério de
  expectância líquida positiva.
- Modelo treinado com o critério antigo precisa ser re-treinado do zero (não
  há nenhum modelo promovido em produção ainda, então não há migração a
  fazer) e só promovido se bater os critérios de
  `specs/07-backtesting-e-validacao.md` em backtest out-of-sample.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-07-31
- Justificativa: aprovação explícita em conversa ("vamos atuar na 1 e 2
  juntas"), após apresentação da lista priorizada de hipóteses de
  feature/target da Fase 2.
