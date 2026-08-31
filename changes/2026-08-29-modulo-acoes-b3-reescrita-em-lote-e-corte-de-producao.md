# 2026-08-29 — Módulo de Ações: reescrita em lote, Fase 4 destravada

## Contexto

Fecha o que a migração para Postgres deixou pendente (`changes/2026-08-27-...`): `build_
decisao` levava 150-350x mais tempo contra Postgres que contra SQLite, bloqueando a Fase
4 (corte de produção). O comando desta rodada pediu, nesta ordem: medir antes de
reescrever, reescrever para acesso em lote sem mudar regra de negócio, validar contra as
doze datas-âncora, e então ligar produção — com o mecanismo de migração de schema
deliberadamente adiado (não bloqueia produção).

## Fase 1 — Medição, antes de qualquer linha de código mudar

Instrumentado `build_decisao` (hooks `before_cursor_execute`/`after_cursor_execute` do
SQLAlchemy) contra o Postgres real, para 2016-02-29:

- **3.438 round trips ao banco**, somando 300,82s de 341,23s de parede (88%) — a
  hipótese de N+1 explicava a maior parte do tempo, não uma minoria. Sem isso confirmado,
  a reescrita teria atacado a coisa errada — mesma disciplina que evitou otimizar o
  parser errado na COTAHIST.
- **Distribuição**: fundamento (DRE/BP/DFC) 48,6% do tempo em banco (1.676 consultas);
  "outro" 24,6% (856 consultas — investigado e identificado como `SAVEPOINT`/`ROLLBACK
  TO SAVEPOINT`/`RELEASE SAVEPOINT`, do padrão de uma `session.begin_nested()` por
  candidato em `build_universo_elegivel`, 428 candidatos × 2); preço/liquidez 19,8% (662
  consultas); identidade 3,6%; setor 3,4%.
- **Achado dentro do achado**: `get_ebitda_as_of`, `get_divida_liquida_as_of`,
  `get_lucro_liquido_controladores_as_of` e `get_patrimonio_liquido_controladores_as_of`
  cada uma chamava `get_latest_filing_as_of` de novo, independentemente — até 4
  resoluções do mesmo filing por empresa. Redundância *dentro* de uma empresa, não só
  *entre* empresas — explicava por que "fundamento" concentrava quase metade do tempo.
- **Sonda de latência pura** (`SELECT 1`, mesma conexão reaproveitada, 50x): média
  87,73ms, mínimo 84,94ms — descarta reabertura de conexão/renegociação de SSL por
  query (variância seria alta, não um piso quase constante). A causa real: **`tradding_
  bot` está em `europe-west4-drams3a`, o Postgres em `us-east4-eqdc4a`** — travessia
  intercontinental real, mesmo em rede privada. **Não corrigido nesta rodada** — a
  posição do bot na Europa é quase certamente o que dá acesso à Binance sem
  geobloqueio (`us-east4` é bloqueado, Holanda passa); mover o bot quebraria a execução
  de ordens para ganhar uma tela mais rápida. Registrado como achado para a próxima
  rodada: serviço próprio para `acoes/api.py` em `us-east4`, já que o módulo não tem
  nenhuma dependência da Binance (só CVM/B3/BCB) — ver Seção 11.12 da spec.

## Fase 2 — Reescrita em lote

Padrão eliminado: uma consulta por candidato → uma consulta por *tipo de dado*, para o
universo inteiro de uma vez. Nenhuma regra de negócio mudou — as mesmas cinco regras de
exclusão (Seção 6), a mesma matriz de aplicabilidade, as mesmas três categorias de
ausência, a mesma hierarquia de demeaning setorial (Seção 7). O que mudou é só como o
dado chega à memória:

- **Identidade** (`cnpj_ticker_map.py::get_cnpj_as_of_lote`) — uma consulta com
  `ticker IN (...)`, agrupamento em Python reproduzindo o `ORDER BY data_inicio_
  vigencia DESC LIMIT 1` por ticker.
