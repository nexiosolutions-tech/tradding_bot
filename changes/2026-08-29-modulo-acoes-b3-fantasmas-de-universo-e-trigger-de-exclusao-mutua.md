# 2026-08-29 — Módulo de Ações: 59 linhas fantasma em `universo_elegivel`, corrigidas e travadas por trigger

## Contexto

Fechando a Fase 5 da migração para Postgres (`changes/2026-08-27-modulo-acoes-b3-
migracao-postgres-dados-validados-producao-pendente.md`), ficou uma divergência residual
registrada como pendência aberta: 2016 media 117/98 contra os 116/97 publicados na Seção
7.8 da spec — 1 empresa a mais no universo. O usuário pediu para não deixar isso em
aberto por muito tempo, citando o histórico da frente (73%→65%, GETI4, pico 210 vs 235):
nas três vezes anteriores, uma divergência de pequena magnitude escondia um bug real.
Assim foi desta vez também, só que maior: **1 unidade em 2016 escondia 59 linhas em 11
anos.**

## O mecanismo, confirmado, não hipotético

`CTAX11` (2016-02-29) estava presente **nas duas tabelas ao mesmo tempo**:
`universo_elegivel` (volume medido R$525.946) e `universo_exclusao` (motivo `iliquido`).
Recomputando a liquidez do zero para 2016, fora da tabela materializada: o piso
deflacionado por IPCA daquele ano é R$551.781,52 — `CTAX11` fica abaixo, deveria ser
excluído. A exclusão está certa; a elegibilidade é resíduo de antes da correção de IPCA
(Seção 7.8) ter sido aplicada — um reprocessamento posterior inseriu a exclusão correta
sem nunca apagar a linha antiga. Mesmo bug já registrado na Seção 7.7/7.8 ("reprocessar
sem limpar" zerou o universo de 2024 em silêncio), agora na direção inversa: em vez de
zerar, sobra.

**Escopo real, medido por join direto entre as duas tabelas** (`(data_decisao, ticker)`
presente nos dois lados): 59 pares, todos `motivo=iliquido`, em 11 das 12 datas-âncora da
série (2016-2026; só 2015 fica de fora, porque é a própria data-base do IPCA, onde a
razão de deflação é sempre 1 por definição). Por ano: 2016→1, 2017→2, 2018→3, 2019→2,
2020→5, 2021→3, 2022→4, 2023→10, 2024→9, 2025→9, 2026→10.

## Disciplina de investigação antes de tocar em dado (a pedido do usuário)

Não apagou-se nada até confirmar, caso a caso, qual lado do conflito estava certo:

1. **Todos os 59 confirmados**: volume recomputado fresco (não o persistido — os dois
   batem exatamente, sem corrupção de valor) contra o piso deflacionado do ano de cada
   par. Em **100% dos casos, `exclusao` está certa** (volume < piso) — zero casos na
   direção oposta. `motivo` uniformemente `iliquido` em todos os 59 — se fosse resíduo
   genérico de reprocessamento, seria esperado ver outros motivos também; não ver nenhum
   outro é evidência a favor da causa (IPCA), não contra.
2. **Veredito simulado antes de apagar** (query excluindo os pares fantasma do `COUNT`,
   sem tocar produção): recalculado universo + score computável para os 12 anos. O
   resultado bateu **exatamente com a Seção 7.8 publicada em 11 dos 12 anos**, nos dois
   números — prova independente de que a spec estava certa desde que foi escrita, e o
   banco materializado que divergiu depois, não o texto. **N≥100 continua reprovando só
   2016** (97 < 100) mesmo tirando até 10 fantasmas de 2023/2024/2026 — nenhum outro ano
   cruzou o piso.
3. **Única exceção**: 2023 bate no universo (200) mas o score computável simulado fica em
   177 contra os 178 publicados — 1 empresa, só no score. Investigado (ver seção
   dedicada abaixo) e não resolvido nesta rodada — pendência de prioridade baixa,
   registrada na spec.

## Correção aplicada (depois da simulação confirmar, não antes)

As 59 linhas de `universo_elegivel` apagadas — em **ambos** os bancos (Postgres `acoes`
via `railway ssh`, e o SQLite local `results/acoes.db`, que tinha exatamente os mesmos 59
pares, como esperado de uma migração byte-a-byte). Depois de apagar, os 12 anos
recalculados **de verdade** (não simulados) contra os dois bancos batem exatamente com os
números da simulação — mesma disciplina de validação já usada para a migração em si.

## Correção estrutural: trigger de exclusão mútua

`universo_elegivel` e `universo_exclusao` são mutuamente exclusivas por definição (Seção
6), mas nenhuma `UniqueConstraint` das duas tabelas impedia o mesmo par `(data_decisao,
ticker)` de existir nos dois lados — foi exatamente essa lacuna que permitiu o bug.
Adicionado em `models.py`: função + trigger `BEFORE INSERT` em Postgres (`plpgsql`,
`RAISE EXCEPTION ... USING ERRCODE = '23505'` — classificado como `unique_violation` de
propósito, para cair no mesmo tratamento de `IntegrityError` que o resto do módulo já usa)
e trigger equivalente em SQLite (`RAISE(ABORT, ...)`, que o driver `sqlite3` já classifica
como `IntegrityError` nativamente). **Nenhuma mudança de código de aplicação** —
`_excluir`/`build_universo_elegivel` já capturam `IntegrityError` como duplicata
rejeitada; o trigger só torna a inconsistência entre tabelas um caso a mais do mesmo
tratamento.

Validado nos dois sentidos, nos dois bancos: insert conflitante rejeitado como
`IntegrityError` (elegível depois de exclusão, e exclusão depois de elegível), insert
não-conflitante continua funcionando normalmente. Suíte completa (`--ignore=tests/
test_binance_ws_live.py -k acoes`): 136 passed, sem nenhuma adaptação de teste.

## Achado no processo, maior que a trigger em si: `after_create` não protege banco existente

**Correção (2026-08-29, rodada seguinte — `changes/2026-08-29-modulo-acoes-b3-reescrita-
em-lote-e-corte-de-producao.md`): o diagnóstico abaixo estava errado na causa, não no
sintoma.** O teste que "confirmou" a ausência da trigger em `results/acoes.db` chamava
`get_session_factory()` sem importar `tradingbot.acoes.models` — sem esse import, `Base.
metadata` fica vazio e `create_all` não faz nada, por *qualquer* motivo, não porque o
banco já existia. Descoberto ao investigar um crash real do `after_create` disparando
contra o Postgres (`RAISE EXCEPTION` da trigger colidindo com a formatação `%` do
`sqlalchemy.DDL()`) — isso só acontece se o evento *dispara*, contradizendo a conclusão
abaixo. A asserção de startup (`_assert_trigger_exclusao_mutua`, registrada abaixo)
continua correta e continua necessária — só a razão muda: não é "o evento não dispara
contra banco existente", é "nada garante que quem chama `get_session_factory()` importou
`models` primeiro". Texto original mantido abaixo, sem apagar, com esta nota no topo —
mesma disciplina da Seção 7.7 da spec (marcar como superado, não reescrever silenciosamente).

Registrada a trigger via `event.listen(Base.metadata, "after_create", ddl)`, esperando
que qualquer `create_all()` a aplicasse. Testado contra SQLite `:memory:` e contra a
suíte completa (136 testes) — passou, e quase foi aceito como "cobertura completa" nesse
teste. **Não é** (ver correção acima — a causa real não é esta). `after_create` (nível de
`MetaData`) só dispara quando `create_all` efetivamente cria tabela nova — contra um
banco que já existe (o `results/acoes.db` real e o `acoes` no Postgres, os dois já
populados antes desta mudança), o evento nunca dispara, e a trigger nunca seria aplicada
sozinha. Só descoberto ao checar deliberadamente o arquivo real (`sqlite_master` sem
nenhum trigger, depois de rodar `get_session_factory` contra ele) — o teste em memória
mascarava exatamente esse gap.

**Consequência, generalizada pelo usuário**: qualquer construção de schema registrada da
mesma forma (`event.listen(..., "after_create", ...)`) — trigger, constraint, índice —
nunca chega a um banco já populado. O sintoma é o pior possível: testes passam (banco
novo em memória), produção fica sem a proteção, silenciosamente. Segunda vez que uma
suposição sobre ambiente engana nesta frente (a primeira foi o caminho `results/` vs
`backend/results/`) — mas desta vez a consequência é mais séria, por ser silenciosa em
vez de um erro óbvio.

**Correção estrutural aplicada**: `persistence.py::_assert_trigger_exclusao_mutua`,
chamada ao final de `get_session_factory` (todo caminho de acesso ao banco passa por
ali). Consulta `pg_trigger`/`sqlite_master` pelas duas triggers esperadas; levanta
`RuntimeError` explícito se qualquer uma faltar — mesmo princípio do
`IngestionCountMismatchError` (a garantia não pode depender de alguém lembrar). Testado
nos dois sentidos: passa com a trigger presente, falha ruidosamente quando ausente
(simulado dropando a trigger manualmente depois de criada). Aplicado manualmente às duas
bases já existentes (Postgres `acoes` via SQL direto, SQLite local via
`executescript`) — a asserção de startup já confirma as duas protegidas agora.

**Pendência explícita, não resolvida nesta rodada**: um mecanismo de migração de schema de
verdade (Alembic ou equivalente). Sem ele, toda mudança de schema em banco existente
continua sendo manual — a asserção de startup transforma "esquecer" em "falha ruidosa no
boot", mas não elimina a necessidade de alguém aplicar a DDL à mão. Registrado como
próximo passo estrutural, não como bloqueio desta rodada.

## O 2023: divergência não explicada, do lado corrupção pelo critério da 7.8 — não pendência benigna

O usuário levantou que, se uma retificação da CVM com `dt_receb` anterior à data de
decisão for ingerida depois do cálculo original, a visão point-in-time daquela data muda
**legitimamente** — o arquivo mestre cresce, o passado fica mais completo, sem que isso
seja corrupção. Isso é uma propriedade real do sistema (Seção 5), registrada na Seção 7.8
com o critério de distinção explícito (mudança legítima vem com filing novo de `dt_receb`
compatível; corrupção não).

**Testado especificamente contra o caso de 2023** (score computável simulado 177 vs. 178
publicado): a hipótese **foi refutada, não apenas descartada por suposição**. Não houve
nenhuma ingestão de CVM entre a Seção 7.8 ter sido escrita (2026-08-26) e esta
investigação (2026-08-29) — conferido contra o histórico de `changes/` do período, só
migração e limpeza de dado, nenhum `cvm_ingestion` rodado.

**Isso muda a classificação, não só o status.** Sem filing novo, o próprio critério de
distinção que acabou de ser escrito na spec classifica esta divergência do **lado
corrupção**, não do lado mudança legítima — refutar a explicação plausível é o oposto de
fechar a pendência com uma história razoável, e é a mesma disciplina que já corrigiu a
explicação original do pico de universo (Seção 7.7: "provavelmente identidade não
resolvida" — era piso de histórico mínimo, não identidade). Relabeled explicitamente:
não é mais "pendência de baixa prioridade" (que soa a "provavelmente sem problema"), é
**"divergência não explicada, do lado corrupção pelo critério da 7.8"** — prioridade de
investigação continua baixa (1 empresa em 200, não muda nenhum veredito de N≥100), mas a
etiqueta não deve deixar a próxima pessoa tratar isto como resolvido. Precedente direto:
o achado inteiro desta rodada começou como uma única empresa (`CTAX11`, 2016) antes de
virar 59 linhas em 11 anos — a mesma magnitude pequena que o 2023 tem agora.

## Testes + suíte

136 testes (`-k acoes`) passaram após a mudança de modelo, sem adaptação. Nenhum teste
novo — a proteção é validada por scripts ad hoc contra os dois bancos reais (documentados
acima), não promovidos a `tests/` nesta rodada (mesma pendência já registrada de
scripts ad hoc não commitados).

## Decisão

- Aprovado por: Brian — pediu para não deixar a divergência de 2016 em aberto,
  investigar antes de apagar (revisar a lista, simular sem tocar produção, só então
  apagar e validar), e registrar a trigger de exclusão mútua como correção estrutural
  junto da migração (2026-08-29). Também identificou a lacuna do `after_create` como o
  achado mais importante da rodada, e pediu a asserção de startup como mitigação barata
  e imediata.
- Justificativa: o histórico desta frente mostrou três vezes que uma divergência pequena
  escondia um bug real — tratar a de 2016 como "resíduo aceitável" sem investigar teria
  deixado 59 linhas de corrupção em produção, silenciosamente, com o mesmo padrão de
  reincidência já visto (2024 zerado por reprocessar sem limpar). A trigger fecha a
  lacuna estrutural; a asserção de startup fecha a lacuna de como a trigger chega (ou
  não) a um banco existente.
