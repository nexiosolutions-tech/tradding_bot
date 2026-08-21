# 2026-08-20 — Módulo de Ações: Seção 6 (universo elegível) — primeira junção real das três camadas

## Contexto

Primeiro artefato que junta identidade (`cnpj_ticker_map`), preço (`CotahistPrice`) e
publicação (`CvmFiling`) numa única data de decisão. Usuário nomeou explicitamente por
que este é o passo de maior cuidado desde o point-in-time: junção é onde aparecem bugs
que nenhum teste de camada isolada pega. Três exigências: mesmo relógio nas três
consultas as-of (fronteira inclusiva idêntica); precedência de exclusão explícita e
sequencial, para nunca haver ambiguidade sobre qual motivo registrar quando mais de um se
aplicaria; materialização por data com motivo de exclusão registrado, tão parte do
artefato quanto quem entrou.

## O que foi implementado

`backend/src/tradingbot/acoes/universo_elegivel.py`: `build_universo_elegivel` opera
sobre as tabelas já persistidas pelos três módulos anteriores (nunca re-parseia
COTAHIST/FCA/CVM). Cadeia sequencial de cinco filtros, cada um só alcançado se os
anteriores foram superados: `iliquido` → `classe_secundaria` → `identidade_nao_resolvida`
→ `recuperacao_judicial` (lista vazia por padrão, fonte real pendente) →
`historico_insuficiente`. Duas tabelas novas (`models.py`): `UniversoElegivel`
(ticker, CNPJ, `setor_ativ`, volume mediano) e `UniversoExclusao` (ticker, motivo), ambas
append-only por `UniqueConstraint(data_decisao, ticker)`.

Nova consulta em `pointintime.py`: `get_latest_filing_as_of` — generaliza
`get_filing_as_of` para quando o exercício de referência (`dt_refer`) não é conhecido de
antemão, o caso real da Seção 6 (precisa do último balanço público, não de um exercício
específico). Mesma disciplina de filtrar primeiro por `dt_receb <= data_decisao`, só
depois ordenar por `dt_refer`/`versao` decrescente.

## Teste de junção de fronteira

Reusa fixtures já comitadas do mesmo `BBAS3`/Banco do Brasil real em duas camadas
(`COTAHIST_A2024_real_extract.ZIP` + `dfp_master_index_2024_real_extract.csv`) — sem
precisar de dado novo. Confirma que a camada de preço inclui a própria data de decisão
quando ela é exatamente o último pregão real da fixture, e que `get_latest_filing_as_of`
inclui a própria data quando ela é exatamente o `dt_receb` real — mesmo relógio `<=` nas
duas camadas, sem vazamento de um dia em nenhuma direção.

## Teste de aceite: materialização real de 2016-07-15

Fixtures novas, reais: `COTAHIST_A2016_universo_real_extract.ZIP` (`ITUB3`/`ITUB4`/
`BBAS3`/`PETR3`/`PETR4`, ~74 pregões reais abril-julho/2016, e `HOOT4` real com mediana de
`VOLTOT` ~R$890 — caso real de exclusão por liquidez); `dfp_master_index_2015_itub_bbas_
petr_real_extract.csv` (índice mestre CVM real, exercício 2015, incluindo as 3
retificações reais do BB); `cad_cia_aberta_itub_bbas_petr_real_extract.csv` (`SETOR_ATIV`
real). Resultado: `ITUB4`/`BBAS3`/`PETR4` entram com CNPJ correto, classe mais líquida
escolhida sobre a menos líquida (`ITUB4`>`ITUB3`, `PETR4`>`PETR3`), setor correto
(`Bancos`, `Bancos`, `Petróleo e Gás`), e `get_latest_filing_as_of` devolve a versão 3 do
balanço do BB — a retificação mais recente já pública em 2016-07-15 (`dt_receb=
2016-06-02`), não a v1 nem a v2 — prova que a junção respeita retificação e fronteira de
data ao mesmo tempo.

## Medição definitiva do piso setorial — integridade de ingestão verificada antes de confiar em qualquer número

Ingestão de COTAHIST 2015 e 2016 completos (não extrato) rodou primeiro em background e
foi interrompida silenciosamente na fronteira de sessão — dois processos marcados
"stopped" sem registro de conclusão, banco parcial de 10,8MB. Descartado sem uso, seguindo
o alerta direto do usuário: savepoint-por-linha esconde ingestão truncada atrás de um
número que parece válido. Reingerido em primeiro plano, com contagem de linhas de equity
pré-calculada a partir do arquivo bruto (mesmo filtro `startswith` de `_is_equity`, não
uma reimplementação própria) e comparada byte a byte contra o resultado:

| Ano | Linhas esperadas (filtro real) | Linhas inseridas | Bate? |
|---|---|---|---|
| 2015 | 67.334 | 67.334 | Sim |
| 2016 | 66.706 | 66.706 | Sim |

