# 2026-08-27 — Módulo de Ações: migração de dados para Postgres validada, Fase 4 (produção) explicitamente pendente

## Contexto

Executado `specs/comando-migracao-acoes-postgres.md`, autorizado pelo usuário ("Sim dê
inicio à implementação"). O comando previa 5 fases. As Fases 0-3 (verificação, schema,
dados, validação) foram concluídas com sucesso. A Fase 4 (corte de produção) foi
explicitamente interrompida antes de começar, por decisão do usuário, ao surgir um
achado de performance que muda o escopo do que falta. Este `changes/` fecha a Fase 5
(registro) com os três achados desta rodada — dois deles não previstos no comando
original.

## Fase 0 — Verificações

- **0.1 Rede**: `dados.cvm.gov.br` e o endpoint de classificação setorial da B3
  respondem de dentro do container Railway (`railway ssh`, `python3 -c` com
  `urllib.request` — o container não tem `curl`). Nenhuma restrição de rede encontrada
  para este módulo (diferente do que já aconteceu com a Binance).
- **0.2 Isolamento**: banco lógico separado (`acoes`) no mesmo serviço Postgres
  gerenciado que o bot já usa no Railway — não schema, não prefixo de tabela. Mesmo
  padrão de isolamento físico que os dois módulos já mantêm em SQLite (bancos de arquivo
  distintos), sem mudança de código além da string de conexão. Zero estado ou schema
  compartilhado com o bot, conforme `CLAUDE.md`.
- **0.3 Capacidade**: volume de 4,6G, 159MB em uso antes da migração. ~539MB do SQLite
  local (mais índices, que pesam mais em Postgres) cabiam com folga confortável.

## Fase 1 — Schema

Todas as garantias de unicidade/append-only portadas (`CvmFiling`, `CotahistPrice`,
`UniversoElegivel`, índice composto de `CvmFinancialLineItem`). As três consultas as-of
(identidade, publicação, preço) e o índice composto verificados via `EXPLAIN ANALYZE`
real no Postgres — todos usando `Index Scan`/`Bitmap Index Scan`, sub-milissegundo cada.
Nenhum índice que servia no SQLite deixou de ser usado no Postgres.

**Achado real de tipo, corrigido na origem**: `CotahistPrice.quantity` (`QUATOT`) estourava
`integer` (int4, ~2,1 bilhões) do Postgres — 53 linhas reais na série 2015-2026, até
48,7 bilhões (`AZUL53`, papel muito diluído/pós-reestruturação). SQLite aceita qualquer
inteiro sem checagem de faixa; Postgres não. Corrigido no modelo (`Integer` → `BigInteger`
em `models.py`, com comentário explicando a origem do achado), não só contornado na
migração — nenhum outro `Integer` do módulo (`versao`, `fatcot`, `checked_year`) tinha
risco equivalente (verificado empiricamente, `MAX`/`MIN` por coluna). Suíte completa
(499 testes) re-rodada depois da mudança de tipo, sem adaptação de teste.

## Fase 2 — Dados

Carga em lote (`COPY ... FROM STDIN`, `psycopg2`, `copy_expert`, 20 mil linhas por lote),
em primeiro plano, progresso por tabela. Asserção de contagem obrigatória, SQLite vs.
Postgres, por tabela — todas batendo exatamente:

```
cvm_filings: 12881 / 12881
cvm_financial_line_items: 1742542 / 1742542
cotahist_prices: 999756 / 999756
corporate_event_flags: 21984 / 21984
cnpj_ticker_map: 691 / 691
unresolved_tickers: 63 / 63
universo_elegivel: 2701 / 2701
universo_exclusao: 4614 / 4614
b3_industry_classification: 97 / 97
ipca_indice: 139 / 139
cdi_taxa: 2922 / 2922
TOTAL: 2788390 / 2788390
```

Banco `acoes` final: 528MB (vs. 539MB do arquivo SQLite — provavelmente compactação de
TOAST/reindexação, sem overhead de página livre acumulada do SQLite).

## Fase 3 — Validação: migração correta, âncora do próprio comando estava errada

`build_decisao` rodado para as duas datas-âncora do comando, contra Postgres via rede
privada do Railway:

| Ano | Universo (Postgres) | Score computável (Postgres) | Tempo |
|---|---|---|---|
| 2015-02-27 | 128 | 104 | 362,1s |
| 2016-02-29 | 117 | 98 | 343,0s |

