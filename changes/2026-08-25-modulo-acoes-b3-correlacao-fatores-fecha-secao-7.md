# 2026-08-25 — Módulo de Ações: correlação real sobre as 115 empresas fecha a Seção 7

## Contexto

A Seção 7.3 (ROE) tinha fechado com uma correlação ROE×earnings yield de 0,92 medida
sobre só 3 empresas, explicitamente marcada como estatisticamente insuficiente para
decidir ortogonalidade. Usuário pediu a medição real sobre o universo de 115 empresas de
2016 (já materializado na Seção 6.1), com duas condições explícitas: (1) medir sobre os
valores **demeaned** (o que o score composto de fato usa), não os valores crus — porque
os dois fatores compartilham lucro no numerador, correlação bruta positiva é esperada
por construção, não evidência de redundância; (2) reportar o **n efetivo** (empresas com
os dois fatores definidos), não os 115 nominais. E pediu que o resultado decidisse
explicitamente se a Seção 7 fecha com três fatores ou precisa de mais um antes do
backtest.

## Reconstrução da medição (scratchpad apagado de novo entre turnos)

Terceira vez nesta spec que o scratchpad é apagado no meio do trabalho — reconstruído do
zero com a mesma disciplina de verificação já estabelecida: COTAHIST 2015+2016
reingeridos com contagem de linhas conferida byte a byte contra o arquivo bruto (67.334 e
66.706, batendo exato outra vez), universo de 2016-02-29 reconstruído (N=115,
determinístico — bate exatamente com a medição da Seção 6.1), classificação B3 real
rebuscada via API para as 115 empresas (98/115 cobertura, mesmo número da Seção 6.2).

## Achado novo: a maioria do universo ainda reporta o exercício anterior

62 das 114 empresas com algum filing visível em 2016-02-29 resolveram para o balanço do
exercício **2014** (publicado em 2015), não 2015 — a maior parte das DFPs de 2015 só foi
publicada entre março e junho de 2016, depois da data de decisão. Exigiu baixar e
processar `dfp_cia_aberta_2014.zip` (índice mestre + DRE_con + BPP_con), não previsto
antes de medir. Confirma exatamente o comportamento esperado de uma consulta point-in-time
honesta — não um bug, o resultado natural de perguntar "o que era público" numa data no
início do ano civil.

## Achado novo de fonte: arquivos de item da CVM só têm a versão retificada mais recente

Ao processar o Banco do Brasil (caso já conhecido: 3 versões do balanço de 2015, `dt_receb`
25/02, 28/03 e 30/06/2016), o módulo devolveu `None` para EPS/lucro/patrimônio apesar do
filing estar corretamente resolvido como visível (versão 1, `dt_receb=2016-02-25 <=
2016-02-29`). Investigado: `dfp_cia_aberta_DRE_con_2015.csv`, como disponibilizado hoje
pela CVM, só contém a **versão 3** do balanço do BB — as versões 1 e 2 (as que estavam
de fato vigentes em fevereiro de 2016) não têm conteúdo baixável em lugar nenhum. O
índice mestre preserva o metadado histórico de todas as versões (`dt_receb`, `versao`);
os arquivos de item (DRE/BP/DFC) preservam só o conteúdo da retificação mais recente.

**Isso não é um bug do módulo — é o módulo funcionando corretamente.** Usar a versão 3
disponível, rotulada como se fosse a versão 1 vigente em fevereiro, seria vazamento de
point-in-time disfarçado de dado disponível. `get_ebit_as_of`/`get_lucro_liquido_
controladores_as_of`/etc. recusam a versão errada e devolvem `None` (faltante) — o
comportamento correto, mesmo custando cobertura. Medido o tamanho do efeito: **10 das 34
empresas** com algum fator ausente são por este motivo especificamente — distinto de
"empresa não reportou", registrado como limitação de fonte que afeta qualquer consulta
de fator numa janela entre publicação inicial e retificação final, não só EPS/ROE.

## Composição completa do `n` faltante (34 de 115)