- **Preço/liquidez** (`universo_elegivel.py::volume_mediano_as_of_lote`,
  `contagem_pregoes_lote`; `decisao.py::preco_as_of_lote`) — `ROW_NUMBER() OVER
  (PARTITION BY ticker ORDER BY trade_date DESC)`, uma consulta para todos os
  candidatos, reproduzindo exatamente o `LIMIT` por ticker (não uma aproximação por
  janela de calendário, que poderia cortar pregões de um ticker com histórico
  intermitente e mudar a mediana).
- **Setor B3** (`b3_setor.py::get_latest_b3_classification_lote`) — `cnpj IN (...)`,
  agrupamento por `data_coleta` máxima.
- **Fundamento** (`pointintime.py::get_latest_filing_as_of_lote`,
  `get_line_items_lote`) — resolve o filing de **todas** as empresas de uma vez
  (`ROW_NUMBER() OVER (PARTITION BY cnpj_cia ORDER BY dt_refer DESC, versao DESC)`),
  depois busca **todas** as linhas `ordem_exerc='ÚLTIMO'` de todos os filings resolvidos
  numa única consulta (`tuple_(cnpj, dt_refer, versao) IN (...)`). `fatores.py` ganhou
  seis extratores puros (`_extrair_eps`, `_extrair_ebit`, `_extrair_da`, `_extrair_
  divida_liquida`, `_extrair_lucro_liquido_controladores`, `_extrair_patrimonio_
  liquido_controladores`) que operam sobre essas linhas já em memória — mesma regra de
  cada função `as_of` original (mesmo filtro de `cd_conta`/`ds_conta`/`startswith`/
  `base`, mesma dedução via `_unica_por_conteudo`), só sem voltar ao banco. As funções
  `as_of` single-item originais (`get_eps_as_of`, `get_ebit_as_of` etc.) continuam
  existindo, inalteradas, para quem ainda as chama isoladamente (testes).
- **Escrita** (`universo_elegivel.py::_insert_lote_ignorando_duplicata`) — troca `session.
  begin_nested()` por candidato por um `INSERT ... ON CONFLICT DO NOTHING` em lote (uma
  chamada para todos os excluídos, uma para todos os aceitos), dialeto-específico
  (`postgresql`/`sqlite`). Reprocessar uma data já materializada continua ignorando
  silenciosamente o que já existe (mesmo comportamento). **Mudança de comportamento real
  e deliberada**: a trigger de exclusão mútua (`changes/2026-08-29-modulo-acoes-b3-
  fantasmas-...`) agora falha o **lote inteiro** se algum candidato colidir com o lado
  oposto, em vez de isolar só aquela linha como antes (`SAVEPOINT` por candidato dava
  isolamento por linha). Verificado empiricamente (não só argumentado): dentro de uma
  única execução de `build_universo_elegivel`, um candidato nunca é tentado nos dois
  lados (a precedência de exclusão garante um caminho só) — o conflito só pode vir de
  uma corrupção *pré-existente* de uma execução anterior, exatamente o que a trigger
  existe para pegar. Testado diretamente: corrompido um par `(data_decisao, ticker)`
  artificialmente numa cópia de teste e confirmado que `build_universo_elegivel`
  propaga `IntegrityError` para o lote inteiro, não silencia.

**Achado durante a implementação, não previsto**: a trigger de exclusão mútua
(`models.py::_TRIGGER_FUNCAO_POSTGRES`) tinha um bug latente — o texto do `RAISE
EXCEPTION 'ticker % ...'` usa `%` como placeholder do próprio `plpgsql`, mas
`sqlalchemy.DDL()` trata `%` como formatação de string Python por padrão, e crasha
(`ValueError: unsupported format character`). Nunca tinha sido exercitado: a aplicação
manual anterior (via `psql -f`, fora do SQLAlchemy) nunca passou por esse caminho, e os
testes contra SQLite não têm `%` na trigger equivalente. Só apareceu ao rodar `get_
session_factory` contra Postgres nesta rodada. Corrigido escapando como `%%` (convenção
padrão do operador `%` do Python) — testado que o resultado final enviado ao Postgres
tem `%` simples, não `%%` nem crash.

