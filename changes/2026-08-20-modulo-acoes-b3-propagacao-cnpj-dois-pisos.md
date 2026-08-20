# 2026-08-20 — Módulo de Ações: propagação por CNPJ, dois pisos (precisão + cobertura), 2016 recuperado

## Contexto

Usuário pediu, com teto de esforço explícito: medir quanto da era 2010-2017 é
irrecuperável de verdade vs. reconciliação malfeita, separando os dois problemas que a
auditoria anterior misturou — falso negativo (empresa existe, tokenização não achou) e
falso positivo (match aponta empresa errada). Sequência definida por ele: propagação por
CNPJ primeiro (maior retorno, menor risco), remedir cobertura, auditar precisão de novo,
e só então decidir se vale mexer em tokenização — parado antes disso, como instruído.

## Passo 1: código interno CVM como segunda chave — resultado nulo, honesto

Tentativa de usar um código legado que o FCA às vezes reporta em vez do ticker real (CSN
aparece como `"4030"` em todo ano 2018-2025, nunca como `CSNA3`) como chave de junção
adicional, derivando o de-para de dentro do próprio FCA quando o mesmo CNPJ mostra as
duas formas em anos diferentes. Achado: os 5 pares assim derivados (`9989→RPMG3`,
`90212→MLAS3`, `0000→MTRE3`, `21130→TRIS3`, `23574→MEAL3`) já eram resolvidos pela
propagação direta — zero ganho líquido. Para CSN e casos com código persistente (nunca
coexiste com o ticker real em nenhum ano observado), não há de-para derivável sem
conhecimento externo — ficam de fora, por desenho, sem adivinhação.

## Passo 2: propagação por CNPJ (direta + raiz de ticker) — este funcionou

Dicionário `ticker → CNPJ` a partir de `Codigo_Negociacao` em qualquer ano FCA 2018-2025
(763 tickers), aplicado a 2010-2016. Estendido com propagação por raiz de 4 letras do
ticker (mesma raiz = mesma empresa, classes diferentes — `VALE5`/`VALE3`, `SUZB5`/`SUZB3`
— sem misturar `GOAU4`/`GGBR4`, raízes genuinamente diferentes).

Cobertura, antes (Seção 5.4) vs. depois:

| Ano | Antes | Depois |
|---|---|---|
| 2010 | 0,0% | 69,8% |
| 2012 | 0,0% | 79,9% |
| 2014 | 0,0% | 83,1% |
| 2016 | 0,0% | 90,7% |

## Passo 3: auditoria de precisão nos quatro anos — zero erros em 469 identificações

Toda identificação de 2010, 2012, 2014 e 2016 inspecionada manualmente contra o cadastro
CVM. Nenhum erro em nenhum ano — diferente da reconciliação por nome (Seção 5.5, ~65% de
precisão real), propagação por identidade verificada não colide em token genérico.
Corrigiu inclusive vários dos falsos positivos anteriores (`ESTC3→YDUQS`, `QGEP3→Enauta`,
`TIMP3→TIM Participações`, em vez do buraco negro da Cyrela).

## O piso original media a coisa errada — corrigido para dois pisos

Usuário identificou, a partir do resultado: o piso de 95% (cobertura, um número só) foi
pré-registrado contra o risco de **identidade errada**, silenciosa e não-recuperável. A
auditoria mostrou que esse risco zerou com propagação — o que sobra é **ausência
contável**, natureza diferente (mesma exclusão declarada já usada em toda a spec).
Pré-registrado (antes de auditar 2010/2012/2014, arquivo em
`pre_registro/dois_pisos.txt` da sessão) e aplicado:

1. Precisão de identidade ≥98%, auditada — gate rígido, sem negociação.
2. Cobertura ≥85% — gate de amostra, mais frouxo.

Um ano só é avaliável se passar nos dois. Teste de honestidade que o próprio usuário deu:
"se a auditoria tivesse achado 90,7% de cobertura mas com 10 empresas erradas, a resposta
seria manter 95% e cortar em 2018" — é a precisão de 100%, não a proximidade de 90,7%,
que muda a decisão.

## Resultado final, aplicando os dois pisos

| Ano | Cobertura | Precisão | Avaliável? |
|---|---|---|---|
| 2010 | 69,8% | 100% | Não (cobertura) |
| 2012 | 79,9% | 100% | Não (cobertura) |
| 2014 | 83,1% | 100% | Não (cobertura, perto) |
| 2016 | 90,7% | 100% | **Sim** |

**2016 entra como ano avaliável para o gate de promoção**, junto com 2018 em diante.
2010/2012/2014 ficam de fora só por cobertura — não por identidade ruim, distinção que
não existia antes desta rodada.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

- Nova Seção 5.6: método de propagação, tentativa nula do código interno, tabela de
  cobertura, auditoria de precisão, os dois pisos, resultado final por ano.
- Seção 5.5: conclusão ajustada para apontar à 5.6 em vez de fechar o corte em 2018.
- Seção 10, critério 1: era avaliável passa a ser "2018+ e 2016", não corte único.
- Seção 13: bullet reescrito refletindo a distinção identidade-vs-cobertura.

## Pendente

- 2011, 2013, 2015, 2017 não medidos (nem COTAHIST baixado) — teto de esforço explícito.
  Tendência (69,8→79,9→83,1→90,7%) sugere que a fronteira real de 85% de cobertura fica
  entre 2014 e 2016, possivelmente incluindo 2015 e/ou 2017.
- Tokenização de falsos negativos (BRASIL/BBAS3, concatenação ITUB4) e rejeição de match
  por token genérico não foram implementadas — paradas por instrução explícita, avaliar
  só se depois de medir os anos ímpares ainda faltar pouco.
- Nenhum código de produção escrito — desenho de spec.

## Decisão

- Aprovado por: Brian — sequência definida com teto de esforço explícito ("Começaria pela
  propagação por CNPJ... pare antes da tokenização e da rejeição de match genérico por
  enquanto"), e a correção do próprio critério a partir do resultado ("o piso de 95% media
  a coisa errada... o que sobra em 2016 não é 9,3% de identidade errada, é 9,3% de empresa
  ausente"), com os dois pisos especificados exatamente (precisão ≥98% auditada, cobertura
  ≥85%) e o teste de honestidade para distinguir correção de racionalização (2026-08-20).
- Justificativa: separar os dois tipos de erro (identidade errada vs. ausência) e medir
  cada um com a métrica certa recuperou um ano de amostra sem baixar o padrão de
  segurança contra o risco que de fato importa — exatamente o resultado que o usuário
  previu antes de rodar qualquer coisa.
