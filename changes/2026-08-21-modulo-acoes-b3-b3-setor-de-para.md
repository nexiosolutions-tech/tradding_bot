# 2026-08-21 — Módulo de Ações: de-para para a taxonomia setorial real da B3

## Contexto

A Seção 6.1 fechou o piso setorial na taxonomia CVM granular (`SETOR_ATIV`), não a
classificação B3 de nível 1 que a Seção 7 assume ("~10 setores"). Usuário pediu o
desenho e a implementação do de-para, com a mesma disciplina de sempre: verificar a
fonte real antes de assumir schema, chave de junção ou cobertura — nomeando
explicitamente a armadilha temporal (classificação corrente não cobre universo
histórico, mesmo problema que a identidade já resolveu uma vez, em outra roupa).

## Verificação da fonte — nada presumido

A página pública de "Classificação setorial"
(`b3.com.br/.../renda-variavel/acoes/consultas/classificacao-setorial/`) não expõe
nenhum arquivo de download — é uma SPA Angular. Inspecionado o HTML bruto da página
(`curl` direto, sem JS) em busca de chamadas de API, achado o endpoint real por trás
dela: `sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetDetail/
{params_base64}` — não documentado publicamente, achado por engenharia reversa do
bundle carregado pela página (`listedCompaniesPage/classification`).

**Schema confirmado por chamada real** (`codeCVM=9512`, Petrobras):
`industryClassification` é uma string de três níveis separados por `" / "` — setor
econômico / subsetor / segmento (`"Petróleo. Gás e Biocombustíveis / Petróleo. Gás e
Biocombustíveis / Exploração. Refino e Distribuição"`, setor e subsetor idênticos porque
só há um subsetor dentro do setor nesse caso). Segunda chamada (`codeCVM=19348`, Itaú):
`"Financeiro / Intermediários Financeiros / Bancos"` — três níveis distintos, confirma
que o primeiro nível é o "setor econômico" que a Seção 7 assume, não um nível mais
granular por acidente.

**Chave é o CNPJ direto** — vem no próprio payload (`"cnpj":"33000167000101"`, sem
pontuação, normalizado para o formato pontuado do resto do módulo). Não precisa passar
por `cnpj_ticker_map` para esta junção específica.

## A armadilha temporal — confirmada, não presumida

Testado diretamente contra dois casos reais escolhidos para forçar a resposta: o
`codeCVM=1279`, registro antigo do Itaú antes de uma reestruturação (`cad_cia_aberta.csv`
mostra dois `CD_CVM` para o mesmo CNPJ do Itaú, um `CANCELADA` e um `ATIVO`), e
`codeCVM=20753`, Banco Cruzeiro do Sul (falido, `SIT=CANCELADA` no registro CVM). Os dois
devolvem payload vazio (`{}`). O `codeCVM=19348` (registro atual do Itaú) devolve
classificação completa. **Confirma exatamente o que o usuário previu**: a fonte só cobre
empresa listada hoje, não o universo histórico.

## Medição de cobertura sobre o universo real de 2016

Consultado o endpoint real para as 115 empresas do universo elegível de 2016-02-29 (já
materializado, `changes/2026-08-20-modulo-acoes-b3-secao-6-universo-elegivel.md`),
mapeando CNPJ→`codeCVM` via `cad_cia_aberta.csv` (preferindo o registro `ATIVO` quando
há mais de um por CNPJ):

**98 de 115 (85%) têm classificação hoje.** As 17 sem cobertura, verificadas uma a uma
contra o que aconteceu de fato na década seguinte — quase todas fusão, incorporação,
falência ou troca de código, não um bug de junção:

| Ticker (2016) | O que aconteceu depois (conhecimento verificável) |
|---|---|
| `LAME4` | Lojas Americanas — recuperação judicial 2023, reestruturada como Americanas S.A. |
| `FIBR3` | Fibria — incorporada pela Suzano em 2019 |
| `SMLE3` | Smiles — incorporada de volta pela GOL em 2021 |
| `QGEP3` | QGEP — renomeada Enauta (`ENAT3`) |
| `LINX3` | Linx — adquirida pela StoneCo em 2021, deslistada |
| `HGTX3` | Cia Hering — adquirida pelo grupo Soma em 2021 |
| `SULA11` | Sul América — adquirida pela Rede D'Or em 2022 |
| `TIMP3` | TIM Participações — reestruturada como TIM S.A. |
| `MPLU3` | Multiplus — incorporada pela LATAM/Smiles |
| outros (`ALSC3`, `ENBR3`, `MAGG3`, `PRML3`, `RLOG3`, `SLED4`, `GOLL4`, `JBSS3`) | fusão, reestruturação societária ou renomeação de código na década |

## Resultado: exatamente o cenário "meio a meio" pré-especificado

