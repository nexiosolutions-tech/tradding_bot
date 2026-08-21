# 2026-08-20 — Módulo de Ações: preço bruto COTAHIST normalizado + eventos tipo+data

## Contexto

Com a camada de publicação (CVM) fechada e testada, usuário pediu o terceiro eixo
point-in-time — preço/eventos — antes dos itens financeiros genéricos, por dependência
(universo elegível da Seção 6 precisa de volume; o backtest inteiro precisa de retorno).
Mesma disciplina: verificar o layout real antes de desenhar o schema.

## Verificação que corrigiu a premissa: `FATCOT` não é o que se esperava

A hipótese inicial era que `FATCOT` (campo citado na Seção 5.3) seria parte do
mecanismo de ajuste corporativo. Baixado o layout oficial atual (o link antigo mudou de
domínio, `bvmf.bmfbovespa.com.br` → `b3.com.br`) e confirmado: `FATCOT` é **fator de
escala de cotação** (`1`=unitária, `1000`=lote de mil ações), não tem relação com
proventos/desdobramento. Verificado empiricamente, não só pelo texto — `VOLTOT/QUATOT`
(preço médio real do dia) bateu com `PREULT/FATCOT` para `FATCOT=1000` (`FNAM11`) e para
`FATCOT=10` (`SMLL11`, **valor que existe no dado real de 2024 mas não está documentado
em lugar nenhum do layout oficial**). Nenhum ticker do universo de ações propriamente
dito (`ESPECI` ON/PN/PR/OR/UNT) teve `FATCOT≠1` em 2024 — a armadilha é real, mas mora
majoritariamente em fundos/ETFs, fora do escopo da Seção 6.

## O sinal de evento real: `ESPECI`, com uma estrutura mais complexa que o esperado

O campo tokeniza por espaço: classe + sufixo "ex-" opcional (sempre começa com `E`) + tag
de segmento opcional (`NM`, `N1`...) — confirmado por inspeção byte a byte
(`'ON  EB  NM'` → `['ON','EB','NM']`), não por posição fixa, porque a tag de segmento
desloca onde o sufixo aparece dentro do campo de 10 caracteres.

Achado que exigiu correção de desenho: **o sufixo "ex-" persiste por vários pregões, não
marca um dia isolado**. Confirmado contra `ON EJ` do BBAS3, que durou ~8 pregões seguidos
em 2024. A regra de detecção corrigida: só a **primeira** data de uma nova sequência de
sufixo gera evento — comparação com o sufixo do pregão anterior do mesmo ticker, não
"todo dia com sufixo é um evento".

## Desdobramento confirmado sem marcador — e um sufixo não documentado

Vasculhada a tabela completa de `ESPECI`: existe `EG` (ex-grupamento, reverse split), não
existe equivalente para desdobramento (forward split) em nenhuma linha, documentada ou
observada. Um sufixo `EX` aparece no dado real (BBAS3, 2024-02-22) sem estar em lugar
nenhum do layout oficial — capturado como evento, tipo registrado como "não documentado"
em vez de adivinhado.

## Classificação de quebra de nível, testada contra preço real (não assumida)

Medido o efeito de cada sufixo real do BBAS3 em 2024:

| Sufixo | Variação medida | Classificação |
|---|---|---|
| EB (bonificação) | -50,57% | quebra de nível (mudança de quantidade sem caixa) |
| EJ (juros) | +0,65% | movimento de mercado normal |
| EDJ (dividendo+juros) | -3,53% | movimento de mercado normal |
| EX (não documentado) | -2,25% | movimento de mercado normal |

Regra: `is_level_break=True` só quando o sufixo contém `B` (bonificação) ou `G`
(grupamento) — a única categoria que mudou o preço de forma mecânica e desproporcional
ao que qualquer distribuição em caixa produziu no mesmo ticker, mesmo ano.

## O que foi implementado

