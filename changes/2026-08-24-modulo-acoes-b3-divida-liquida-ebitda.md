# 2026-08-24 — Módulo de Ações: dívida líquida/EBITDA, primeiro fator a exercitar a matriz

## Contexto

Usuário pediu dívida líquida/EBITDA em vez de EV/EBITDA especificamente para forçar a
matriz de aplicabilidade a existir sem abrir a quinta fonte de dado (ações em
circulação/valor de mercado, ainda não localizada — ver `changes/2026-08-24-modulo-acoes-
b3-secao-7-earnings-yield.md`, verificação anterior). Pediu, na ordem: verificar os
CD_CONTA de EBITDA e dívida líquida contra demonstração real antes de calcular qualquer
coisa; parar e avisar se D&A exigisse uma fonte nova.

## Verificação (reportada e aprovada antes da implementação)

Confirmado contra a DRE/DFC/BP reais da Petrobras (2015, publicado 2016):

- **D&A não está na DRE** (86 linhas reais checadas, zero menções) — só na DFC método
  indireto, grupo de reconciliação `CD_CONTA "6.01.01.*"`, código não fixo
  (`ST_CONTA_FIXA='N'`).
- **Achado não previsto**: `CD_CONTA "3.05"` (DRE) é `ST_CONTA_FIXA='S'` tanto para
  Petrobras (`"Resultado Antes do Resultado Financeiro e dos Tributos"`, EBIT) quanto
  para Itaú (`"Resultado Antes dos Tributos sobre o Lucro"`, lucro pré-imposto) — mesmo
  código, `ST_CONTA_FIXA='S'` nos dois, significados inteiramente diferentes, porque
  instituição financeira usa outro plano de contas de DRE. `ST_CONTA_FIXA='S'` garante
  fixo *dentro* da variante, não *entre* variantes — achado que exigiu verificar
  `DS_CONTA` em toda consulta que depende de `CD_CONTA`, não só confiar no código.
- Dívida líquida (BP): caixa (BPA `"1.01.01"`) e dívida circulante+não circulante (BPP
  `"2.01.04"`/`"2.02.01"`) — sem armadilha adicional, códigos consistentes com o esperado.

## O que foi implementado

`CvmFinancialLineItem` ganhou o campo `base` (`"con"`/`"ind"`, padrão `"con"`) —
convenção fixa estrutural, não checagem em runtime: cada consulta de fator filtra pela
mesma base sempre, para que EBIT consolidado nunca se combine com D&A individual.
`ingest_line_items_for_cnpj` ganhou o parâmetro `base` correspondente.

`backend/src/tradingbot/acoes/fatores.py`, novas funções:

- `get_ebit_as_of` — `CD_CONTA "3.05"`, **verificado por `DS_CONTA`** antes de aceitar o
  valor (o achado do banco). `None` para instituição financeira.
- `get_depreciacao_amortizacao_as_of` — busca por conteúdo de `DS_CONTA` dentro do
  prefixo `"6.01.01."`, nunca por código literal. `None` (não zero) se ausente ou
  ambíguo — D&A ausente ≠ D&A zero.
- `get_ebitda_as_of` — EBIT + D&A, mesma `base`, `None` se qualquer parte faltar (nunca
  soma parcial).
- `get_divida_liquida_as_of` — BPA/BPP.
- `divida_liquida_ebitda_raw` — `None` (indefinido) quando `EBITDA ≤ 0`.
- `fator_divida_liquida_ebitda_aplicavel` — matriz por subsetor B3, escopo verificado:
  só `"Intermediários Financeiros"` inaplicável, com justificativa econômica registrada
  (alavancagem é o negócio do banco, não um risco a medir). Seguradoras/bolsa/holdings
  financeiras explicitamente **não** incluídas — casos-limite pendentes, não assumidos.
- `compute_score_composto` — renormaliza pesos sobre fatores aplicáveis (percentil
  presente), não sobre um conjunto fixo.

## Três categorias de ausência, três ramos de código

Inaplicável (matriz, decisão determinística por subsetor) vs. faltante (dado deveria
existir e não existe — `get_ebitda_as_of`/`get_divida_liquida_as_of` devolvem `None`) vs.
indefinido (dado existe, `EBITDA ≤ 0` torna o múltiplo sem sentido econômico —
`divida_liquida_ebitda_raw` devolve `None`). Faltante e indefinido são mecanicamente
idênticos na normalização (imputação pela mediana), mas semanticamente distintos,
registrados separadamente para auditoria.

## Resultado real: Petrobras 2015

EBIT real -R$13.188 milhões (**prejuízo operacional**, não só líquido) + D&A real
R$38.574 milhões = **EBITDA R$25.386 milhões, positivo apesar do EBIT negativo** —
comportamento esperado numa empresa intensiva em ativo fixo. Dívida líquida real
R$395.004 milhões. Dívida líquida/EBITDA real **≈15,56x** — alavancagem severa, real,
consistente com o rebaixamento de rating da Petrobras por agências internacionais em
2015.

