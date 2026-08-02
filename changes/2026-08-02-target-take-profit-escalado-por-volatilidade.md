# Change Proposal — 2026-08-02 — Take-profit escalado por volatilidade (não adotado)

**Status:** aplicada

## Evidência (origem)
- Ligada a: `changes/` (implicitamente, 8ª rodada de `specs/11`) — análise de
  importância de features via SHAP encontrou `atr_pct` (volatilidade
  recente) dominando a decisão do modelo, mais que o dobro de importância
  de qualquer outra feature, correlação de +0.91. Explicação mecanística:
  com `move_threshold_pct`/`stop_loss_pct` fixos (0.8%/1.5%), volatilidade
  mais alta favorece estatisticamente acertar o take-profit primeiro (mais
  perto) mesmo sem habilidade direcional real.
- Pedido explícito do usuário para atacar esse achado como prioridade
  ("vamos pelo item 1"), entre as opções apresentadas para trabalho em
  paralelo enquanto o engine roda sem interrupção por uma semana.

## Proposta
- `TargetConfig.move_threshold_atr_multiple: float | None` (novo,
  `model/dataset.py`) — quando definido, o take-profit vira esse múltiplo do
  `atr_pct` da barra de entrada em vez do `move_threshold_pct` fixo. `None`
  (default) preserva o comportamento anterior — aditivo, não destrutivo.
  `stop_loss_pct` deliberadamente **não muda** — continua fixo em 1.5%, o
  mesmo valor da execução real (`06-camada-de-execucao.md`); esta proposta
  não é mudança de parâmetro de risco/execução (`CLAUDE.md` regra 6 não se
  aplica), só de definição de label de treino (regra 7: mudança de
  arquitetura/target, processo SDD completo).
- `model/evaluation.py::evaluate_config` e `model/importance.py::compute_feature_importance`
  estendidos com o mesmo parâmetro, para permitir comparação empírica e para
  ficar disponível como ferramenta do loop agêntico (specs/09).

## Classificação de risco da mudança
- [x] Mudança de arquitetura/target do modelo (requer processo SDD completo).
- Não é mudança de parâmetro de risco/execução — `stop_loss_pct` real
  intocado.
- Sem push para produção nesta rodada, por pedido explícito do usuário
  (engine rodando sem interrupção por uma semana para acumular histórico).

## Validação proposta e resultado
A/B no cache de 90 dias (`horizon_minutes=45`, `entry_percentile=99`,
`n_splits=5`, sem filtro de regime para isolar o efeito do target), `k` em
`{8, 10, 12, 15, 18, 22}` (`k≈15` reproduz a distância média atual na
volatilidade típica do cache):

- **Baseline** (`move_threshold_pct=0.008` fixo): PF por fold
  `[1.54, 0.38, 1.03, 0.50, 0.20]`, mean 0.73, min 0.20, `folds_won=2/5`.
- **Nenhum candidato bateu o baseline** em `folds_won` (todos ficaram em
  0/5 ou 1/5) nem em PF mínimo (nenhum passou de 0.15). Melhor `mean_pf`
  entre os candidatos: `k=12` com mean 0.96, mas `min_pf=0.07` e só 1/5
  folds vencidos — amostra pior, não modelo melhor.
- **Verificação mecanística (o que a proposta realmente testava)**: SHAP
  recalculado com `k=12` mostra `atr_pct` caindo de \|SHAP\| médio 1.45 para
  0.53, com a correlação de direção **invertendo de sinal** (+0.89 → -0.83)
  — confirma que o atalho de assimetria de barreiras fixas foi neutralizado
  como pretendido.
- **Conclusão honesta**: a correção resolveu exatamente o problema
  mecanístico identificado pelo SHAP, mas isso não se traduziu em modelo
  melhor — o profit factor piorou. O modelo trocou um atalho de volatilidade
  por outro (agora com sinal invertido), sem sinal direcional genuíno
  suficiente para preencher a lacuna. Evidência a mais de que este
  par/timeframe/conjunto de features pode não ter sinal direcional
  explorável suficiente com a arquitetura atual.
- Suíte completa sem regressão — ver commit desta data.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-02
- Justificativa: aprovação explícita para investigar o item ("vamos pelo
  item 1"). Resultado negativo/neutro reportado com transparência total —
  a funcionalidade fica no código (aditiva, não é o default) como
  ferramenta de investigação futura, mas **não é adotada** como
  configuração de treino padrão. Não altera nada em produção.