Os quatro números **divergiam** da tabela do comando (125/106 em 2015, 115/98 em 2016).
Pela regra do próprio comando ("pare e investigue antes de prosseguir — não ajuste o
código até bater"), a investigação foi contra a fonte, não contra o resultado: rodar o
mesmo `build_decisao`, inalterado, contra o SQLite original (nunca tocado pela migração).
Resultado: **SQLite produz exatamente os mesmos 128/104 e 117/98.** A migração está
correta — o dado, o schema e a query se comportam de forma idêntica nos dois bancos.

**A âncora do comando estava errada, não a migração.** O comando foi montado com os
números da Seção 7.7 da spec, sem checar que a Seção 7.8 (mesma spec, seção seguinte) já
os havia corrigido — 2015 sobe de 125→128 por uma inconsistência de identidade entre
2015/2016 e 2017-2026 na Seção 7.7, e IPCA desloca 2016 de 117→116/98→97. Corrigido
diretamente na Seção 7.7 (nota explícita marcando a tabela como superada, apontando para
a 7.8 e para este `changes/`), para que a próxima pessoa que referenciar aquela tabela
não caia na mesma armadilha.

**Divergência residual, menor, ainda aberta**: o 2016 medido aqui (117/98, idêntico em
SQLite e Postgres) não bate com o valor final da Seção 7.8 (116/97) — uma diferença de 1
em ambos os números. Não investigada nesta rodada (a prioridade era confirmar que a
migração reproduz a fonte, o que ela faz de forma byte-a-byte); hipótese de trabalho, não
confirmada: `UniversoElegivel`/`UniversoExclusao` são append-only e nunca recalculados
retroativamente, então as linhas de 2016 já materializadas podem ser de antes da correção
de IPCA/identidade da Seção 7.8, sem ligação automática que force o recálculo. Fica como
pendência registrada, não como fato estabelecido.

Suíte completa (499 testes) rodada contra Postgres: **passou sem nenhuma adaptação de
teste.**

## Achado 1 — Incidente de segurança: senha do Postgres em texto plano, rotacionada

Durante a validação da Fase 3, um `ps aux` rodado para checar se um processo remoto de
diagnóstico ainda estava ativo expôs a senha do Postgres em texto plano na saída — porque
a conexão SSH usou o padrão `env VAR=valor comando`, e `env` é um processo cujo próprio
argv contém o `VAR=valor` literal, visível para qualquer observador com acesso a `ps aux`
naquele container. **Causa raiz**: variável de ambiente passada como argumento de
processo, não como ambiente de fato. O padrão nativo do bash (`VAR=valor comando`, sem o
binário `env`) não tem esse problema — a atribuição vira `envp` do processo filho via
`execve`, nunca `argv`, e não aparece em `ps aux`. **Correção adotada daqui para frente**:
nunca passar segredo como argumento de processo — usar variável de ambiente via prefixo
nativo do shell, arquivo lido em tempo de execução, ou stdin. Nenhum `-c`/`--set` de CLI
deve conter o segredo como texto literal.

Tratado como incidente de segurança em tempo real, não como item de checklist:

1. Senha rotacionada no Postgres (`ALTER USER postgres WITH PASSWORD ...`) executado via
   `railway ssh`, com a nova senha transferida por stdin (nunca argv) e o SQL lido de
   arquivo (`-f`, nunca `-c` com o segredo embutido no comando).
2. Confirmado, contra a rede privada real (não `localhost` do próprio container — que usa
   `trust`/`peer` e teria dado falso positivo): senha nova autentica, senha antiga é
   rejeitada (`FATAL: password authentication failed`).
3. Variáveis `POSTGRES_PASSWORD`/`PGPASSWORD` do serviço Postgres atualizadas via
   `railway variable set --stdin` (nunca como argumento de linha de comando, nunca como
   parâmetro literal de chamada de ferramenta). `DATABASE_URL`/`DATABASE_PUBLIC_URL` são
   compostas por referência de template e já refletiram o valor novo automaticamente.
4. **Achado operacional durante a própria rotação**: `restart-service` reaproveita o
   mesmo deployment (sem rebuild) e portanto o `DATABASE_URL` já resolvido no momento do
   deploy original — não repega a variável nova. Os dois serviços com conexão eager no
   startup (`tradding_bot`, `learning-daily-cron`) caíram por isso logo após o restart.
   Corrigido com `redeploy` (gera deployment novo, re-resolve a referência) nos 5 serviços
   que dependem de `DATABASE_URL` do Postgres (`tradding_bot`, `learning-daily-cron`,
   `depth-capture`, `aggtrade-capture`, `measure-aggtrade-rate`) — todos online depois.
5. Arquivos temporários locais e remotos com a senha (antiga e nova) removidos ao final
   de cada etapa.

## Achado 2 — Performance: incompatibilidade de padrão de acesso, não ajuste de índice

`build_decisao` (universo + 3 fatores) leva 362-343s contra Postgres pela rede privada do
Railway, contra ~1s no SQLite local — **150-350x mais lento**. Não é índice ausente:
`EXPLAIN ANALYZE` já confirmado usando os índices corretos, execução sub-milissegundo por
consulta no servidor. É o **padrão de acesso**: uma consulta as-of por candidato (uma por
empresa, em `build_universo_elegivel` e no laço de fatores) é gratuita num banco embutido
(SQLite, sem IPC/rede) e cara em round trip de rede num banco cliente-servidor — centenas
de round trips em série somam minutos, independentemente de índice. Mesma classe de
problema já resolvida nesta frente na ingestão da COTAHIST (526s→22s, commit por linha →
lote), agora na camada de leitura, não de escrita.

**Decisão explícita do usuário**: mitigação por cache foi descartada, não considerada
insuficiente — "Mês atual" é justamente a tela cujo propósito é mostrar o que mudou hoje;
cachear trocaria lentidão por dado defasado exatamente onde a defasagem mais importa. A
correção real é reescrever o acesso a dado de `build_decisao` para lote (`IN`/join
trazendo todos os candidatos de uma vez, colapsando centenas de round trips em poucos) —
escopo de uma rodada própria, não desta.

## Fase 4 — Não executada, explicitamente pendente

Rotas de `acoes/api.py` **não foram** religadas ao Postgres; `ModuleSwitch` **continua**
desabilitando a aba Ações; hospedagem operacional **continua** sendo o SQLite local. O
achado de performance acima bloqueia a Fase 4 até a reescrita para acesso em lote —
ligar produção com o padrão atual tornaria as 5 telas do módulo impraticáveis (min. de
343s por decisão). Seção 11.12 da spec 14 atualizada para refletir exatamente esse
estado: critério de produção disparado, dados migrados e validados, corte pendente.

## Fase 5 — Registro (este arquivo)

- Seção 7.7 da spec 14: nota explícita marcando a tabela como superada pela 7.8, com a
  ligação direta ao engano real que ela já causou (âncora do comando de migração).
- Seção 11.12 da spec 14: atualizada com o estado real (critério disparado, dados
  migrados/validados, Fase 4 pendente pelo achado de performance).
- Decisão de isolamento da Fase 0.2 registrada acima.

## Pendente (para a próxima rodada, escopo próprio)

- **Reescrever o acesso a dado de `build_decisao`/`build_universo_elegivel` para lote**,
  com a mesma disciplina já usada na COTAHIST: medir onde o tempo vai antes de reescrever,
  reescrever, e travar o resultado contra os quatro números já conhecidos (2015: 128/104;
  2016: 117/98) como regressão. Só depois disso a Fase 4 pode prosseguir.
- Divergência residual do 2016 (117/98 medido vs. 116/97 da Seção 7.8) — investigar a
  hipótese de materialização append-only não recalculada retroativamente.
- Pendências já conhecidas e fora de escopo desta rodada (não tocadas): causa raiz do EPS
  implausível, caso `PDGR3`, bug de `winsorize`/`compute_demeaned_percentiles` em universo
  vazio/100% ausente, e sourcing/verificação de IBOV/IBrX-100/SMLL como price-only vs.
  total-return.

## Testes + suíte

499 testes passaram contra Postgres sem nenhuma adaptação. Nenhum teste novo — esta
rodada foi migração e validação, não mudança de comportamento.

## Decisão

- Aprovado por: Brian — autorizou a implementação completa do comando de migração
  ("Sim dê inicio à implementação", 2026-08-27) e, ao ver os dois achados não previstos
  (segurança e performance), definiu a ordem de prioridade e o escopo restante em
  seguida: rotacionar a credencial imediatamente, corrigir a Seção 7.7, fechar a Fase 5
  com a Fase 4 pendente, e tratar o acesso em lote como rodada própria, explicitamente
  sem mitigação por cache (2026-08-27).
- Justificativa: a migração de dados é um resultado verificável e correto por si só —
  encerrá-la aqui, sem forçar a Fase 4 contra um padrão de acesso que não escala para
  cliente-servidor, evita entregar um módulo em produção que seria tecnicamente "ligado"
  mas praticamente inutilizável (min. de 343s por tela). A senha exposta em texto plano
  no mesmo Postgres que o bot usa é um risco real e imediato — rotacionada antes de
  qualquer outra tarefa desta rodada, não ao final dela.
