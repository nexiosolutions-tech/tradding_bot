# 2026-08-26 — Módulo de Ações: nomeando o padrão do bug, piso absoluto justificado por massa, requisito de asserção na ingestão

## Contexto

Rodada de revisão sobre a anterior (diagnóstico bancário + bug do
`compute_demeaned_percentiles`, `changes/2026-08-25-modulo-acoes-b3-diagnostico-bancario-e-piso-de-fator.md`).
Sem mudança de código — refinamento de framing e três decisões de registro que a spec
precisava capturar antes de fechar o assunto.

## O padrão do bug, nomeado

Um diagnóstico encomendado para investigar um viés (bancário) revelou um bug de código
que produzia outro viés maior: o piso de população do bucket estava sendo satisfeito com
dado inventado (`len(grupo)=7 >= 3` passava com só 2 valores reais). O bug não era
específico de bancos — atinge qualquer bucket pequeno com imputação, o que descreve
metade dos setores da B3 (Seção 6.2: 5 de 11 setores de produção abaixo de população 6).
Registrado explicitamente na Seção 7.5 para não deixar a lição confinada ao caso que a
expôs.

## Por que N absoluto, não piso percentual — o argumento de massa

Concordância com a generalização de N≥100 (Seção 10, critério 2) para o universo com
score computável, mas por uma razão mais forte que "evitar reinventar": poder estatístico
transversal depende de massa absoluta, não de fração coberta — 90% de um universo de 60
é amostra pior que 80% de um universo de 150. Como o universo elegível da B3 oscila entre
113 e 235 conforme o ano, um piso percentual ficaria frouxo nos anos gordos e apertado nos
magros, o inverso do que a proteção deveria fazer. Registrado na Seção 7.5/10.

## 2016 reprovando é o critério funcionando, não um problema

2016 foi o vale do ciclo (recessão, universo bruto de 113). Um piso desenhado para
proteger poder estatístico transversal que reprova o ano mais magro está fazendo o
trabalho para o qual foi desenhado — reconecta com a tensão de folds fora da era
avaliável já registrada no critério 1 da Seção 10.

## N=100 passa a fazer trabalho diferente — herdado, não recalibrado

N=100 foi calibrado contra o mínimo do universo *bruto* (113 em 2016) e descrito
explicitamente como guarda passiva ("nunca reprova nada"). Aplicado ao universo
computável, ele passa a morder de verdade (reprova 2016 com 97) — deixou de ser guarda e
virou filtro ativo. Um número calibrado para uma função raramente é certo para outra por
coincidência. **Decisão registrada por ora**: manter 100, mas marcado como herdado e não
recalibrado nas Seções 7.5 e 10 — recalibração pendente até a série completa 2015-2026
mostrar quantos anos o critério reprova. Reprovar dois ou três anos de vale é o critério
funcionando; reprovar metade da série é sinal de que o número está errado.

## Requisito novo para a otimização de ingestão pendente (Seção 6.2)

O padrão savepoint-por-linha (ainda pendente de otimização por performance) foi o mesmo
padrão que produziu o truncamento silencioso na fronteira de sessão (Seção 5.1). Registrado
como requisito para quando a otimização for feita: a conferência de contagem de linhas
contra o arquivo bruto deve virar **asserção de código dentro da própria rotina de
ingestão** (falha visível se não bater), não passo de verificação manual pós-ingestão —
para que o truncamento fique impossível de não notar, em vez de algo que se lembrou de
checar da última vez.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Seção 7.5: parágrafo nomeando o padrão do bug (não específico de bancos), parágrafo do
argumento de massa para N absoluto, parágrafo "2016 reprovar é o critério funcionando",
parágrafo "N=100 herdado, não recalibrado, decisão registrada". Seção 10, critério 2:
mesmo argumento de massa e a nota de herdado-não-recalibrado. Seção 6.2 (nota de
performance da ingestão): requisito de asserção de contagem de linhas como parte do
código, não verificação manual.

## Pendente

- Recalibração de N=100 (ou confirmação de que 100 é o número certo por argumento de
  poder estatístico, não por herança) — depende da série completa 2015-2026.
- Otimização de ingestão savepoint-por-linha → lote, com a asserção de contagem de linhas
  já embutida no código desde a primeira versão da rotina otimizada.

## Decisão

- Aprovado por: Brian — nomeou o padrão do bug explicitamente (diagnóstico revela bug
  maior que o achado que o motivou), deu o argumento de massa para preferir N absoluto a
  piso percentual (não só "evita reinventar"), separou "2016 reprovar é informativo" de
  "é um problema", pediu que N=100 seja revisto por fazer trabalho novo mesmo que a
  resposta continue sendo 100, e pediu que a futura otimização de ingestão inclua a
  conferência de linhas como asserção de código, não checagem manual (2026-08-26).
- Justificativa: cada um desses pontos fecha uma lacuna que ficaria implícita ou
  esquecida se não registrada agora — o argumento de massa evita que um piso percentual
  reapareça como "mais simples" numa rodada futura sem quem lembre por que foi
  descartado; marcar N=100 como herdado evita que ele seja tratado como validado por
  aparecer numa spec já revisada; e a asserção de código na ingestão fecha exatamente o
  tipo de falha (truncamento silencioso) que já aconteceu uma vez neste módulo.
