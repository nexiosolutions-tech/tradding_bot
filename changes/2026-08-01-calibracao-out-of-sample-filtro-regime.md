# Change Proposal — 2026-08-01 — Calibração out-of-sample de `min_trend_pct`

**Status:** aplicada

## Evidência (origem)
- Ligada a: `changes/2026-07-31-filtro-regime-tendencia.md`, que já implementou
  `RegimeFilteredStrategy` mas deixou `min_trend_pct=-0.005` como constante
  fixa, explicitamente marcada como provisória — o valor foi escolhido
  testando 6 candidatos contra os mesmos 5 folds de teste usados para medir
  o resultado (PF médio 0.81). Isso é calibração dentro da amostra, o
  mesmo tipo de risco estatístico já sinalizado pela ressalva de pequena
  amostra em `min_profit_factor`
  (`changes/2026-07-31-criterio-promocao-expectancia-positiva.md`).
- Pedido explícito do usuário para fechar essa dívida antes de seguir para
  os outros itens do dia (importância de features / SHAP e verificação do
  ciclo de aprendizado contínuo com dados reais).

## Proposta
- Nova função `choose_regime_threshold` (`model/strategy.py`): para cada
  fold do walk-forward, faz backtest de cada candidato de `min_trend_pct`
  (`{-0.02, -0.015, -0.01, -0.005, 0.0, +0.005, +0.01}`) só contra a fatia
  de calibração (mesmo intervalo de tempo já usado por `choose_thresholds`
  para `entry_threshold`/`exit_threshold` — nunca o fold de teste) e
  mantém o candidato de melhor profit factor. Se nenhum candidato atingir
  a amostra mínima na fatia de calibração, cai de volta no candidato mais
  permissivo (sem filtro) em vez de aplicar um limiar não validado.
- Ligado em `train_model.py` e `sweep_thresholds.py`, substituindo o valor
  fixo por fold.
- `min_trend_pct` escolhido por fold agora é persistido em
  `metadata.json` do modelo salvo (`model/versioning.save_model`), e
  `execution/bootstrap.load_active_strategy()` devolve esse valor junto
  com a estratégia — `build_orchestrator` usa o `min_trend_pct` real do
  modelo promovido, não mais uma constante global.
- O placeholder da Fase 1 (nunca treinado/calibrado, sem fatia de
  calibração própria) continua usando o fallback fixo
  `PLACEHOLDER_MIN_TREND_PCT = -0.005` — mesmo valor de antes, agora
  nomeado e documentado como o que é: um fallback, não um resultado
  calibrado.
- **Ressalva que permanece**: o modelo é calibrado (`IsotonicRegression`)
  usando os mesmos `calib_rows` que agora também backtestam os candidatos
  de `min_trend_pct` — não é um holdout nunca tocado, é o mesmo nível de
  rigor já aceito para `entry_threshold`/`exit_threshold` neste código,
  não uma garantia mais forte que isso.

## Classificação de risco da mudança
- [x] Mudança de lógica de decisão da estratégia (mesmo processo SDD de
  `changes/2026-07-31-filtro-regime-tendencia.md`, do qual esta é
  continuação direta).
- Não é mudança de parâmetro de risco/execução (`CLAUDE.md` regra 6).
- Nenhum modelo está promovido em produção hoje — a mudança afeta o
  pipeline de treino/avaliação, não a estratégia realmente ativa agora
  (placeholder, que só ganhou um nome explícito para seu fallback já
  existente).

## Validação empírica
- Suíte completa: 165 passed, 1 deselected (rede) — 2 testes novos para
  `choose_regime_threshold`: um constrói uma janela de calibração com
  declínio longo seguido de alta longa (mesmo formato dos folds reais de
  baixa/alta) e confirma que o limiar escolhido supera não filtrar nada
  nessa mesma janela; outro confirma o fallback para o candidato mais
  permissivo quando nenhum candidato atinge a amostra mínima.
- A/B no cache de 90 dias (mesmos 5 folds de
  `changes/2026-07-31-filtro-regime-tendencia.md`, `horizon_minutes=45`,
  `entry_percentile=99`), comparando "sem filtro" vs. "filtro com
  `min_trend_pct` calibrado out-of-sample por fold":

  | | sem filtro | filtro calibrado out-of-sample |
  |---|---|---|
  | PF médio | 0.73 | 0.71 |
  | PF mínimo (pior fold) | 0.20 | 0.19 |
  | folds vencidos | 2/5 | 2/5 |

  **Resultado honesto: o filtro calibrado corretamente fica neutro a
  levemente pior que não filtrar nada** — o PF médio de 0.81 reportado em
  `changes/2026-07-31-filtro-regime-tendencia.md` era artefato de calibrar
  o limiar contra os próprios folds de teste; ao remover esse vazamento, o
  ganho desaparece nesta janela de 90 dias. Isso não invalida o raciocínio
  mecanístico por trás do filtro (a limitação long-only continua real),
  mas mostra que, pelo menos neste recorte de dados, o filtro explícito
  não está adicionando vantagem mensurável além do que o modelo já evita
  sozinho agora que `trend_regime_pct` não é mais input direto dele
  (`changes/2026-07-31-filtro-regime-tendencia.md`). `folds_won`
  permanece 2/5 nos dois casos — nenhuma decisão de promoção muda.
  Mecanismo mantido no pipeline (é a forma estatisticamente correta de
  calibrar, e não piora nada fora do ruído), mas o valor do filtro em si
  fica como questão em aberto para quando houver mais dados/candidatos.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-01
- Justificativa: aprovação explícita em conversa ("vamos começar com o
  tópico de recalibrar o min_trend_pct fora da amostra"), primeiro item da
  lista de próximos passos apresentada e aceita no início do dia.
