# Change Proposal — 2026-07-30 — Label do modelo ignora stop-loss (só olha máxima futura)

**Status:** aplicada

## Evidência (origem)
- Ligada a: auditoria técnica completa de 30/07/2026.
- `model/dataset.py` (`build_dataset`) rotula cada linha como "oportunidade"
  (`label=1`) se a máxima futura dentro do horizonte atinge o alvo de lucro —
  mas nunca verifica se a mínima futura teria acionado um stop-loss *antes*
  disso. Confirmado por leitura direta: só existe `future_highs`, não há
  `future_lows` em nenhum lugar do arquivo.
- Consequência: o modelo aprende a reconhecer padrões que "eventualmente"
  teriam alcançado o alvo, mesmo em casos onde o preço teria caído e disparado
  o stop-loss primeiro. O modelo está sendo treinado para um mundo sem
  stop-loss, mas opera em um sistema que sempre tem stop-loss (regra 2 do
  CLAUDE.md) — a definição do target não corresponde a como a estratégia
  realmente é executada.

## Proposta
- Trocar o critério de rotulagem pelo método de "tripla barreira": dentro do
  horizonte (`horizon_bars`), percorrer candle a candle e checar qual barreira
  é tocada primeiro — take-profit (`move_threshold_pct` acima do close),
  stop-loss (`stop_loss_pct` abaixo do close) ou fim do horizonte sem tocar
  nenhuma. `label=1` só se o take-profit for tocado *antes* do stop-loss.
- `TargetConfig` ganha um novo campo obrigatório `stop_loss_pct`, com o mesmo
  valor já usado em produção (`STOP_LOSS_PCT = 0.015` em `train_model.py`), de
  forma que o modelo aprenda contra o stop-loss que realmente será usado.
- **Isto é mudança de target do modelo, não retreino** (regra 7 do CLAUDE.md)
  — a definição do que está sendo predito muda, não só os pesos. Por isso
  `specs/04-modelo-ml-e-scoring.md` precisa ser atualizada primeiro,
  descrevendo o critério de tripla barreira como o contrato do label, antes
  do código ser alterado.
- Modelos já treinados com o critério antigo precisam ser re-treinados do
  zero (não é um fine-tune) e só promovidos a produção se baterem o critério
  de `specs/07-backtesting-e-validacao.md` em backtest out-of-sample — nenhuma
  promoção automática pula essa validação.
- **O que não muda:** o pipeline de features, o modelo (LightGBM) em si, e o
  processo de promoção/backtest — só a definição do que é "1" e "0" no
  dataset de treino.

## Classificação de risco da mudança
- [x] Mudança de arquitetura/target do modelo (requer processo SDD completo)

## Validação proposta
- Atualizar `specs/04-modelo-ml-e-scoring.md` descrevendo o critério de tripla
  barreira como contrato (evento tocado primeiro, não "eventualmente
  alcançado").
- Teste unitário com uma série sintética onde a mínima futura fura o
  stop-loss antes da máxima futura alcançar o alvo — confirmar `label=0`
  (hoje seria incorretamente `label=1`).
- Teste unitário com o inverso (alvo tocado antes do stop) confirmando
  `label=1`, e um caso onde nenhuma barreira é tocada confirmando `label=0`.
- Re-treinar o modelo com o novo critério e rodar o backtest completo de
  `specs/07` antes de qualquer promoção — novo modelo só substitui o atual em
  produção se bater os critérios de promoção definidos lá.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-07-30
- Justificativa: aprovação explícita em conversa ("Pode redigir e implementar
  as entradas de changes/"), após revisão do achado da auditoria técnica.
  Aprovação cobre a mudança de código e de spec; NÃO cobre promoção de um
  modelo re-treinado para produção sem passar pelo critério de backtest de
  specs/07 — essa etapa permanece sujeita ao processo normal, não a esta
  aprovação genérica.
