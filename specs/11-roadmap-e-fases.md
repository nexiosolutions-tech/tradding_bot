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
  promover um modelo que não é consistentemente melhor), não um bug.
- **Iteração de 2026-07-31** (features normalizadas por escala +
  recalibração de `move_threshold_pct`, ver
  `changes/2026-07-31-normalizacao-features-escala-preco.md` e
  `changes/2026-07-31-recalibracao-target-move-threshold.md`): mesma rodada
  real (BTCUSDT, 1m, 45 dias). Resultado: **critério de saída continua não
  atingido, 0 de 5 folds vencidos** — profit factor do candidato entre 0.03
  e 0.43 (com `entry_percentile` ajustado para 99 num teste de calibração
  rápido), bem abaixo do gate absoluto de `min_profit_factor=1.0`. Achado
  relevante no processo: subir o alvo de lucro (`move_threshold_pct`
  0.3%→0.8%) derrubou a taxa de `label=1` para 0.9% do dataset — um
  desbalanceamento de classe forte que desalinha `entry_percentile=80`
  (default do CLI) com a taxa real de positivos; subir o percentil para 99
  melhorou o profit factor em todos os folds mas não o suficiente para
  promover. Não é conclusivo se o teto está no conjunto de
  features/threshold atual, no horizonte (`horizon_minutes=15`), ou se
  BTCUSDT 1m simplesmente não tem sinal explorável suficiente nesse recorte
  — próxima iteração deveria tratar `entry_percentile`/`horizon_minutes`
  como hiperparâmetros a variar sistematicamente, não fixos, antes de
  descartar o conjunto de features atual.
- **Iteração de 2026-07-31 (2ª rodada — features ATR/cíclicas + sweep
  sistemático)**: implementadas as duas features candidatas pendentes
  (`changes/2026-07-31-features-atr-e-ciclicas-tempo.md`) e criado
  `scripts/sweep_thresholds.py` para variar `entry_percentile` (80/90/95/99)
  × `horizon_minutes` (10/15/30) sistematicamente em vez de manualmente,
  buscando os dados uma única vez (BTCUSDT, 1m, 45 dias, `n_splits=3` para
  caber num grid de 12 combinações em tempo razoável).
  - **Padrão claro e consistente nas 12 combinações**: percentil de entrada
    mais alto e horizonte mais longo sempre melhoram o profit factor médio
    — tendência monotônica, ainda subindo nos extremos testados (99%,
    30min). Melhor combinação: `horizon_minutes=30`, `entry_percentile=95-99`
    (mean PF 0.33, min PF 0.16) — mas **0 de 3 folds vencidos em todas as 12
    combinações**, sem exceção.
  - Follow-up explorando horizontes ainda maiores (com `n_splits=5`, já com
    as features novas): `horizon_minutes=45, entry_percentile=99` chegou a
    mean PF 0.77 — bem melhor — mas com `min_trades=6` no pior fold e
    `min_pf=0.00`. Amostra pequena demais para confiar no número (mesma
    ressalva já documentada em `07-backtesting-e-validacao.md` sobre PF
    perto do gate precisar de amostra suficiente) — não é evidência sólida
    de melhora real, é o tipo de resultado que a própria Fase 4b/critério de
    amostra mínima existe para filtrar.
  - **Conclusão desta rodada**: a tendência (percentil/horizonte maiores
    ajudam) é real e vale manter em mente, mas não fecha a lacuna sozinha —
    mesmo o melhor ponto testado com amostra confiável (~0.33) está a ~3x de
    distância do gate de promoção (1.0). As features novas (ATR, cíclicas)
    não foram claramente responsáveis por uma melhora distinguível de ruído
    nesta rodada — não invalida a decisão de adicioná-las (o raciocínio de
    cada uma continua sólido), só significa que não são, sozinhas, a peça
    que faltava.
- Próximos passos possíveis — iteração de modelo, não mudança de fase:
  testar horizontes ainda maiores com dados de um período mais longo (para
  manter `min_trades` alto o suficiente para confiar no resultado), revisar
  se BTCUSDT 1m tem sinal explorável nesse recorte de fato ou se vale testar
  outro timeframe/par, considerar peso de classe no treino (LightGBM) dado
  o desbalanceamento observado (`label=1` em 0.5-4.5% das linhas dependendo
  do horizonte), ou aceitar que esse conjunto de features/target não supera
  a regra simples neste par/janela e testar outro.
- **Limitação conhecida (2026-07-31):** o baseline placeholder da Fase 1
  (`RsiBollingerPlaceholderStrategy`) tem expectância estruturalmente
  negativa — sua saída por recuperação de RSI fecha a posição antes do
  preço cobrir o custo de round-trip (~0.3%), resultando em taxa de acerto
  líquida entre 0% e 9% em múltiplas janelas históricas distintas. Ver
  detalhamento em `07-backtesting-e-validacao.md`. Isso torna "superar o
  baseline" (critério de saída acima) um critério fraco por si só — antes de
  retomar a iteração de features/target desta fase, o critério de promoção
  em `07-backtesting-e-validacao.md` foi reforçado para também exigir
  expectância líquida positiva do próprio candidato (ver
  `changes/2026-07-31-criterio-promocao-expectancia-positiva.md`), não só
  "melhor que um baseline quebrado".

## Fase 3 — Dashboard em modo observação

- Implementar views Live, Performance e Modelo (`08`) consumindo dados do
  backtest/paper trading — ainda sem execução real.
- **Critério de saída:** usuário consegue acompanhar visualmente o
  comportamento do sistema e confia no que está vendo (sem cobrir bugs de
  visualização/dados).