**Achado colateral sobre o próprio achado do `after_create`**: ao investigar o crash
acima, ficou claro que o `after_create` da `MetaData` **dispara mesmo incondicionalmente
em todo `create_all()`**, não só quando uma tabela é criada pela primeira vez — contrário
ao que o registro de 2026-08-29 (`changes/...fantasmas-de-universo...`) concluiu. Essa
conclusão anterior vinha de um teste com um erro real: o script que "confirmou" a
ausência da trigger em `results/acoes.db` chamava `get_session_factory()` sem nunca
importar `tradingbot.acoes.models` — sem esse import, `Base.metadata` fica vazio,
`create_all` não faz nada, e nenhuma trigger é criada por *qualquer* motivo, não porque
o banco já existia. A asserção de startup (`_assert_trigger_exclusao_mutua`) continua
correta e continua valendo como proteção — só a explicação de *por que* ela é necessária
muda: não é "o evento não dispara contra banco existente", é "nada garante que quem
chama `get_session_factory()` importou `models` primeiro". Registrado aqui para não
repetir a mesma alegação errada — o comportamento real do `after_create` segue não
totalmente re-verificado em todas as combinações (dialeto × schema pré-existente), e a
asserção de startup é a rede de segurança correta independente da causa exata.

## Fase 3 — Validação

**Correção**, `build_decisao` contra Postgres, doze datas-âncora, contagem exata exigida
contra os números pós-limpeza (`changes/2026-08-29-...fantasmas...`):

| Ano | Universo/Score | Bate | Tempo | Ano | Universo/Score | Bate | Tempo |
|---|---|---|---|---|---|---|---|
| 2015 | 128/104 | OK | 3,38s | 2021 | 174/152 | OK | 4,88s |
| 2016 | 116/97 | OK | 2,82s | 2022 | 190/172 | OK | 5,10s |
| 2017 | 127/104 | OK | 3,24s | 2023 | 200/177 | OK | 7,71s |
| 2018 | 132/112 | OK | 3,52s | 2024 | 196/186 | OK | 8,57s |
| 2019 | 144/120 | OK | 3,85s | 2025 | 181/168 | OK | 8,83s |
| 2020 | 164/143 | OK | 4,76s | 2026 | 168/156 | OK | 7,53s |

**Doze de doze batem exatamente.** Nenhum ajuste de código foi feito para forçar
correspondência — os números já batiam na primeira execução da versão em lote.

**Performance, antes/depois** (2016-02-29, mesma instrumentação da Fase 1):

| | Antes | Depois | Fator |
|---|---|---|---|
| Round trips | 3.438 | 13 | 264x menos |
| Tempo de parede | 341,23s | 4,12s | 83x mais rápido |
| Tempo em banco | 300,82s | 3,59s | 84x menos |
| "fundamento" (consultas) | 1.676 | 2 | 838x menos |
| `SAVEPOINT`/nested tx | 856 | 0 | eliminado |

**Meta cumprida com folga** — todas as doze datas abaixo de 10s, a maioria abaixo de 5s
(2020-2026 sobem para 4,8-8,8s, proporcional ao universo maior desses anos, esperado).

**Regressão**: suíte completa (`--ignore=tests/test_binance_ws_live.py`), 499 testes,
passou sem nenhuma adaptação, antes e depois da correção do `%%`.

## Fase 4 — Corte de produção

`acoes/api.py` já lê `ACOES_DATABASE_URL` via `persistence.py::get_engine` — nenhuma
mudança de código nas rotas foi necessária para a conexão em si, só a variável de
ambiente em produção. `ModuleSwitch`/`App.tsx` já checam `/api/acoes/disponivel`
dinamicamente no carregamento — nenhuma mudança de frontend necessária para reabilitar
a aba; ela se habilita sozinha quando a rota responde `disponivel: true`. Confirmado
contra produção real: `disponivel: true`, deploy estável (`state: online`).