`backend/src/tradingbot/acoes/cotahist_ingestion.py`: `normalize_price` (função pura,
`raw/100/FATCOT`), `parse_cotahist_year` (filtro de universo de ações reaproveitado da
Seção 6 — `CODBDI=02`, `TPMERC=010`, `ESPECI` ON/PN/PR/OR/UNT), `ingest_cotahist_year`
(append-only, mesmo padrão savepoint-por-linha do `cvm_ingestion.py`, detecção de evento
por transição). `models.py`: `CotahistPrice` (`UniqueConstraint(ticker, trade_date)`) e
`CorporateEventFlag` (`UniqueConstraint(ticker, event_date, ex_suffix)`).
`price_sanity.py`: `find_implausible_returns` — nenhum retorno diário deveria exceder um
limiar de plausibilidade (padrão 60%) sem uma quebra de nível conhecida explicando;
FATCOT mal normalizado ou evento não detectado produzem exatamente esse padrão, e a
função sinaliza em vez de deixar passar como dado de mercado normal.

## Testes (`backend/tests/test_acoes_cotahist_ingestion.py`), 7 no total

Fixture real: `tests/fixtures/cotahist/COTAHIST_A2024_real_extract.ZIP`, extrato de 8
registros reais do `COTAHIST_A2024.ZIP` baixado de `bvmf.bmfbovespa.com.br`, cobrindo as
transições reais `EB` e `EDJ` do BBAS3.

1. `normalize_price` bate com `VOLTOT/QUATOT` real (`FNAM11` FATCOT=1000, `SMLL11`
   FATCOT=10).
2. Filtro de universo exclui fundos/ETFs corretamente (`FNAM11`/`SMLL11` fora, só as 6
   linhas de `BBAS3` na fixture passam).
3. Append-only: segunda ingestão do mesmo arquivo rejeita as 6 linhas de preço.
4. `FATCOT=1` não altera o preço bruto (BBAS3 não teve escala não-unitária).
5. Evento gerado só na primeira data de cada sequência de sufixo — 2 eventos (não 6) nas
   6 linhas da fixture.
6. `EB` classificado como quebra de nível, `EDJ` não — a distinção testada, não só
   declarada.
7. Detector de retorno implausível: com o evento real presente, a queda de -50,57% não é
   acusada (evento explica); removido o evento (simula normalização/detecção que
   falhou), o mesmo retorno é acusado — prova que o detector reage à ausência do evento.

374 testes passam na suíte completa (367 + 7 novos), zero regressão.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Nova Seção 5.3.1: os três achados (FATCOT, ESPECI, desdobramento sem marcador), a tabela
de classificação de quebra de nível medida, o escopo refinado do gap de magnitude
(bloqueia só momentum, não valor/liquidez), as fontes de magnitude candidatas não
verificadas, e o que foi implementado. Seção 12 (fases) atualizada.

## Pendente

- Fonte de magnitude de proventos/desdobramento — bloqueia especificamente o fator de
  momentum (Seção 7), não o resto da Fase 1. Três candidatas registradas, nenhuma
  verificada: arquivo de proventos da própria B3, formulários CVM, FRE.
- Ingestão de todos os anos (2015-2026, a era avaliável) — só 2024 foi baixado e usado
  para a verificação e os testes nesta rodada.
- Itens financeiros genéricos (todos os tipos de demonstração) — Fase 2.
- `cnpj_ticker_map` (Seção 5.4/5.5/5.6) segue como spec, não como código.
- Nenhum código de produção liga preço + identidade + fundamento ainda — cada eixo
  point-in-time existe isolado, a composição fica para quando o universo elegível
  (Seção 6) for implementado de fato.

## Decisão

- Aprovado por: Brian — "o primeiro passo é o de sempre — olhar o layout real da
  COTAHIST e confirmar que dá para separar bruto de evento... antes de desenhar o
  schema" (2026-08-20), seguido por uma segunda rodada de instrução detalhada depois da
  verificação corrigir a premissa do FATCOT: normalizar por FATCOT como obrigatório antes
  de qualquer coisa tocar o preço, distinguir quebra de nível de movimento de mercado
  real, refinar o escopo do gap de magnitude por família de fator (não bloqueio
  genérico), e substituir o teste de aceite de desdobramento (não certificável só com a
  COTAHIST) por um teste de sanidade de retorno implausível.
- Justificativa: a verificação achou o FATCOT fazendo algo diferente do assumido — supor
  a hipótese original e implementar em cima dela teria produzido normalização errada
  silenciosa exatamente no tipo de papel (fundos/ETFs de baixo valor) onde a escala mais
  varia. A estrutura real do ESPECI (persistência multi-pregão, tag de segmento
  embutida) também divergia do que uma leitura só do texto do layout sugeriria — corrigido
  antes de gerar eventos duplicados.
