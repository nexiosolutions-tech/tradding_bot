# 2026-08-19 — Módulo de Ações: fonte real do `cnpj_ticker_map` verificada, schema corrigido

## Contexto

`cnpj_ticker_map` estava registrado como pendência de Fase 2 desde a Fase 1 da CVM
(Seção 5.1), e subiu de prioridade na rodada anterior quando a medição do piso setorial
mostrou que o casamento por nome (73%) contaminava a atribuição setorial de que a Seção 7
inteira depende. Usuário pediu a mesma disciplina de sempre antes de desenhar o schema:
achar a fonte real que casa CNPJ e ticker na mesma linha, não assumir.

## Fonte encontrada: FCA da CVM, sub-arquivo de valores mobiliários

`cad_cia_aberta.csv` (já usado nas rodadas anteriores) não tem ticker. O Formulário
Cadastral (FCA) tem um sub-arquivo dedicado:

```
https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_AAAA.zip
  → fca_cia_aberta_valor_mobiliario_AAAA.csv
```

Colunas confirmadas: `CNPJ_Companhia`, `Codigo_Negociacao` (ticker), `Data_Inicio_Negociacao`,
`Data_Fim_Negociacao`, mais classe/segmento. Baixados os anos 2018–2022 e 2024 para testar
contra casos reais.

## Três testes de aceite

1. **Multi-classe — confirmado.** Petrobras (CNPJ `33.000.167/0001-01`) resolve para
   `PETR3` e `PETR4` na mesma linha de filing (2024).
2. **Troca de ticker por evento societário — confirmado, com uma correção de fonte no
   meio do caminho.** Kroton Educacional → Cogna Educação, mesmo CNPJ
   (`02.800.026/0001-40`). O FCA mostra a mudança de nome (2018: KROTON EDUCACIONAL, ticker
   vazio; 2019: COGNA EDUCAÇÃO, ticker COGN3) mas **não dá a data exata da troca de
   código** — seu campo `Data_Inicio_Negociacao` ficou em `2012-11-30` nos dois filings,
   porque mede a admissão da classe de ação à negociação, não o início do código atual.
   A data real veio de baixar `COTAHIST_A2019.ZIP` e medir: `KROT3` negociou até
   `2019-10-10`, `COGN3` estreou em `2019-10-11`. Usar o campo de data do FCA como
   vigência teria atribuído `COGN3` a um período em que o código real ainda era `KROT3` —
   erro silencioso, mesma classe do que `VERSAO`/`ORDEM_EXERC` já tinham ensinado a evitar
   na Seção 5.1, agora numa fonte diferente.
3. **Reatribuição de ticker — não encontrada.** Varridos tickers de ação regular nos 10
   anos de COTAHIST já baixados (2010–2025 + 2019, baixado nesta rodada especificamente
   para o teste 2), procurando código ausente num ano amostrado e reaparecendo sob empresa
   claramente distinta. Zero casos. Consistente com a prática observável de a B3 não
   reciclar código de empresa deslistada, mas **não é prova de ausência** — registrado como
   risco não coberto pelo teste, per instrução explícita do usuário de não fingir que
   testou o que não apareceu na amostra.

## Achado não previsto: taxa de `Codigo_Negociacao` vazio no FCA

Entre 9,4% (2024) e 19,1% (2018) das linhas de ação (ON/PN/Units) têm o campo de ticker
vazio na própria fonte — não é artefato de junção, o dado chega vazio do FCA. Kroton-2018
é um exemplo desse gap, não uma exceção isolada.

## Schema corrigido: duas fontes combinadas, não uma

- **Identidade** (CNPJ↔ticker) vem do FCA — cobre ~81–91% das linhas por ano; o resto cai
  no casamento por nome já usado antes, marcado como `fonte='reconciliacao_nome'` em vez
  de `fonte='FCA'`, exatamente a reconciliação manual auditada antecipada como fallback
  antes de rodar o teste.
- **Vigência** (desde quando um código é válido) vem do COTAHIST — primeira/última data de
  pregão de cada ticker é a fonte autoritativa, não os campos de data do FCA (que medem
  outra coisa, como o teste 2 mostrou).

```
cnpj_ticker_map: cnpj, ticker, tipo, data_inicio_vigencia, data_fim_vigencia, fonte, data_coleta
```

Consulta as-of e regra append-only exatamente como proposto originalmente pelo usuário —
não mudaram, só a origem de cada campo.

## Decisão de saída declarada

CNPJ sem nenhum ticker mapeado (FCA vazio e sem casamento por nome) não entra no universo
elegível nem no scoring — omitido e registrado, mesmo tratamento já usado para histórico
insuficiente (Seção 6) e dado faltante de fator (Seção 7).

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

- Nova Seção 5.4: fonte, os três testes, o achado do gap de 9-19%, schema corrigido,
  decisão de saída.
- Seção 5.1: nota de pendência atualizada para apontar a fonte confirmada.

## Pendente

- Nenhum código de ingestão escrito — desenho de spec.
- Reconciliação por nome para o ~9-19% sem ticker no FCA ainda não tem processo definido
  (fica para quando a Fase 2 começar a ser implementada).

## Decisão

- Aprovado por: Brian — "descobrir qual fonte casa CNPJ e ticker olhando o dado real...
  Antes de desenhar o schema, o passo é o de sempre: baixar os candidatos reais e ver se
  algum tem as duas colunas juntas" (2026-08-19), com os três testes de aceite
  especificados (multi-classe, troca por evento societário com caso real conhecido,
  reatribuição com instrução explícita de registrar como risco não coberto se não
  encontrado em vez de fingir que testou) e a decisão de saída para CNPJ sem ticker.
- Justificativa: a fonte candidata (FCA) resolveu a identidade mas não a vigência como
  prometia — descobrir isso agora, testando contra casos reais conhecidos (Kroton/Cogna),
  evita que o schema fosse implementado confiando num campo de data que mede a coisa
  errada.