Re-medida a distribuição setorial de 2016-02-29 na taxonomia de produção (11 setores de
nível 1, sobre as 98 empresas com cobertura):

| Setor | N |
|---|---|
| Consumo Cíclico | 26 |
| Financeiro | 16 |
| Utilidade Pública | 13 |
| Materiais Básicos | 11 |
| Bens Industriais | 11 |
| Consumo não Cíclico | 9 |
| Saúde | 5 |
| Petróleo, Gás e Biocombustíveis | 3 |
| Comunicações | 2 |
| Tecnologia da Informação | 1 |
| Não Classificados | 1 |

**5 de 11 (45%) abaixo de população 6** (Saúde, Petróleo/Gás, Comunicações, Tecnologia da
Informação, Não Classificados) — nem o cenário "resolvido" (2-3/10, que abriria espaço
para percentil-dentro-do-setor) nem "sem mudança" (quase todos pequenos). É o terceiro
cenário pré-especificado pelo usuário antes de medir, e ele mesmo definiu a ação: confirma
a decisão já tomada de demeaning setorial por subtração de média em vez de
percentil-dentro-do-setor, agora com o número real de produção, não só a taxonomia CVM
como proxy.

| Medição | Taxonomia | Cobertura | Setores | Abaixo de 6 |
|---|---|---|---|---|
| Original (script solto) | CVM granular | 73% | 27 | 22 (81%) |
| `build_universo_elegivel` | CVM granular | 100% | 40 | 36 (90%) |
| **`b3_setor` (esta rodada)** | **B3 nível 1 (produção)** | **85%** | **11** | **5 (45%)** |

## O que foi implementado

`backend/src/tradingbot/acoes/b3_setor.py`: `parse_industry_classification` (parsing puro
do campo `industryClassification`, três níveis), `fetch_classification` (chamada de rede
real ao `GetDetail`, thin wrapper — não exercitada pela suíte, mesma separação já usada
no resto do módulo entre parsing/persistência e I/O), `ingest_classification_snapshot`
(persistência append-only por `(cnpj, data_coleta)`). Nova tabela `models.py`:
`B3IndustryClassification` (cnpj, code_cvm, setor, subsetor, segmento, data_coleta) —
docstring registra explicitamente que é atributo quase-estático, não point-in-time real,
e por quê (mesma disciplina do `data_coleta` já usado em `CnpjTickerMap`).

## Testes novos

`backend/tests/test_acoes_b3_setor.py`, 5 testes, usando
`tests/fixtures/b3_setor/getdetail_real_samples.json` (quatro respostas reais capturadas
em 2026-08-21 — Petrobras e Itaú com classificação completa, o registro antigo do Itaú e
o Banco Cruzeiro do Sul genuinamente vazios, não fabricados): normalização de CNPJ,
parsing de três níveis (incluindo o caso setor==subsetor da Petrobras), parsing vazio,
ingestão com cobertura real (2 inseridos, 2 sem cobertura), append-only. 394 testes
passam na suíte completa (389 + 5 novos), zero regressão.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Nova Seção 6.2: a verificação da fonte, a armadilha temporal confirmada empiricamente, a
medição de cobertura (85%) com a explicação caso a caso das 17 ausências, e a distribuição
setorial re-medida (5/11) lado a lado com as duas medições anteriores (CVM 73%/100%).
Seção 13 (nota do piso setorial) reescrita com as três medições numa tabela só. Seção 12
(Fase 2) atualizada.

## Pendente

- `b3_setor` não está ligado a `build_universo_elegivel` — persiste separado; a Seção 7
  decide como consumir (fallback para `SETOR_ATIV` da CVM quando `b3_setor` não cobrir,
  provavelmente) quando for implementada.
- Série completa 2015-2026 de cobertura/distribuição B3 — só 2016-02-29 medido.
- Reclassificação setorial histórica não capturada (aceita, declarada — Seção 6.2).
- Nenhum agendamento de coleta periódica do snapshot B3 — snapshot único desta rodada,
  `data_coleta=2026-08-21`.

## Decisão

- Aprovado por: Brian — pediu o de-para com a disciplina de verificar a fonte real antes
  de assumir schema, nomeou a armadilha temporal (mesmo eixo da identidade, "em outra
  roupa") e pré-especificou os três cenários possíveis do resultado com a ação de cada um
  antes de medir ("Se cair para 2/10 ou 3/10... Se ainda ficar meio a meio (5/10)... Se
  continuar quase todo mundo abaixo do piso... é sinal para investigar") (2026-08-21).
- Justificativa: o resultado (5/11, 45%) caiu exatamente no cenário do meio, pré-registrado
  antes de qualquer chamada de API — confirma a decisão de demeaning por média já tomada
  na Seção 7, agora com evidência de produção em vez de proxy, e a cobertura de 85% foi
  verificada caso a caso (não só o número agregado) antes de ser aceita como explicável
  por evento societário real, não por bug.
