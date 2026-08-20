# 2026-08-20 — Módulo de Ações: ingestão do índice mestre CVM e consulta point-in-time (Fase 1)

## Contexto

Com a fundação de identidade fechada (fronteira 2015-2026), usuário definiu o primeiro
passo real de código da Fase 1: o índice mestre de filings CVM com `DT_RECEB` e a
consulta as-of — antes de qualquer item financeiro, mesmo raciocínio de sempre
(verificar o dado real, não a suposição). Desenho concreto deixado para execução direta,
não mais uma rodada de spec.

## Verificação antes de escrever código: 2015 tem `DT_RECEB` populado?

A fronteira de identidade fechou em 2015-2026, mas isso não garante que o índice
DFP/ITR retroaja igual — mesma lição do FCA vazio até 2017. Baixados os índices reais de
2015 (`dfp_cia_aberta_2015.csv`, `itr_cia_aberta_2015.csv`): **`DT_RECEB` 100% populado**,
0 vazios em 793 filings DFP e 2155 filings ITR. A era do fundamento não é mais curta que a
de identidade — confirmado antes de investir na ingestão, não depois.

## O que foi implementado

Novo pacote `backend/src/tradingbot/acoes/` — banco e schema próprios
(`acoes/persistence.py`, `results/acoes.db` por padrão), separado do banco do bot
(`tradingbot.persistence`), por desenho: specs/00 e CLAUDE.md exigem que os dois módulos
nunca compartilhem estado, dado, modelo ou runtime.

- **`models.py`**: `CvmFiling` (índice mestre — `cnpj_cia`, `dt_refer`, `versao`,
  `categ_doc`, `dt_receb`, etc.), com `UniqueConstraint(cnpj_cia, dt_refer, versao,
  categ_doc)` — a trava que garante append-only na marra: rejeita `INSERT` duplicado em
  vez de aceitar um `UPDATE` que apagaria a versão antiga. `CvmFinancialLineItem`
  (escopo restrito, só o necessário para provar `ORDEM_EXERC` — não a ingestão genérica
  de todos os tipos de demonstração, que fica para a Fase 2).
- **`cvm_ingestion.py`**: `ingest_master_index` (parser do CSV real, latin-1,
  `;`-delimitado; cada linha numa savepoint própria, duplicata rejeitada pela constraint
  do banco sem derrubar as demais linhas do arquivo) e `ingest_line_items_for_cnpj`
  (loader restrito a um CNPJ, só para o teste de `ORDEM_EXERC`).
- **`pointintime.py`**: `get_filing_as_of` (a consulta as-of — maior `versao` cujo
  `dt_receb <= data_decisao`, filtro por data primeiro, máximo de versão depois, nunca a
  ordem inversa) e `get_line_items_as_of` (contrato completo da Seção 5.2, junta itens à
  versão visível e filtra `ordem_exerc = 'ÚLTIMO'`).

## Fixtures: extratos reais, não dado sintético

`backend/tests/fixtures/cvm/` — dois arquivos, ambos recortes exatos dos CSVs reais
baixados de `dados.cvm.gov.br` em 2026-08-20:

- `dfp_master_index_2024_real_extract.csv`: Banco do Brasil (`dt_refer=2024-12-31`,
  `versao=1`, `dt_receb=2025-02-19` — confirma o número já registrado na Seção 5.1) e BRB
  Banco de Brasília, mesmo exercício, **retificado de verdade três vezes**
  (`versao=1/2/3`, `dt_receb=2025-04-09/2025-04-10/2025-06-30`) — achado desta rodada, não
  estava registrado antes; substitui a necessidade de fabricar um caso de retificação.
- `dre_con_2024_bb_real_extract.csv`: 3 contas da DRE consolidada do BB, cada uma com as
  linhas `ÚLTIMO` (2024) e `PENÚLTIMO` (2023) reais, valores reais.

## Os cinco testes (`backend/tests/test_acoes_cvm_pointintime.py`), todos contra dado real

1. **Append-only na marra**: ingestão do mesmo arquivo duas vezes — 4 inseridos na
   primeira, 0 inseridos/4 rejeitados na segunda (a `UniqueConstraint`, não uma checagem
   de existência em código, decide).
2. **Teste do Banco do Brasil**: `2025-02-18` não vê o exercício 2024; `2025-02-19` vê,
   `versao=1` — o teste de aceite da Seção 5.2, contra o dado real do índice.
3. **Fronteira de fuso, isolada e nomeada**: `dt_receb == data_decisao` conta como
   disponível (`<=`, não `<`) — mesma convenção já usada em toda a spec para
   `data_publicacao <= data_decisão` (Seção 5), agora testada explicitamente para este
   contrato específico.
4. **Retificação, o teste que a maioria dos sistemas erra**: usando o BRB real de 3
   versões — consulta em `2025-04-09` vê v1; **entre** `2025-04-09` e `2025-04-10` ainda
   vê v1, não v2; consulta em `2025-06-29` (quase dois meses depois de v2, um dia antes de
   v3) ainda vê v2, não v3; e a consulta não regride depois (`2026-01-01` continua vendo
   v3, a mais recente).
5. **`ORDEM_EXERC` só devolve o exercício corrente**: contra a DRE real do BB, as 3 contas
   devolvidas são todas `ÚLTIMO` com os valores de 2024 (`273505274.0`/`104514447.0`/
   `29171564.0`), nunca os de 2023 (`PENÚLTIMO`) do mesmo filing. Mais um teste
   (`test_line_items_vazio_antes_do_filing_existir`) confirmando lista vazia, não erro,
   quando nenhum filing está visível ainda na data consultada.

367 testes passam na suíte completa (361 do bot + 6 novos), zero regressão.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

- Seção 12 (fases): Fase 1 marcada como parcialmente implementada, com escopo exato do
  que falta (cotação COTAHIST, itens financeiros genéricos).
- Seção 15 (critérios de aceite): primeiro item marcado como cumprido para a camada de
  filings, com nota do que resta estender a mesma disciplina.

## Pendente

- Ingestão de cotação (COTAHIST) — Fase 1 ainda não fecha sem isso.
- Ingestão genérica de itens financeiros (todos os tipos de demonstração, todas as
  empresas) — `CvmFinancialLineItem`/`ingest_line_items_for_cnpj` desta rodada são
  deliberadamente restritos, só provam o contrato.
- Detecção de reapresentação via `PENÚLTIMO` — reconhecida na Seção 5.1 como uso futuro,
  não implementada.
- `cnpj_ticker_map` (Seção 5.4/5.5/5.6) segue como spec, não como código — precisa existir
  antes da Fase 2 (universo elegível), não antes da Fase 1.

## Decisão

- Aprovado por: Brian — "o primeiro passo é o índice mestre... antes de qualquer item
  financeiro... Deixo o desenho concreto para o Claude Code executar" (2026-08-20), com a
  ordem exata (ingestão → consulta as-of → teste do BB → os três testes de alçapão) e a
  verificação prévia de que pediu explicitamente: "o arquivo-índice cobre 2015 inteiro?"
  antes de escrever qualquer linha.
- Justificativa: verificar `DT_RECEB` em 2015 antes de codificar evitou descobrir tarde
  que a era do fundamento poderia ser mais curta que a de identidade. O achado da
  retificação real do BRB (3 versões, não hipotética) tornou o teste mais forte do que um
  fixture sintético teria permitido.
