# Change Proposal — 2026-08-15 — Perfis de risco (Segurança/Intermediário/Arrojado), comparação em backtest

**Status:** aplicada

## Evidência (origem)
- Pedido do usuário para dar ao operador diferentes níveis de
  agressividade (risco assumido pelo bot), com a ideia inicial de rodar
  os 3 ao vivo simultaneamente e coletar dado comparável.
- Avaliação antes de aceitar como está: `profit_factor` (a métrica do
  gate de promoção, specs/07) é uma razão — invariante a escalar
  uniformemente o tamanho de posição. Rodar 3 perfis que só variassem
  `risk_per_trade_pct` sobre uma estratégia sem edge confirmado (nenhum
  par jamais venceu o gate — specs/11, 12 rodadas) não geraria resultado
  comparável de verdade. Além disso, `execution/bootstrap.py` assume uma
  estratégia/um símbolo/um pool de capital só — rodar 3 ao vivo exigiria
  mudança de arquitetura de execução (`CLAUDE.md` regra 7) e qualquer
  parâmetro de risco novo em produção passa pela regra 6.
- Recomendação alternativa aprovada pelo usuário: comparar os 3 perfis em
  backtest primeiro, variando também `entry_percentile` e
  `stop_loss_pct` (não só tamanho de posição) para gerar sinal
  estatístico real, seguindo o mesmo método das rodadas anteriores.

## Proposta
- `specs/13-perfis-de-risco.md` (nova) — contrato completo: os 3
  perfis, por que backtest primeiro, e o que fica fora de escopo.
- `model/evaluation.py::evaluate_config` ganha `stop_loss_pct` (default
  `0.015`, o de sempre) e `risk_config: RiskConfig | None` (default
  `None` → `RiskConfig()` de sempre) — aditivo, quem já chama sem esses
  parâmetros mantém o comportamento idêntico.
- `model/promotion.py::run_backtest`/`evaluate_fold` e
  `model/strategy.py::choose_regime_threshold` ganham o mesmo parâmetro
  `risk_config`, threaded através de toda a cadeia — candidato e
  baseline sempre avaliados sob o mesmo perfil de risco dentro de uma
  mesma chamada.
- `model/risk_profiles.py` (novo) — os 3 presets nomeados
  (`SEGURANCA`/`INTERMEDIARIO`/`ARROJADO`). `INTERMEDIARIO` é
  literalmente `RiskConfig()` — a config já validada, não um perfil
  novo.
- `scripts/run_risk_profile_comparison.py` — roda `evaluate_config` uma
  vez por perfil contra BTCUSDT real, imprime `folds_won`/PF/drawdown
  lado a lado.
- **O que não muda**: nenhuma mudança em `execution/`, nenhum perfil
  roda ao vivo, nenhuma promoção automática.

## Classificação de risco da mudança
- [ ] Não é mudança de parâmetro de risco/execução em produção — é
  extensão aditiva de uma ferramenta de backtest já existente
  (`evaluate_config`), e um script de pesquisa novo, sem capital real
  envolvido. `RiskConfig()` (o perfil realmente em produção hoje) fica
  inalterado.

## Validação
- 7 testes novos: threading de `risk_config` através de
  `run_backtest`/`evaluate_fold` provado por comportamento observável
  (circuit breaker mais apertado fecha o backtest com menos trades que
  um mais tolerante, mesmos eventos/estratégia — não é peek em
  internals), e os 3 perfis com os valores relativos corretos entre si
  (`test_risk_profiles.py`).
- Suíte completa: 247 testes passando.
- **Comparação real (2026-08-17), 90 dias de BTCUSDT** (ver
  `11-roadmap-e-fases.md`, 13ª rodada, para a tabela completa):
  `folds_won=0/5` nos três perfis. Achado não esperado de antemão:
  Intermediário (a config já em produção) teve o melhor `mean_pf` (0.87)
  dos três — Segurança (0.48) e Arrojado (0.43) ficaram piores, não
  melhores. `min_pf` similar nos três (0.08-0.10) — reforça que o teto é
  qualidade de timing, não tamanho de posição. `max_drawdown` escalou
  como esperado com o risco por trade.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-15
- Justificativa: "Pode escrever a spec e prosseguir com a implementação,
  acredito que é um passo importante". Rodar os 3 perfis ao vivo
  simultaneamente fica registrado em specs/13 como próximo passo
  condicional — depende de algum perfil vencer o gate de promoção em
  backtest e de uma mudança de arquitetura de execução separada. Com o
  resultado real (nenhum perfil venceu, Intermediário foi o melhor dos
  três), não há hoje justificativa empírica para avançar nessa direção —
  a config em produção permanece a única validada.
