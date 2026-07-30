# 11 — Roadmap e Fases

Cada fase só avança para a próxima após critério de saída cumprido. Nenhuma
fase pula direto para capital real sem passar pelas anteriores — essa ordem é
o que torna o projeto seguro de construir incrementalmente.

## Fase 0 — Especificação (atual)

- Specs de `00` a `11` escritas e revisadas.
- Estrutura de `learnings/` e `changes/` criada.
- **Critério de saída:** usuário aprova as specs como base para início de
  implementação.

## Fase 1 — Infraestrutura de dados e backtesting

- Implementar ingestão (`02`) contra testnet e backfill histórico via REST.
- Implementar motor de features (`03`) com o conjunto inicial de indicadores.
- Implementar motor de backtesting event-driven (`07`), sem modelo de ML ainda
  (pode usar regra simples como placeholder para validar a infraestrutura).
- **Critério de saída:** backtest roda de ponta a ponta com dados reais de
  testnet/histórico, com custos (taxas/slippage) modelados.

## Fase 2 — Modelo preditivo

- Implementar pipeline de treino (`04`) com LightGBM baseline.
- Validação walk-forward (`07`) com métricas completas.
- **Critério de saída:** modelo supera baseline ingênuo (ex.: buy-and-hold ou
  regra simples) em backtest out-of-sample, de forma consistente entre
  diferentes janelas de validação.
- **Status:** infraestrutura implementada e validada de ponta a ponta
  (dataset com label sem lookahead, split walk-forward, calibração, promoção
  fold a fold contra o baseline da Fase 1, versionamento). Critério de saída
  **ainda não atingido** — na primeira rodada real (BTCUSDT, 1m, 45 dias), o
  candidato só venceu 1 de 5 folds, rejeitado nos demais por drawdown pior que
  o baseline. Isso é o sistema de promoção funcionando como deveria (recusar
  promover um modelo que não é consistentemente melhor), não um bug. Próximos
  passos possíveis — iteração de modelo, não mudança de fase: revisar
  threshold/target (`04`), considerar novas features via `changes/`, ou
  aceitar que esse conjunto de features/target não supera a regra simples
  neste par/janela e testar outro.

## Fase 3 — Dashboard em modo observação

- Implementar views Live, Performance e Modelo (`08`) consumindo dados do
  backtest/paper trading — ainda sem execução real.
- **Critério de saída:** usuário consegue acompanhar visualmente o
  comportamento do sistema e confia no que está vendo (sem cobrir bugs de
  visualização/dados).

## Fase 4 — Execução em testnet

- Implementar camada de execução (`06`) e gestão de risco (`05`) completas,
  operando contra testnet com o modelo da Fase 2.
- Circuit breaker, stop-loss obrigatório, idempotência e reconciliação
  testados sob condições adversas simuladas (queda de conexão, latência,
  rejeição de ordem).
- **Critério de saída:** operação estável em testnet por um período mínimo
  (a definir), sem violação de nenhuma invariante de risco, com todo o ciclo
  de vida de ordens corretamente refletido no dashboard.

## Fase 5 — Motor de aprendizado contínuo

- Implementar o job diário (`09`), gerando `learnings/` reais a partir dos
  dados de testnet acumulados.
- Validar o fluxo `learnings/ → changes/ → revisão → spec/código` com pelo
  menos um ciclo completo.
- **Critério de saída:** pelo menos uma proposta de `changes/` gerada a partir
  de dados reais, revisada e (aprovada ou rejeitada) por decisão humana
  registrada.

## Fase 6 — Produção com capital simbólico

- Mainnet com valor mínimo, mantendo todos os gates de risco ativos.
- **Critério de saída:** decisão humana explícita, fora do escopo desta spec
  (é uma decisão financeira do usuário, não uma recomendação de engenharia).

## Fase 7 — Operação plena

- Só após Fase 6 validada pelo próprio usuário nos seus próprios critérios.

---

Cada fase pode gerar novas entradas em `changes/` que retroalimentam specs
anteriores — o roadmap é sequencial em critério de saída, não necessariamente
em que specs podem ser revisitadas.
