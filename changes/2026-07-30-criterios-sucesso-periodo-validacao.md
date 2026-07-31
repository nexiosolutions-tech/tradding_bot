# Change Proposal — 2026-07-30 — Critérios de sucesso mensuráveis para o período de validação

**Status:** aplicada

## Evidência (origem)
- Origem: discussão de projeção de retorno/risco para o período de 1 mês de
  teste solicitado pelo usuário; revisão das specs `05`, `07`, `09` e `11`
  (estado então: Fase 2 não concluída, Fase 4 com código pronto mas sem
  chaves de testnet configuradas ainda).
- `11-roadmap-e-fases.md`, Fase 4: "período mínimo (a definir)" — sem
  critério objetivo, seria arbitrário se fixado em dias de calendário.
- `11-roadmap-e-fases.md`, Fase 2: modelo candidato venceu apenas 1 de 5
  folds — evidência de que o sistema de promoção rejeita corretamente
  resultado não consistente, reforçando que o mesmo rigor deve se aplicar à
  leitura do resultado ao vivo em vez de aceitar qualquer resultado do mês
  como conclusivo.
- `09-aprendizado-continuo.md`: limiar de ≥10 trades já estabelecido para
  `change_proposals.py` gerar proposta sem marcar como "preliminar" —
  reaproveitado aqui em vez de inventar outro número.

## Proposta

Preenche três lacunas já sinalizadas como "a definir em `changes/`" nas
specs existentes — **apenas na parte metodológica/estatística**, não em
parâmetros de tolerância a risco.

### 1. Separar o período de testnet em duas sub-fases distintas

A Fase 4 atual mistura duas perguntas diferentes: "a execução funciona de
forma confiável?" e "o modelo tem alguma vantagem estatística real?". Como a
Fase 2 ainda não promoveu um modelo, a resposta à segunda pergunta ainda não
pode ser avaliada.

- **Fase 4a — Validação mecânica** (pode começar já, com o placeholder da
  Fase 1): critério de saída = operar contra testnet real por um período
  contínuo sem nenhuma violação de invariante de `05-gestao-de-risco.md`
  (ordem sem stop-loss, duplicação de ordem, circuit breaker não
  respeitado), com reconciliação de estado local vs. exchange passando em
  100% das checagens periódicas. Testável em dias, não precisa de 1 mês nem
  de um modelo real — é teste de infraestrutura.
- **Fase 4b — Validação de vantagem estatística** (só inicia quando a Fase 2
  promover um modelo real): aqui entra a pergunta "1 mês é suficiente pro ML
  aprender algo útil?". Ver metodologia abaixo.

### 2. Critério estatístico para a Fase 4b (metodologia, não parâmetro de risco)

Em vez de fixar "1 mês" como duração, ligar o critério de saída a **tamanho
de amostra**, já que a frequência de trade do modelo real ainda é
desconhecida:

- Métrica primária de comparação: retorno do sistema vs. retorno de
  buy-and-hold do mesmo ativo no mesmo período exato (em termos relativos,
  não absolutos).
- Amostra mínima antes de qualquer conclusão: piso de ≥10 trades (mesmo
  limiar de `09-aprendizado-continuo.md`) — abaixo disso, o resultado do mês
  (positivo ou negativo) não é conclusivo, é ruído, e não deveria motivar
  nem promoção de capital nem abandono do modelo.
- Se o modelo real gerar poucos trades no mês (comum em estratégias mais
  seletivas), o critério de saída da Fase 4b se estende no tempo, não é
  forçado pelo calendário — evita a armadilha de "1 mês deu 3 trades, tirar
  conclusão de qualquer jeito".
- Checar consistência entre regimes: mesmo com amostra suficiente,
  `07-backtesting-e-validacao.md` já exige não promover em caso de
  "degradação concentrada em um único regime". Aplicar o mesmo princípio à
  leitura do resultado ao vivo — se o mês de teste foi majoritariamente um
  único regime (alta, baixa ou lateral), isso deve ser registrado no
  `learnings/` correspondente como limitação da conclusão, não ignorado.

### 3. O que esta proposta explicitamente NÃO propõe
- Valor de circuit breaker (X% em janela Y) — decisão do usuário.
- Percentual de drawdown máximo tolerado — decisão do usuário.
- Percentual de capital por posição — decisão do usuário.
- Prazo fixo em dias para a Fase 4 no roadmap — substituído pelo critério de
  amostra acima, mais robusto a variações na frequência de trade do modelo.

### Nota de 2026-07-31, ao aplicar esta proposta

O piso de ≥10 trades acima é um piso mínimo para "não ser obviamente
ruído" — não é uma garantia de significância estatística rigorosa,
especialmente para uma métrica como profit factor, que é uma razão e pode
continuar ruidosa mesmo em 60-70 trades se a distribuição de tamanho de
ganhos/perdas tiver qualquer assimetria (achado relacionado: o gate de
`min_profit_factor=1.0` do critério de promoção de backtest,
`changes/2026-07-31-criterio-promocao-expectancia-positiva.md`, tem a mesma
limitação — um PF de 1.02 em 65-77 trades não é necessariamente sinal
confiável, só direção correta). Ver nota cruzada adicionada em
`07-backtesting-e-validacao.md`.

## Classificação de risco da mudança
- [ ] Nova feature (requer revisão humana antes de entrar em specs/03) — na
  verdade é mudança de **critério de leitura/decisão** para as specs `07` e
  `11`, categoria mais próxima desta lista, mas não altera nenhum parâmetro
  de risco/execução em si.

## Validação proposta
- Nenhuma mudança de código imediata — aplicável a `11-roadmap-e-fases.md`
  (critério de saída da Fase 4, dividida em 4a/4b) e como nota metodológica
  em `07-backtesting-e-validacao.md`.
- Validação prática: quando o primeiro `learnings/` real for gerado após a
  Fase 4a rodar, conferir se o relatório já reflete a separação
  mecânica/estatística proposta aqui.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-07-31
- Justificativa: revisão de conteúdo confirmou que a proposta (a) reaproveita
  um limiar já estabelecido em vez de inventar um novo, (b) fica
  explicitamente fora de parâmetros de risco (regra 6 do CLAUDE.md,
  decisão do usuário), e (c) fecha uma lacuna real ("período mínimo a
  definir" em specs/11). Aprovada em conversa junto com o reforço do
  critério de promoção de backtest, com nota cruzada de 2026-07-31 sobre a
  mesma limitação estatística (piso de amostra vs. PF perto de breakeven)
  se aplicar aos dois contextos (validação ao vivo e promoção em backtest).
