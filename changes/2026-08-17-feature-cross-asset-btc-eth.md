# Change Proposal — 2026-08-17 — Feature cross-asset: força relativa BTC vs. ETH

**Status:** aplicada

## Evidência (origem)
- Sugestão do usuário, aceita como item 1 de um plano de evolução mais
  amplo ("features cross-asset — testável hoje, sem esperar nada"),
  depois de 13 rodadas variando só preço/volume/risco da própria
  BTCUSDT sem fechar o gap de promoção (`11-roadmap-e-fases.md`).

## Proposta
- `features/indicators.py::ReturnOverWindow` — retorno percentual sobre
  janela fixa, bloco reusável para os dois ativos.
- `features/engine.py::FeatureEngine` ganha `reference_symbol` opcional
  — eventos desse símbolo atualizam um rastreador de retorno mas nunca
  geram `FeatureSnapshot` próprio. `eth_relative_strength_pct =
  retorno_btc_15m − retorno_eth_15m`.
- `model/dataset.py::build_dataset` ganha `required_features`/
  `reference_symbol` opcionais (default preserva comportamento de
  sempre) e `CROSS_ASSET_FEATURE_NAMES`/`MODEL_CROSS_ASSET_FEATURE_NAMES`.
- `model/evaluation.py::evaluate_config` ganha `feature_names`/
  `reference_symbol`, threaded até `build_dataset` **e** até
  `evaluate_fold`/`choose_regime_threshold` (ver bug abaixo).
- `scripts/run_cross_asset_comparison.py` — ablação controlada, mesmo
  método da 12ª rodada.
- **O que não muda**: a feature não entra em `FEATURE_NAMES`/
  `MODEL_FEATURE_NAMES` — depende de um segundo stream de dado que a
  maioria dos fluxos (`train_model.py`, triagem de moedas, perfis de
  risco) não tem, então não poderia entrar incondicionalmente sem
  quebrar tudo isso (diferente da confluência multi-timeframe, 12ª
  rodada, que só dependia do próprio stream).

## Bug real encontrado e corrigido durante a validação
- Primeira tentativa de rodar a ablação: `0 trades em todos os 5 folds`
  do lado "com a feature" — não era resultado, era bug.
- Causa: `backtesting/engine.py::BacktestEngine` sempre construía
  `FeatureEngine()` sem `reference_symbol`, mesmo quando
  `build_dataset` (usado só para montar o dataset de treino) já
  recebia o parâmetro corretamente. Um modelo treinado com
  `eth_relative_strength_pct` nunca via essa chave durante a avaliação
  real do fold — `ModelStrategy.on_features` sempre retornava `None`
  (`not all(name in snapshot.features for name in self.model.feature_names)`
  sempre verdadeiro).
- Corrigido: `reference_symbol` agora propaga por toda a cadeia —
  `BacktestEngine.__init__` → `model/promotion.py::run_backtest` →
  `evaluate_fold` → `model/strategy.py::choose_regime_threshold` →
  `evaluate_config`. Teste de regressão explícito
  (`test_reference_symbol_reaches_the_engine_used_for_fold_evaluation`,
  `tests/test_backtest_engine.py`) — prova por comportamento observável
  (uma estratégia que só entra quando a feature está presente consegue
  operar com `reference_symbol` configurado e não consegue sem).

## Classificação de risco da mudança
- [ ] Não é mudança de parâmetro de risco/execução em produção — feature
  opt-in, sem uso em nenhum modelo promovido (nenhum existe hoje).

## Validação
- 260 testes passando (11 novos: `ReturnOverWindow`, `FeatureEngine`
  multi-símbolo, `build_dataset` multi-símbolo, o bug de
  `BacktestEngine`/regressão).
- **Comparação real (2026-08-17), 90 dias de BTCUSDT+ETHUSDT** (ver
  `11-roadmap-e-fases.md`, 14ª rodada): `folds_won=0/5` nos dois casos,
  `mean_pf` 0.67 (sem) vs. 0.63 (com) — delta pequeno e misto, dentro do
  ruído já observado entre janelas (12ª rodada).

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-17
- Justificativa: "vamos seguir o seu plano iniciando pelo item 1".
  Resultado inconclusivo, mesma lógica de decisão da 12ª rodada: mantida
  disponível (opt-in) por motivação mecanística e ausência de piora além
  do ruído, sem entrar como default. Próximo item do plano combinado:
  automatizar a correção de taxa nas análises de produção.