## O teste da composição — a Seção 8 ainda não tem código

Confirmado antes de rodar: Seção 8 (motor de carteira) é spec, não código nesta
implementação — não havia lógica de composição para verificar se renormalizava ou
assumia conjunto fixo. `compute_score_composto` foi implementada em `fatores.py` como
semente mínima da regra, não o motor de carteira completo. Teste de aceite: `ITUB4`
(só earnings yield aplicável, banco) e `PETR4` (os dois fatores aplicáveis), ambos no
percentil 80 nos fatores que se aplicam, chegam ao mesmo score composto — sem
renormalização, `ITUB4` ficaria com score 40 (tratando o fator ausente como zero) em vez
de 80, um viés setorial inteiro escondido na aritmética. Teste explícito
(`test_compute_score_composto_sem_renormalizacao_seria_viesado`) documenta o bug que a
renormalização evita, como especificação executável.

## Point-in-time de três demonstrações — o mais exigente até agora

Teste de aceite prova que `get_ebitda_as_of`/`get_divida_liquida_as_of` resolvem o filing
vigente **na data de decisão**: antes da publicação real da Petrobras
(`dt_receb=2016-03-21`), os dois são `None`; depois, os valores reais aparecem, do mesmo
exercício, todos resolvidos pelo mesmo `get_latest_filing_as_of`.

## Testes novos

`backend/tests/test_acoes_fatores_divida_liquida_ebitda.py`, 11 testes: `get_ebit_as_of`
verifica `DS_CONTA` (banco vira `None`); D&A real sem ambiguidade (12 candidatos, 1
match); EBITDA real positivo apesar de EBIT negativo; EBITDA de banco `None`; dívida
líquida real; múltiplo real ≈15,56x; regra de indefinido (`EBITDA≤0`); matriz
(banco/industrial/desconhecido); composição comparável banco vs. industrial;
especificação executável do bug evitado; point-in-time de três demonstrações. Fixtures
novas, todas reais, extratos mínimos: `dre_con_2015_itub_bbas_petr_ebit_real_extract.csv`,
`dfc_mi_con_2015_petr_da_real_extract.csv`, `bpa_con_2015_petr_caixa_real_extract.csv`,
`bpp_con_2015_petr_divida_real_extract.csv`. 413 testes passam na suíte completa (402 +
11 novos), zero regressão.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Nova Seção 7.2: as duas armadilhas achadas (D&A fora da DRE, `CD_CONTA` com significado
diferente em banco apesar de `ST_CONTA_FIXA='S'`), a convenção de `base` consolidada, as
três categorias de ausência, o resultado real da Petrobras, o teste de composição e a
nota explícita de que a Seção 8 precisa herdar a regra de renormalização quando for
implementada de verdade, não redecidir. Seção 12 (Fase 3) atualizada.

## Pendente

- EV/EBITDA — precisa de valor de mercado (ações em circulação × preço), fonte não
  encontrada em FCA nem DFP; provável quinta demonstração (Formulário de Referência),
  não aberta nesta rodada.
- Seguradoras, bolsa (B3/`BVMF3`), holdings financeiras na matriz — casos-limite
  nomeados pelo usuário, não verificados contra dado real ainda.
- Seção 8 (motor de carteira) sem código — `compute_score_composto` é semente mínima,
  não o motor completo (sugestão de aporte, tetos por ativo/setor, alerta de saída por
  liquidez).
- Demais famílias de fator (Qualidade, Crescimento, Momentum, Tamanho).

## Decisão

- Aprovado por: Brian — pediu a verificação de CD_CONTA antes de qualquer cálculo, com
  instrução explícita de parar se D&A exigisse fonte nova (não exigiu — DFC já é uma
  demonstração conhecida via `get_latest_filing_as_of`, não uma quinta fonte). Definiu a
  sequência (EBITDA→dívida líquida/EBITDA→matriz→composição→point-in-time
  multi-fonte) e pediu confirmação prévia sobre se a Seção 8 renormaliza pesos antes de
  rodar o teste da composição (2026-08-24).
- Justificativa: o achado do `CD_CONTA "3.05"` com significado diferente em banco, apesar
  de `ST_CONTA_FIXA='S'` nas duas empresas, é exatamente o tipo de armadilha que só
  aparece verificando contra dado real de mais de uma empresa — confirma a disciplina do
  projeto (nunca confiar em metadado de "fixo" sozinho) e virou uma regra estrutural
  (verificação de `DS_CONTA`) que qualquer fator futuro baseado em `CD_CONTA` deve seguir.
