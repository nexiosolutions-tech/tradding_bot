# Change Proposal — 2026-07-31 — Peso de classe (scale_pos_weight) e seed fixa no treino

**Status:** aplicada

## Evidência (origem)
- Ligada a: revisão geral da Fase 2 e lista de próximos passos, item "peso
  de classe" (aprovado explicitamente em conversa: "Podemos prosseguir").
- `label=1` observado entre 0.5% e 6.1% das linhas dependendo do horizonte
  (sweeps de hoje) — desbalanceamento real que o `LGBMClassifier` não
  compensava (sem `scale_pos_weight`/`class_weight`), podendo otimizar a
  perda de treino simplesmente prevendo a classe majoritária na maior parte
  do tempo, exatamente o modo de falha que um alvo de "oportunidade rara"
  convida.
- Ao validar o efeito, percebido que o treino não tinha `random_state` fixo
  — duas rodadas do mesmo `ModelConfig` podiam produzir scores diferentes
  só por aleatoriedade interna do LightGBM (bagging/subsample de features),
  o que tornava qualquer comparação "configuração A vs. B" potencialmente
  contaminada por ruído de execução, não diferença real de configuração.

## Proposta
- `ModelConfig` ganha `balance_classes: bool = True` (default ligado) e
  `random_state: int = 42`.
- `train_model` calcula `scale_pos_weight = n_negativos/n_positivos` a
  partir do próprio `fit_rows` de cada fold quando `balance_classes=True`;
  passa `1.0` (sem efeito) quando desligado ou se não houver positivos.
- `random_state` é repassado ao `LGBMClassifier`, tornando o treino
  determinístico dado o mesmo `ModelConfig`/dados.
- **O que não muda:** arquitetura do modelo (LightGBM), target/label,
  pipeline de calibração isotônica — é ajuste de hiperparâmetro de treino
  dentro do mesmo espaço, não mudança de arquitetura/target (`CLAUDE.md`
  regra 7 — pode seguir critério de promoção automática de
  `07-backtesting-e-validacao.md`).

## Classificação de risco da mudança
- [x] Retreino de modelo dentro do mesmo espaço de hiperparâmetros/target
      (pode seguir critério de promoção automática de specs/07)

## Validação proposta
- Testes unitários: `scale_pos_weight` calculado corretamente a partir do
  desbalanceamento real quando ligado, neutro (1.0) quando desligado;
  determinismo (duas rodadas do mesmo config produzem os mesmos scores).
- Validação empírica: comparação controlada (mesma seed, mesmos folds) com
  e sem balanceamento no melhor ponto já encontrado (90 dias, BTCUSDT 1m,
  `horizon_minutes=45`, `entry_percentile=99`):
  - Sem balanceamento: PF por fold = [0.61, 0.23, 0.66, 0.40, 0.15], média 0.41.
  - Com balanceamento: PF por fold = [1.54, 0.38, 1.03, 0.50, 0.20], média 0.73.
  - **Todos os 5 folds melhoraram**, não só a média — primeiro sinal
    consistente (não isolado/ruidoso) desde o início desta investigação.
    Um fold (o primeiro, cronologicamente) chegou a **PF=1.54, acima do
    gate de promoção pela primeira vez** — ainda assim `folds_won=0/5`,
    porque a promoção exige vitória em **todos** os folds, não só um bom
    resultado isolado (o sistema de promoção funcionando como deveria).
- Suíte completa sem regressão (150 testes).

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-07-31
- Justificativa: aprovação explícita em conversa ("Podemos prosseguir"),
  item da lista de próximos passos sugerida após a revisão geral do
  projeto.