- **Status: implementado.** API FastAPI + dashboard React com as 4 views
  (Live/Performance/Modelo/Aprendizado). Validado visualmente contra a API
  real rodando localmente — as 4 views carregam e renderizam dados reais da
  Fase 1 corretamente (screenshots tirados durante a implementação). Decisão
  de arquitetura tomada: API e `Orchestrator` no mesmo processo/serviço (ver
  `10-stack-tecnica-e-dependencias.md`).

## Fase 4 — Execução em testnet

- Implementar camada de execução (`06`) e gestão de risco (`05`) completas,
  operando contra testnet com o modelo da Fase 2.
- Circuit breaker, stop-loss obrigatório, idempotência e reconciliação
  testados sob condições adversas simuladas (queda de conexão, latência,
  rejeição de ordem).
- **Critério de saída, dividido em duas sub-fases (2026-07-31, ver
  `changes/2026-07-30-criterios-sucesso-periodo-validacao.md`):** a
  formulação original ("período mínimo a definir") misturava duas perguntas
  diferentes — se a execução funciona de forma confiável, e se o modelo tem
  alguma vantagem estatística real. Como a segunda só pode ser respondida
  depois que a Fase 2 promover um modelo, elas foram separadas:
  - **Fase 4a — Validação mecânica** (pode rodar já, com o placeholder da
    Fase 1): critério de saída = operação contínua em testnet sem nenhuma
    violação de invariante de `05-gestao-de-risco.md` (ordem sem
    stop-loss, duplicação de ordem, circuit breaker não respeitado), com
    reconciliação de estado local vs. exchange passando em 100% das
    checagens periódicas. Testável em dias — teste de infraestrutura, não
    de qualidade de modelo.
  - **Fase 4b — Validação de vantagem estatística** (só inicia quando a
    Fase 2 promover um modelo real): critério de saída ligado a **tamanho
    de amostra**, não a prazo fixo em calendário — piso de ≥10 trades
    (mesmo limiar de `09-aprendizado-continuo.md`) antes de qualquer
    conclusão; abaixo disso o resultado do período é ruído, não motivo
    para promover capital nem abandonar o modelo. Se o modelo gerar poucos
    trades no período (comum em estratégias seletivas), o critério se
    estende no tempo em vez de forçar conclusão pelo calendário. Mesma
    checagem de `07-backtesting-e-validacao.md` contra degradação
    concentrada em regime único se aplica à leitura do resultado ao vivo.
    **Nota de calibração:** esse piso de ≥10 trades é um mínimo para "não
    ser obviamente ruído", não uma garantia de significância estatística —
    ver a mesma ressalva sobre `min_profit_factor` perto de 1.0 em
    `07-backtesting-e-validacao.md`.
- **Status: código implementado, validação ao vivo pendente.** `Orchestrator`
  completo (máquina de estados, sizing/stop-loss/circuit breaker via o mesmo
  `RiskManager` do backtesting, idempotência de client order id,
  reconciliação de gap), testado extensivamente contra um `FakeExchangeClient`
  em memória. **Falta:** o usuário gerar chaves de API em
  `testnet.binance.vision` e configurá-las (`BINANCE_API_KEY`/`BINANCE_API_SECRET`)
  — sem isso, nem a Fase 4a pode começar a ser avaliada, porque não há como
  testar contra a exchange real ainda. Como a Fase 2 não promoveu modelo, a
  estratégia ativa por padrão é o placeholder da Fase 1 — rodar em testnet
  hoje só validaria a Fase 4a (mecânica), nunca a 4b (vantagem estatística).

## Fase 5 — Motor de aprendizado contínuo

- Implementar o job diário (`09`), gerando `learnings/` reais a partir dos
  dados de testnet acumulados.
- Validar o fluxo `learnings/ → changes/ → revisão → spec/código` com pelo
  menos um ciclo completo.
- **Critério de saída:** pelo menos uma proposta de `changes/` gerada a partir
  de dados reais, revisada e (aprovada ou rejeitada) por decisão humana
  registrada.
- **Status: código implementado, sem dado real para processar ainda.** Job
  diário e drafting de `changes/` implementados e testados com dados
  sintéticos. O critério de saída depende de trades reais existirem
  (Fase 4 rodando), então só pode ser cumprido depois dela.

## Fase 6 — Produção com capital simbólico

- Mainnet com valor mínimo, mantendo todos os gates de risco ativos.
- **Critério de saída:** decisão humana explícita, fora do escopo desta spec
  (é uma decisão financeira do usuário, não uma recomendação de engenharia).
- **Esta fase não é implementável por um agente de IA.** Não existe código a
  escrever aqui — é a decisão do usuário de trocar `BINANCE_TESTNET=false` (o
  próprio `bootstrap.py` bloqueia isso por padrão, exigindo intervenção manual
  explícita fora do fluxo automatizado) depois de: (a) Fase 4 estável por um
  período que o usuário considere suficiente, (b) as lacunas conhecidas de
  `06-camada-de-execucao.md` fechadas, (c) um modelo real promovido (Fase 2)
  ou aceitação consciente de operar com o placeholder.

## Fase 7 — Operação plena

- Só após Fase 6 validada pelo próprio usuário nos seus próprios critérios.
- Mesma nota da Fase 6: decisão humana, não uma tarefa de engenharia.

---

Cada fase pode gerar novas entradas em `changes/` que retroalimentam specs
anteriores — o roadmap é sequencial em critério de saída, não necessariamente
em que specs podem ser revisitadas.