| Motivo | N |
|---|---|
| Versão indisponível no arquivo de item (achado acima) | 10 |
| Nenhuma linha no arquivo de item para `(CNPJ, dt_refer)` resolvido | 6 |
| Nenhum filing visível na data | 1 |
| `DS_CONTA` não encontrado apesar da versão certa disponível | ~17 |

## Resultado: correlação real, `n` efetivo reportado

**`n` efetivo = 81 de 115 (70%)** — empresas com earnings yield **e** ROE definidos ao
mesmo tempo, a única base com significado para a correlação.

| | Bruta | **Demeaned** |
|---|---|---|
| Pearson (`n=81`) | 0,28 | **0,40** |

## Interpretação: a correlação demeaned veio mais alta, não mais baixa — e isso tem explicação, não foi forçado para caber na hipótese

A hipótese de trabalho da Seção 7.3 era que o demeaning reduziria a correlação (qualidade
e valor divergindo dentro do setor). O resultado real foi o oposto (0,40 > 0,28).
Explicação registrada, não a única possível, mas consistente: parte da correlação bruta
pode estar sendo **amortecida** por efeito de nível setorial — banco tem ROE
estruturalmente alto mas o mercado já precifica isso via earnings yield próprio do setor,
um efeito que empurra contra a correlação dentro do bruto. Demeaned (comparação dentro do
próprio setor) remove esse efeito de nível e sobra mais puramente o componente mecânico
esperado (lucro no numerador dos dois). **0,40 é moderado**: não é zero (não deveria ser,
os fatores compartilham uma grandeza), mas está bem abaixo do limiar de 0,7 que
sinalizaria redundância real.

## Decisão de escopo: Seção 7 fecha com três fatores

Correlação demeaned moderada, dentro da faixa pré-especificada para fechar a Seção 7 com
os três fatores já implementados (earnings yield/valor, dívida líquida/EBITDA/alavancagem,
ROE/qualidade — três famílias distintas) e seguir para o backtest (Seção 9) em vez de
implementar Crescimento/Momentum/Dividendos/Tamanho antes de saber se a abordagem tem
qualquer poder. É o backtest e o teste de nulidade que decidem isso — três fatores
ortogonais o suficiente já permitem um score composto real e um backtest com significado.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Nova Seção 7.4: os dois achados de fonte (maioria em exercício anterior; versão
retificada indisponível no arquivo de item), a composição do `n` faltante, a tabela
bruta/demeaned, a interpretação da inversão de direção, e a decisão de fechar a Seção 7
com três fatores. Seção 12 (Fase 3) marcada como fechada com a decisão de escopo.

## Pendente

- Correlação de três vias incluindo dívida líquida/EBITDA — parcialmente inaplicável a
  banco (matriz), precisaria de tratamento diferente numa correlação multi-fator; não
  medido nesta rodada.
- Demais famílias de fator — retomadas só se o backtest com os três fatores atuais não
  tiver poder suficiente (Seção 9/10), não antes.
- A limitação de "versão retificada indisponível" pode afetar qualquer consulta futura de
  fator; vale considerar, quando a Fase 2 for além do escopo atual, se um snapshot próprio
  do conteúdo de cada versão (capturado no momento da publicação) é necessário para
  reconstrução point-in-time completa — não resolvido aqui, só nomeado.

## Decisão

- Aprovado por: Brian — pediu a correlação sobre os valores demeaned (não crus, porque a
  correlação bruta é inflada por construção pelo lucro compartilhado), o `n` efetivo
  reportado explicitamente, e definiu o critério de fechamento da Seção 7 antes de medir
  ("se vier razoável, baixa a moderada, feche a Seção 7 com esses três e siga para o
  backtest") (2026-08-25).
- Justificativa: a correlação demeaned (0,40) caiu exatamente na faixa que o critério
  pré-especificado definia como suficiente — decisão tomada pelo número medido, não por
  preferência. A descoberta da limitação de versão retificada indisponível é o tipo de
  achado que só aparece processando escala real (115 empresas, não 3) — confirma, mais
  uma vez, por que a medição em escala segue a mesma disciplina da medição pequena.
