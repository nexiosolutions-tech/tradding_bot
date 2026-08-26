# 2026-08-26 — Módulo de Ações: ingestão COTAHIST em lote (526s → 22s), asserção de contagem, índice as-of

## Contexto

Pendência de performance registrada desde a Seção 6.1 (`ingest_cotahist_year`,
savepoint-por-linha, ~300-400s/ano) e reafirmada nas duas rodadas anteriores como
bloqueador da série completa 2015-2026. Usuário pediu, antes de otimizar: medir onde o
tempo vai (parsing, I/O ou transação) em vez de assumir que é o commit; e, ao trocar o
mecanismo de escrita, atenção a dois riscos que o batch introduz — falha parcial de lote
(uma linha ruim pode derrubar ou pular o lote inteiro, não só a linha) e idempotência
(reingestão frequente de um ano precisa continuar segura). Pediu também confirmar que a
asserção de contagem lê do banco pós-commit, não de um contador em memória (que mentiria
exatamente no caso que a asserção existe para pegar), e verificar índices as-of para
`CotahistPrice`/`CvmFinancialLineItem` antes do backtest completo (~130 datas de decisão).

## Medido antes de otimizar

`COTAHIST_A2016.ZIP` real (66.706 linhas de equity, mesmo arquivo já usado nas rodadas
anteriores):

| Etapa | Tempo |
|---|---|
| Parsing puro (sem banco) | 6,69s |
| Ingestão completa (parsing + savepoint-por-linha + commit) | 526,27s |

Banco, não parsing, é >98% do custo. O processo passa a maior parte do tempo em estado
`D` (espera de I/O), consistente com overhead de transação por `SAVEPOINT` — SQLite só
faz `fsync` no commit externo, não por savepoint, então o custo não é disco por linha, é
overhead de ORM/transação por `INSERT` isolado. Confirma a suspeita registrada nas rodadas
anteriores sem precisar assumi-la.

## Idempotência: já garantida estruturalmente, confirmado antes de mudar qualquer coisa

`CotahistPrice` já tem `UniqueConstraint(ticker, trade_date)` — mesmo padrão de
`CvmFiling`. Reingestão de um ano já era segura antes desta rodada; não precisou de
mudança.

## O que foi implementado

`backend/src/tradingbot/acoes/cotahist_ingestion.py`:

- `ingest_cotahist_year` insere preços em **lote** (`PRICE_BATCH_SIZE = 2000`), uma
  savepoint por lote em vez de por linha.
- `_flush_price_batch`: caminho comum é o lote inteiro num `INSERT` só; **só se o lote
  falhar** (duplicata real de reingestão, ou qualquer violação de integridade), refaz
  aquele lote específico linha por linha — isola a linha problemática sem pagar
  savepoint-por-linha no caso comum, e sem nunca descartar uma linha em silêncio.
- Eventos societários (`CorporateEventFlag`) continuam savepoint-por-linha — algumas
  centenas por ano, nunca foram o custo medido, não valia complicar o caminho comum.
- `IngestionCountMismatchError`: depois do commit final, conta via `SELECT` no banco
  quantos preços foram persistidos no intervalo de datas do arquivo e compara contra a
  contagem de chaves `(ticker, trade_date)` distintas vistas no parsing — **lê do banco,
  não de um contador em memória**, porque um contador mentiria exatamente no caso que
  esta asserção existe para pegar (falha parcial de lote). Dispara com mensagem
  informativa se não bater.

`backend/src/tradingbot/acoes/models.py`: `CvmFinancialLineItem` ganhou
`ix_cvm_financial_line_items_as_of (cnpj_cia, dt_refer, versao)`.

## Resultado, mesmo arquivo, mesma máquina

526,27s → **22,35s** (≈23,5×). Contagens idênticas nos dois lados (66.706 preços
inseridos, 646 eventos inseridos, zero duplicata rejeitada) — confirma que o lote não
mudou o resultado, só o caminho de escrita.

## Índices as-of: um faltava, um já existia — verificado, não assumido em nenhuma direção

`EXPLAIN QUERY PLAN` contra a consulta real de fator (`cnpj_cia=? AND dt_refer=? AND
versao=?`) mostrou o SQLite usando só o índice de `dt_refer` (baixa seletividade — todas
as empresas reportam nas mesmas poucas datas de referência) antes da mudança, e o índice
composto novo depois. Já para `CotahistPrice`, o mesmo comando mostrou o SQLite **já**
usando o índice único implícito de `UniqueConstraint(ticker, trade_date)` para a consulta
as-of de preço — nenhuma mudança feita ali, porque um índice composto novo seria
redundante (custo de escrita extra sem ganho de leitura, na própria rotina que este
trabalho acabou de acelerar).

## Testes novos

`backend/tests/test_acoes_cotahist_ingestion.py`: 3 testes novos —
`test_ingest_em_lote_com_batch_size_pequeno_insere_tudo` (múltiplos lotes, nada perdido),
`test_lote_com_uma_duplicata_isola_so_a_linha_duplicada` (lote misto, fallback separa
corretamente), `test_contagem_pos_commit_detecta_descarte_silencioso_de_linha` (simula o
próprio bug que a asserção existe para pegar via monkeypatch, prova que ela dispara — não
basta confiar que o código nunca vai regredir para esse padrão). 12/12 testes do arquivo
passam; suíte completa (`--ignore=tests/test_binance_ws_live.py`): **425 passed**.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Seção 6.2: pendência de performance substituída pelo relato da otimização — números
antes/depois, design do fallback de lote, a asserção e por que lê do banco, e a
verificação (não suposição) dos índices as-of nos dois modelos, nas duas direções
(adicionar onde faltava, não adicionar onde já havia).

## Pendente

- Série completa 2015-2026 de N e distribuição setorial — agora praticável em custo de
  ingestão (~22s/ano em vez de ~526s/ano); é o próximo passo da sequência já registrada
  pelo usuário (piso de cobertura → diagnóstico bancário → série completa), com os dois
  primeiros itens já fechados nas rodadas anteriores.
- Recalibração de N=100 (Seção 7.5/10) e distribuição do universo com score computável ao
  longo do ciclo — ambos dependem da série completa e ficam baratos depois que ela existir
  (nota do usuário: enfileirar antes do backtest em si).

## Decisão

- Aprovado por: Brian — pediu medição antes de otimizar em vez de assumir a causa (mesma
  disciplina já aplicada ao `EX`/`FATCOT`/`3.05` nesta spec), atenção a falha parcial de
  lote como um segundo modo de falha distinto de truncamento, confirmação de idempotência
  na tabela de preço, e verificação de índices as-of nos dois modelos antes do backtest
  completo (2026-08-26).
- Justificativa: medir antes confirmou que o custo é quase inteiramente transação, não
  parsing nem I/O bruto — evitou otimizar a coisa errada (ex.: paralelizar parsing não
  teria ajudado). Verificar os índices nas duas direções (empiricamente, via `EXPLAIN
  QUERY PLAN`) achou exatamente um caso real de cada: um índice faltando
  (`CvmFinancialLineItem`) e um já coberto implicitamente (`CotahistPrice`) — assumir
  qualquer uma das duas direções sem checar teria produzido ou uma lacuna de performance
  não corrigida, ou um índice redundante desacelerando a própria rotina que este trabalho
  otimizou.
