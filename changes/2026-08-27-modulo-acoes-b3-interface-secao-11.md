# 2026-08-27 — Módulo de Ações: interface (Seção 11) implementada, achado real de EPS implausível

## Contexto

Usuário pediu implementação da interface conforme
`14-modulo-acoes-b3-secao-11-interface.md` — a proposta de design escrita depois do
resultado nulo do backtest (Seção 9.6), reformulando o módulo como "painel de
evidência", não de recomendação. Arquivo fundido na Seção 11 de
`specs/14-modulo-acoes-b3.md` (versão canônica agora), o arquivo separado virou
ponteiro histórico.

## 1. Backend: `acoes/api.py`, `APIRouter` próprio

Montado em `tradingbot.api.app` via `include_router`, sessão de banco própria
(`acoes.persistence.get_session`) — nunca reusa `session_factory`/`orchestrator` do
bot (`CLAUDE.md`: nunca estado/dado/modelo/runtime compartilhado). Seis rotas:
`/mes-atual`, `/empresas/{ticker}`, `/saude-do-dado`, `/historico`,
`/historico/{data}`, `/precos`.

**Carimbo de proveniência e célula vazia honesta (Seção 11.3) não existiam em nenhuma
função anterior** — `build_decisao`/`DecisaoEmpresa` só carregavam percentil, nunca o
valor bruto nem o motivo de ausência. Resolvido reusando só funções já públicas de
`fatores.py`/`pointintime.py` (nunca reimplementadas): `_detalhe_earnings_yield`/
`_detalhe_divida_liquida_ebitda`/`_detalhe_roe` recomputam o valor bruto + decidem o
motivo entre os 4 estados (`inaplicavel`/`indefinido`/`sem_dado`/`versao_indisponivel`)
— o último distinguido checando se a versão do filing tem **algum** item financeiro
ingerido (`versao_indisponivel`) vs. tem itens mas não o específico buscado
(`sem_dado`), nunca adivinhado.

**Cache em processo (`_cache_decisao`) + trava (`threading.Lock`) + aquecimento em
background no `lifespan`** — `build_decisao` custa 15-30s por data (materializa
universo + computa 3 fatores para ~150-250 empresas). Sem cache, Empresa/Histórico/
Saúde do Dado (que consultam várias das 12 datas da série) recalculariam tudo a cada
requisição. Dois problemas reais medidos e corrigidos nesta rodada, não hipotéticos:

- **Duas requisições lentas em paralelo corrompiam a experiência** (medido: erro de
  CORS no navegador ao navegar rápido entre Empresa e Saúde do Dado) — causa real era
  contenção de threads/SQLite, não CORS; corrigida serializando o cálculo com uma
  trava global (API de um usuário só, "ferramenta de trabalho", nunca alta
  concorrência).
- **Cache nunca guarda "hoje"** (única data cujo resultado pode mudar dentro do
  próprio dia) — mas isso deixava toda navegação para uma tela nova pagar o cálculo
  do zero. Resolvido com aquecimento em thread separada no startup do servidor
  (`warm_up_cache_em_background`, desligável em teste via `WARMUP_HABILITADO` — sem
  isso, corria contra as próprias asserções de teste sobre o estado do cache, uma
  fonte de flakiness por timing).

13 testes novos (`test_acoes_api.py`), reusando a fixture real já existente de
`test_acoes_decisao.py` (ITUB4/BBAS3/PETR4, 2016-07-15).

## 2. Dado de produção promovido

`results/acoes.db` (gitignored) recebeu uma cópia do banco da série completa já
verificada nesta sessão (2015-2026, dado real CVM/COTAHIST/BCB) — sem isso a interface
mostraria um banco vazio. `results/acoes_backtest.json` recebeu o resultado do
backtest (Seção 9.6) já computado, servido estático pela API (mesma convenção do
`/api/backtests` do bot, que lê de `results/*/report.json`) — recomputar o backtest
completo a cada request seria caro demais.

## 3. Frontend: módulo Ações completo

- **`ModuleSwitch`** (`src/components/ModuleSwitch.tsx`, compartilhado) — troca a
  sidebar inteira entre Cripto e Ações (spec 08, já desenhado; implementado com troca
  real agora que o módulo de Ações tem dado funcional).
- **Tema claro escopado** (`src/acoes/acoes.css`, namespace `.acoes-*` próprio — nunca
  reaproveita `.sidebar`/`.panel`/`.topbar` do cripto, que carregam tema escuro
  hardcoded em vários lugares, não só via CSS var). IBM Plex Serif/Sans/Mono
  carregadas via Google Fonts em `index.html`, ao lado das fontes do cripto.
  Responsivo até 380px, foco de teclado visível, `prefers-reduced-motion` respeitado.