**Achado real durante a navegação das telas, não previsto pelo comando**: `/api/acoes/
mes-atual` levou **4min55s** na primeira medição real contra produção — `build_decisao`
já em lote (confirmado, ~4-9s), mas a **camada de apresentação da API tinha o mesmo
N+1, numa camada diferente**. `_empresa_para_ranking` (usada por "Mês atual" e
"Histórico") chamava `get_latest_filing_as_of`/`get_eps_as_of`/`get_divida_liquida_as_
of`/`get_ebitda_as_of`/`get_lucro_liquido_controladores_as_of`/`get_patrimonio_liquido_
controladores_as_of`/`preco_as_of` uma vez **por empresa do ranking**, para expor o
valor bruto por trás de cada percentil que `build_decisao` já tinha computado mas não
devolvia — desenho original deliberado ("nunca reimplementa a extração, só materializa
o que falta"), mas que reimplementava a *consulta*, não a *lógica*, empresa por empresa.
Mesmo padrão do achado da Fase 1, camada diferente.

**Corrigido com o mesmo material da Fase 2**: `pointintime.py` ganhou `existe_algum_
item_lote` (mesma checagem de `versao_indisponivel`, em lote — precisa ser uma consulta
separada de `get_line_items_lote`, porque não filtra por `ordem_exerc`, e misturar os
dois filtros apagaria a distinção entre "filing sem nenhum item" e "filing com item, só
não o ÚLTIMO"); `cnpj_ticker_map.py` ganhou `get_fonte_identidade_as_of_lote`. `api.py`
ganhou `_DossieRanking`/`_montar_dossie_ranking` (busca tudo uma vez para o ranking
inteiro) e `_detalhe_*`/`_selo_identidade` passaram a consumir esse dossiê em memória,
via os extratores puros de `fatores.py` já criados na Fase 2 — nenhuma lógica nova,
reuso do que já existia. `_retorno_carteira_topo_ou_base` (tela Histórico, 8 chamadas
por requisição) tinha o mesmo padrão para preço — batido numa função companheira,
`_precos_topo_base_por_data`, reduzindo de até 160 consultas individuais para 5.

**Validado por equivalência, não só por não quebrar**: script ad hoc comparando, para
196 empresas reais de 2024-02-29, o valor de cada `_detalhe_*`/`_selo_identidade` pela
via antiga (consulta individual) contra a via nova (dossiê em lote) — **zero
divergências**. Suíte completa (499 testes) segue passando sem adaptação.

**Resultado**: `/api/acoes/mes-atual` volta a responder dentro da meta depois da
correção (medido após o redeploy, ver seção seguinte).

## O que não foi feito nesta rodada (registrado, não esquecido)

- **Região do `tradding_bot`**: não movida. Achado da Fase 1 (travessia intercontinental
  Europa↔EUA) registrado como próxima rodada — serviço próprio para `acoes/api.py` em
  `us-east4`, ao lado do Postgres, preservando `tradding_bot` na Europa (acesso à
  Binance). Antes de mover, confirmar que CVM/B3/BCB respondem de `us-east4` (Fase 0.1
  do comando de migração original, vale reconfirmar do container novo).
- **Mecanismo de migração de schema** (Alembic ou equivalente): adiado por decisão
  explícita desta rodada — não bloqueia produção. Continua registrado como pendência
  estrutural.
- **2023** (divergência de 1 no score computável, `changes/2026-08-29-...fantasmas...`):
  não investigado, como pedido.
- Pendências do EPS (causa raiz na ingestão, `PDGR3`, bug do `winsorize`): não tocadas.

## Decisão

- Aprovado por: Brian — comando completo para esta rodada ("Comando — Reescrita em lote
  e corte de produção do módulo de Ações", 2026-08-29), com a ordem explícita de medir
  antes de reescrever, não mudar regra de negócio, validar contra as doze âncoras antes
  de qualquer coisa, e então ligar produção.
- Justificativa: o achado de round trips (88% do tempo) confirmado por medição real, não
  suposição, autorizou a reescrita. A reescrita em lote resolveu o problema por conta
  própria (83x, folgadamente dentro da meta de 10s) mesmo sem tocar na causa de fundo da
  latência por round trip (a travessia intercontinental) — os dois achados se
  multiplicam, mas nenhum dependia do outro para fechar esta rodada.
