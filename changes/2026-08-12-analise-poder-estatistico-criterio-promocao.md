# Change Proposal — 2026-08-12 — Análise de poder estatístico: o gap de promoção é falta de edge ou gate rigoroso demais?

**Status:** aplicada

## Evidência (origem)
- Ligada a: "Balanço consolidado após 10 rodadas" em `specs/11-roadmap-e-fases.md`,
  que deixou em aberto duas leituras não resolvidas para o teto observado
  de `folds_won` (nunca 5/5, apesar de PF por fold individual às vezes
  passar de 1.0): (a) teto real de capacidade preditiva do conjunto
  features/arquitetura, ou (b) critério de promoção rigoroso demais para
  medir um edge real mas modesto com confiança em 90 dias de dado.
- Pedido explícito do usuário para avançar nessa investigação antes de
  decidir entre continuar ajustando a arquitetura atual ou partir para uma
  mudança maior.

## Proposta
- Simulação de Monte Carlo (bootstrap, 8000 repetições), usando os P&Ls
  individuais reais de 85 trades (5 folds do walk-forward, config de
  referência já estabelecida: `horizon_minutes=45`, `entry_percentile=99`,
  balanceamento de classe, sem filtro de regime — a mesma da 4ª rodada).
  Para uma grade de deslocamentos hipotéticos no P&L médio por trade
  (representando "e se o edge real fosse X melhor, mantendo a mesma
  variância/forma da distribuição observada"), reamostra folds sintéticos
  do mesmo tamanho dos folds reais (7 a 24 trades) e mede a fração de
  simulações em que os 5 folds simultaneamente atingem PF ≥ 1.0.
- Script ad-hoc, não incorporado a `model/evaluation.py` — é uma análise
  pontual, não uma ferramenta reutilizável do pipeline (diferente de
  `evaluate_config`/`compute_feature_importance`, que já são reusadas em
  múltiplos scripts e pela ferramenta do loop agêntico).

## Classificação de risco da mudança
- [ ] Não é mudança de código de produção, parâmetro de risco/execução,
  nem de arquitetura — é análise estatística pontual sobre resultados já
  existentes, sem alterar nenhum comportamento do sistema.

## Resultado
- No deslocamento observado (0, i.e., a configuração atual): P(vencer os
  5 folds) ≈ 0% — consistente com o resultado empírico real (nunca
  aconteceu em nenhuma das 10 rodadas anteriores).
- Seria necessário um deslocamento de +$8 no P&L médio por trade (de
  -$3.57 para +$4.43 — mais de meio desvio-padrão do resultado de um
  trade individual) só para chegar a 50% de chance de vencer os 5 folds
  simultaneamente.
- **Conclusão**: essa distância é grande demais para ser efeito de amostra
  pequena — mais dado não resolveria isso, porque a média já observada é
  negativa (mais trades por fold tornaria essa estimativa mais confiável
  na direção negativa, não abriria uma chance de passar por sorte). Isso
  resolve a dúvida a favor da leitura (a): o teto observado é mais
  consistente com limite real de capacidade preditiva do conjunto
  features/arquitetura do que com um gate rigoroso demais barrando um
  edge real e modesto.
- Achado secundário, registrado como contexto e não como conclusão: mesmo
  num cenário de edge forte o bastante para passar em 87% dos folds
  individuais, a chance agregada de bater 5/5 cai para 50% — o gate é
  matematicamente exigente por natureza (vencer 5 eventos independentes é
  uma exigência multiplicativa), por design da spec 07. Isso não muda a
  conclusão principal, só documenta que o gate em si tem um custo
  estatístico real, caso uma revisão futura do critério de promoção venha
  a ser proposta (mudança de risco separada, `CLAUDE.md` regra 6).
- Limitação assumida: o bootstrap junta os 5 folds num pool único, sem
  respeitar que o edge varia por regime de mercado (achado da 5ª/8ª
  rodadas) — não necessário aqui dado o tamanho da distância encontrada.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-12
- Justificativa: continuação direta do plano de trabalho acordado ("vamos
  avançar nos dois itens, começando pelo item 1"). Resultado usado para
  decidir a direção do item 2 (próxima alavanca de melhoria) — reforça
  buscar uma mudança maior em vez de continuar ajustando hiperparâmetros
  dentro da arquitetura atual.