- **4 componentes transversais** (Seção 11.3): `ProvenanceChip`, `IdentityBadge`,
  `EmptyCell`, `MethodBanner` — usados em todas as telas via `FatorCell` (célula de
  fator reusada, nunca duplicada).
- **5 telas**: Mês atual (com navegação mês a mês, faixa de contexto do método,
  ranking com fatores+percentil+carimbo, distribuição setorial, mudanças do mês),
  Empresas (lista + ficha com linha do tempo de conhecimento e histórico de entregas
  à CVM), Minha carteira (composição manual via `localStorage`, exposição setorial vs.
  universo — nunca vs. Ibovespa, concentração, simulação de aporte antes/depois sem
  sugerir alocação), Saúde do dado (fontes, cobertura por era, exclusões do mês,
  resultado do backtest publicado sem eufemismo), Histórico (reconstrução ponto-a-
  ponto de cada data de decisão real + retorno subsequente 1/3/6/12m do topo vs. base
  do ranking).

Verificado num navegador real (Playwright/`chromium-cli` não disponível no ambiente,
`playwright-core` instalado como dependência transitória e removida depois) — as 5
telas + troca de módulo navegadas com dado real de produção, zero erros de console,
fluxo de adicionar posição em Minha carteira testado ponta a ponta.

## 4. Achado real: EPS implausível em 28 ocorrências, não isolado (registrado na Seção 13, não corrigido)

A própria tela de Empresa (linha do tempo de conhecimento, que mostra o valor **bruto**
de cada fator) expôs um earnings yield de 25.067% para `EVEN3` em 2023-02-28 — óbvio.
Escaneada a série completa: **28 valores implausíveis (|razão| > 300%) em earnings
yield/ROE, ao longo das 12 datas**. A maioria é distress real (`RSID3`/`PDGR3`,
prejuízo grande contra preço já deprimido), mas pelo menos 4 são artefato de escala,
incluindo **`ITUB4`** (2020-02-28, ≈87x) — um banco grande e líquido, descartando
"empresa pequena com dado ruim" como explicação completa. Investigado um caso
(`EVEN3`): duas contas de EPS no mesmo filing com valores 1000x diferentes
(`3.99.01.01`=1123,0 vs. `3.99.02.01`=1,123) — sugere problema de escala/unidade em
pelo menos uma conta da CVM, causa raiz ainda não confirmada para os outros 27 casos.

**Não corrigido nesta rodada** — é mudança de lógica de fator (`fatores.py`), não de
interface, e precisa de investigação própria (a mesma disciplina já registrada em
`feedback_measure_before_accepting_extreme_results`: medir antes de aceitar, e aqui
antes de corrigir também — não dá para saber se a correção certa é filtrar, escolher a
outra conta, ou algo mais específico sem olhar mais casos). Registrado na Seção 13
como risco conhecido aberto.

## Testes + suíte

13 testes novos (`test_acoes_api.py`). Suíte completa
(`--ignore=tests/test_binance_ws_live.py`): 488 passed. Frontend: `tsc -b` limpo,
`vite build` sem erro, `oxlint` limpo.

## Pendente

- Investigar a causa raiz do achado de EPS implausível (Seção 13) — se é sempre a
  mesma conta CVM, se afeta `score_composto` o bastante para mudar alguma leitura do
  backtest (improvável dado o resultado já ser nulo, mas não verificado), se o mesmo
  padrão existe em ROE por causa distinta.
- Fonte real de IBOV/IBrX-100/SMLL (Seção 9.4) — segue pendente, não é bloqueio desta
  interface (Seção 11.9 já proíbe comparação com índice sem fonte verificada).
- Motor de carteira completo (Seção 8) e Painel do aporte (versão antiga da Seção 11)
  seguem fora de escopo — a interface atual é deliberadamente "painel de evidência",
  não de sugestão de alocação, dado o resultado nulo do backtest.

## Decisão

- Aprovado por: Brian — pediu implementação da interface conforme o arquivo de
  especificação já escrito (2026-08-27).
- Justificativa: a spec de interface já estava aprovada e detalhada num arquivo
  próprio; a tarefa era execução fiel, não decisão de design nova. O achado de EPS
  implausível é reportado, não decidido — mudança de lógica de fator precisa de
  aprovação própria antes de qualquer correção.