Ingestão íntegra confirmada nos dois anos antes de qualquer medição.

**Resultado, 2016-02-29 (mesma data da medição original de Seção 8/13), via
`build_universo_elegivel` sobre as três camadas reais:**

| | Medição original (script solto, casamento por nome) | Medição nova (código, junção real por CNPJ) |
|---|---|---|
| N total | 113 | **115** |
| Setores com dado | 83/113 (73%, casamento por nome) | 115/115 (100%, join direto por CNPJ) |
| Setores medidos | 27 | 40 |
| Setores abaixo de população 6 | 22 (81%) | **36 (90%)** |

**N bate dentro de uma diferença pequena e explicável** (+2, na direção prevista: a
identidade auditada de `cnpj_ticker_map` recupera casos que o proxy por raiz de ticker da
medição original não cobria — o mesmo padrão já visto quando `ITUB4`/`BBAS3` chegaram a
ficar de fora por bug de tokenização numa rodada anterior).

**O total de setores medidos subiu de 27 para 40 não porque o universo mudou de
taxonomia, mas porque a cobertura foi de 73% para 100%** — a medição original só atribuía
setor a 83 das 113 empresas (casamento por nome), então setores presentes só entre as 30
sem match nunca apareciam na contagem. Com join direto por CNPJ, todas as 115 têm setor.
A taxonomia usada nas duas medições é a mesma (`SETOR_ATIV` da CVM, granular) — **não** a
classificação B3 de nível 1 que a produção vai usar; esse de-para segue pendente, então o
número exato de setores pequenos na taxonomia final ainda não está fixado, mas a direção
(setor pequeno é a regra) está confirmada duas vezes por métodos independentes, mais forte
na versão com cobertura completa, não mais fraca.

## Testes novos

`backend/tests/test_acoes_universo_elegivel.py`, 6 testes: materialização de aceite
2016-07-15 completa; precedência (`iliquido` vence `identidade_nao_resolvida` quando os
dois se aplicariam); `identidade_nao_resolvida` isolado; `historico_insuficiente` com o
limiar de produção (252); append-only; junção de fronteira mesmo relógio preço/publicação.
389 testes passam na suíte completa (383 + 6 novos), zero regressão.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Nova Seção 6.1: a implementação, a precedência de exclusão, as duas tabelas
materializadas, o teste de aceite e a medição definitiva. Seção 12 (Fase 2) e Seção 13 (a
nota do piso setorial, antes só "22/27 direcional") atualizadas com o número real lado a
lado com o original.

## Pendente

- Série completa 2015-2026 de N e distribuição setorial — só 2016-02-29 remedido nesta
  rodada, por custo de ingestão (ver nota de performance abaixo). Direção esperada pelo
  padrão já observado (crescimento não-monotônico, vale em recessão) seguiria a mesma
  forma, mas não confirmada ano a ano ainda.
- De-para `SETOR_ATIV` (CVM, granular) → classificação B3 de nível 1 (produção) — sem
  isso, o piso setorial exato de produção continua sem número fixado, só a direção.
- Recuperação judicial sem fonte real — gate 4 da precedência nunca dispara nesta rodada.
- **Performance da ingestão**: savepoint-por-linha levou 299s (2015) e 399s (2016) para
  ~67 mil linhas cada — funcionalmente correto e verificado (contagem bate exatamente),
  mas lento demais para ingerir os 17 anos completos em produção. Padrão correto para
  quando isso for otimizado: lote com um commit por arquivo (ou por lote), não savepoint
  por linha — registrado como pendência isolada, não resolvido nesta rodada para não
  misturar mudança de mecanismo de escrita com validação de resultado na mesma passada
  (instrução explícita do usuário).

## Decisão

- Aprovado por: Brian — pediu a Seção 6 com três exigências (mesmo relógio, precedência
  de exclusão explícita, materialização com motivo registrado) e um teste de aceite
  nomeado (2016, `ITUB4`/`BBAS3`/`PETR4`, CNPJ+classe+filing corretos), mais a medição
  definitiva do piso setorial sobre código real. Depois de dois processos em background
  serem interrompidos na fronteira de sessão, alertou especificamente sobre o risco de
  savepoint-por-linha esconder ingestão truncada, e pediu verificação de contagem de
  linhas antes de confiar em qualquer número — seguido à risca antes de rodar a medição
  (2026-08-20).
- Justificativa: a mesma disciplina de "medir, não presumir" que fechou `EX` (Seção 5.3.2)
  e a fronteira 2015-2026 (Seção 5.6) se aplicou aqui — a divergência N=115 vs. 113 e
  40 vs. 27 setores não foi aceita por bater "aproximadamente", foi explicada eixo a eixo
  (identidade vs. cobertura de setor) antes de ser registrada como confirmação do achado
  original, não substituição por conveniência.
