# 2026-08-20 — Módulo de Ações: `EX` medido na população inteira (N=73, 2010-2026)

## Contexto

A rodada anterior deixou `EX` registrado como "não documentado, comportamento presumido"
a partir de um único caso real (BBAS3, -2,25%). Usuário pediu a medição completa antes de
seguir para a Seção 6: contar todas as ocorrências no histórico disponível e olhar a
distribuição inteira, não uma amostra — com três resultados possíveis pré-especificados
(ruído puro, cauda de quebra de nível, ou bimodal exigindo decisão caso a caso) e a ação
já definida para cada um.

## Medição: 17 anos de COTAHIST, população inteira de `EX`

Baixados todos os anos de 2010 a 2026 (11 já estavam no scratchpad, 10 baixados nesta
rodada). Toda transição `ON→...EX...` do universo de ações (mesmo filtro da Seção 6:
`CODBDI=02`, `TPMERC=010`, `ESPECI` ON/PN/PR/OR/UNT) contabilizada — 73 ocorrências no
total, não uma amostra bienal como as medições anteriores desta frente.

## Resultado: nem ruído puro, nem bimodal limpo — o terceiro cenário

| Faixa | N | % |
|---|---|---|
| dentro de ±5% | 49 | 67,1% |
| entre 5% e 33% | 20 | 27,4% |
| ≥ 33% em módulo | 4 | 5,5% |

Min=-80,96%, max=+4,86%, mediana=-2,37%. Os 4 casos extremos: `CEBR6`/`CEBR3`/`CEBR5` (as
três classes da mesma empresa, mesmo dia — 2021-10-18, -80,96%/-80,35%/-80,12%) e `VIVT3`
(2025-04-15, -50,08%). **Vão real na cauda**: nenhum caso entre -22,54% (`CGAS5`,
2019-12-10) e -50,08% (`VIVT3`) — a distribuição não é contínua ali, há um buraco
genuíno na amostra.

## Decisão: tratamento conservador para rótulo ambíguo

Nem o cenário "seguro" (que dispensaria ação) nem o cenário "sempre quebra" (que
reclassificaria `EX` como `B`/`G`) se sustentam nos dados. Aplicado o terceiro cenário
pré-especificado: `is_level_break` de `EX` não é decidido pelo sufixo sozinho — é
decidido **caso a caso pelo retorno do próprio dia**, limiar `|retorno| ≥ 0,33`, dentro
do vão real da distribuição (não escolhido por conveniência, o vão existe entre -22,54%
e -50,08%, o limiar cai dentro dele com folga nos dois lados).

## O que foi implementado

`backend/src/tradingbot/acoes/cotahist_ingestion.py`: `_is_level_break` ganhou um segundo
parâmetro (`pct_change`), `EX_LEVEL_BREAK_THRESHOLD = 0.33` como constante nomeada e
documentada com a origem do número. `ingest_cotahist_year` passou a rastrear o preço de
fechamento anterior por ticker (`last_close_by_ticker`) para calcular o retorno do dia da
transição e decidir a classificação de `EX` no momento da detecção do evento.

## Testes novos, 2 casos reais nos extremos da distribuição

`test_ex_leve_nao_e_quebra_de_nivel`: BBAS3, 2024-02-22, -2,25% — abaixo do limiar, não é
quebra (fixture estendida com as linhas reais de 2024-02-21/22).

`test_ex_extremo_e_quebra_de_nivel`: VIVT3, 2025-04-15, -50,08% — um dos 4 casos reais que
cruzam o limiar, é quebra. Nova fixture `COTAHIST_A2025_real_extract.ZIP` (a COTAHIST é um
arquivo por ano, o caso real mais decisivo caiu num ano diferente do já usado).

Testes existentes atualizados para os novos totais da fixture 2024 (8 linhas, 3 eventos —
`EX`/`EB`/`EDJ` — em vez de 6/2). 376 testes passam na suíte completa (374 + 2 novos),
zero regressão.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Nova Seção 5.3.2: a medição completa (tabela de faixas, os 4 casos extremos nomeados, o
vão real da distribuição), a decisão do tratamento caso a caso, e o que continua em
aberto (o tipo exato de `EX` segue não documentado — só o comportamento de preço foi
medido). Seção 5.3.1 ajustada para apontar à 5.3.2 em vez de fechar `EX` como "movimento
normal" a partir de um caso só.

## Pendente

- O tipo semântico exato de `EX` continua desconhecido — só o efeito de preço foi medido
  e usado para classificação, não uma explicação do que o código significa.
- Ingestão dos 17 anos completos (2010-2026) para produção — nesta rodada, baixados e
  escaneados só para a medição, não persistidos via `ingest_cotahist_year`.
- Próximo passo, conforme instrução do usuário: Seção 6 (universo elegível), primeiro
  artefato que junta as três fundações point-in-time (identidade, publicação, preço).

## Decisão

- Aprovado por: Brian — pediu a contagem completa e a distribuição inteira antes de
  seguir, com os três cenários e a ação de cada um pré-especificados ("Se todas ficarem
  na faixa de ruído... Se houver uma cauda... Se a distribuição for bimodal... o
  tratamento conservador é marcar como quebra sempre que o retorno daquele dia cruzar um
  limiar, caso a caso") e a instrução de registrar N e a distribuição, não "parece ok"
  (2026-08-20).
- Justificativa: um único caso (o BBAS3 da rodada anterior) não permitia distinguir entre
  os três cenários — a medição completa achou o terceiro, o mais trabalhoso de tratar
  corretamente, e a mesma disciplina que corrigiu 73%→65% na reconciliação de identidade
  se aplicou aqui: medir a população, não presumir a partir de uma amostra de um.
