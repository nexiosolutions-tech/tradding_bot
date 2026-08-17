# 13 — Perfis de Risco (Segurança / Intermediário / Arrojado)

## Objetivo

Comparar, em backtest e com dado real, três pontos de agressividade
diferentes sobre a mesma arquitetura de features/modelo já validada —
sem mudar arquitetura, sem capital real, sem execução ao vivo. Resposta a
um pedido do usuário para eventualmente dar ao operador a opção de
escolher o quanto de risco assumir, mantendo o motor de ML/IA comum aos
três.

## Por que backtest primeiro, não os 3 ao vivo simultaneamente

Duas razões, uma estatística e uma arquitetural — nenhuma delas é
burocracia, as duas mudam o que o resultado significaria:

1. **"Agressividade" e "edge preditivo" são eixos diferentes.**
   `profit_factor` (a métrica que decide `folds_won`, o próprio gate de
   promoção — `07-backtesting-e-validacao.md`) é uma razão
   (ganhos/perdas) — escalar uniformemente o tamanho de toda posição
   (`risk_per_trade_pct`) não muda essa razão, só a magnitude em dólares.
   Rodar 3 perfis que só variam tamanho de posição sobre uma estratégia
   sem edge confirmado (nenhum par jamais venceu o gate de promoção —
   `11-roadmap-e-fases.md`, 12 rodadas) não geraria 3 resultados
   comparáveis de verdade — só 3 velocidades diferentes de perder
   dinheiro. Por isso os perfis aqui variam também `entry_percentile`
   (seletividade — muda quais trades acontecem, não só o tamanho deles)
   e `stop_loss_pct` (muda a própria definição do rótulo de treino via
   `TargetConfig.stop_loss_pct`, `model/dataset.py` — um efeito real, não
   só cosmético).
2. **A arquitetura de execução de hoje assume uma estratégia só.**
   `execution/bootstrap.py::build_orchestrator` monta um `Orchestrator`
   com uma estratégia, um símbolo, um pool de equity. Rodar 3 perfis ao
   vivo simultaneamente exigiria 3 alocações de capital isoladas (perda
   de um perfil não pode comer o orçamento do outro) — mudança real de
   arquitetura de execução, `CLAUDE.md` regra 7, e qualquer parâmetro de
   risco novo em produção passa pela regra 6 (aprovação humana explícita
   antes de capital real). Fora de escopo aqui.

## Os 3 perfis

Fixo nos três (isola o eixo de risco do eixo de timing, já validado
separadamente): `horizon_minutes=45` (specs/11, 9ª-12ª rodadas),
mesmo conjunto de features (specs/03).

| Perfil | `entry_percentile` | `stop_loss_pct` | `risk_per_trade_pct` | `max_concurrent_exposure_pct` | `circuit_breaker_loss_pct` |
|---|---|---|---|---|---|
| **Segurança** | 99.5 | 1.0% | 0.5% | 10% | 5% |
| **Intermediário** | 99.0 | 1.5% | 1.0% | 20% | 10% |
| **Arrojado** | 95.0 | 2.5% | 2.0% | 35% | 15% |

- **Intermediário == a config de referência já validada** (specs/11,
  `RiskConfig()` default) — "deixar rodando como é hoje", nas palavras do
  usuário. Não é um perfil novo, é o mesmo já em produção, incluído para
  comparação lado a lado.
- **Segurança**: mais seletivo (só os 0.5% de maior confiança entram),
  stop mais apertado, posição menor, circuit breaker mais sensível.
- **Arrojado**: menos seletivo (mais trades), stop mais largo (mais
  espaço antes de sair, também mais perda se errar), posição maior,
  circuit breaker mais tolerante.
- Valores de `entry_percentile` (95/99/99.5) dentro do intervalo já
  varrido em rodadas anteriores (`sweep_thresholds.py`,
  `ENTRY_PERCENTILE_GRID`) — não são números novos e não testados, são
  pontos já conhecidos, agora nomeados e combinados com risco.

## Extensão de `evaluate_config` (aditiva)

`model/evaluation.py::evaluate_config` ganha `stop_loss_pct` (default
`0.015`, o valor de sempre) e `risk_config: RiskConfig | None` (default
`None` → `RiskConfig()` de sempre) — quem já chama a função sem esses
parâmetros continua com o comportamento idêntico ao de antes. Candidato e
baseline sempre rodam sob o mesmo `risk_config` dentro de uma mesma
avaliação — comparação justa "o candidato bate o baseline **neste**
perfil de risco", não perfis diferentes um do outro.

## Ferramenta de comparação

`scripts/run_risk_profile_comparison.py` — mesmo padrão de
`run_coin_discovery.py`: busca klines reais de BTCUSDT uma vez, roda
`evaluate_config` para cada um dos 3 perfis (`model/risk_profiles.py`),
imprime tabela comparativa.

## Métricas reportadas e como ler cada uma

- `folds_won`/`mean_profit_factor`/`min_profit_factor` — dirigidas
  principalmente por `entry_percentile`/`stop_loss_pct` (mudam quais
  trades acontecem e como o rótulo de treino é definido). É aqui que uma
  pergunta nova pode ter resposta: um perfil mais seletivo cruza o gate
  onde o Intermediário não cruza?
- `max_drawdown_pct` por fold — dirigida principalmente por
  `risk_per_trade_pct`/`circuit_breaker_loss_pct`. Não se espera que
  `profit_factor` varie por causa desses dois isoladamente (razão
  invariante a escala uniforme de posição) — mas o drawdown máximo em %
  do capital, sim.

## Fora de escopo

- Execução ao vivo simultânea dos 3 perfis (ver seção acima).
- Qualquer promoção automática — mesmo um perfil vencendo o gate em
  backtest ainda exige `changes/` + aprovação humana explícita antes de
  capital real (`CLAUDE.md` regra 6).
- Novos parâmetros de risco além dos já existentes em `RiskConfig`
  (`05-gestao-de-risco.md`) — os perfis reusam o que já existe, não
  inventam mecanismo novo.
