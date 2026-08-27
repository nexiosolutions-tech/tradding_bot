# 2026-08-27 — Módulo de Ações: execução local confirmada, 503 estruturado, hospedagem local registrada como decisão

## Contexto

Usuário pediu três coisas nesta rodada: rodar o módulo localmente e confirmar as 5
telas (documentando o comando de subida); fazer as rotas de Ações falharem com clareza
no Railway (503 estruturado no backend, mensagem honesta no frontend, e se possível
desabilitar a aba antes do erro); registrar a decisão de hospedagem local na spec, com
as três opções consideradas e o critério que justificaria mudar.

## 0. Correção de um erro cometido nesta própria rodada

Ao investigar por que `backend/results/acoes.db` não existia, concluí (errado) que o
banco de dados de produção tinha sido perdido num reset de ambiente entre sessões.
**Não tinha.** `acoes/persistence.py::DEFAULT_SQLITE_PATH` resolve para
`<raiz do repo>/results/acoes.db` (via `parents[4]`), não `backend/results/acoes.db` —
o mesmo padrão já documentado para o bot (`../results/tradingbot.db`, visível na linha
imediatamente acima no README, que eu não segui). O banco real de 539MB, com a série
completa 2015-2026, estava intacto o tempo todo.

O que de fato não sobrevive entre sessões é o `/tmp` do agente — scratchpad com os
downloads brutos (COTAHIST, DFP da CVM) e os scripts de orquestração ad hoc que
originalmente popularam o banco. Isso é real e seguiu registrado (Seção 11.12/README),
só a conclusão inicial ("o banco sumiu") estava errada. Corrigido antes de prosseguir,
não deixado como estava — a mesma disciplina que este projeto já cobrou de mim antes.

## 1. Execução local confirmada

Backend (`uvicorn tradingbot.api.app:app --reload`) e frontend (`npm run dev`) rodados
de verdade, apontando para o banco real (539MB, série completa). Verificado num
Chromium real (Playwright, `playwright-core` instalado como dependência transitória e
removida depois) — as 5 telas navegadas com dado de produção real, zero erros de
console. Comando de subida documentado no `backend/README.md`, nova seção "Módulo de
Ações — rodar localmente", incluindo como confirmar o caminho real do banco antes de
assumir onde ele está (a mesma checagem que teria evitado o erro da Seção 0).

## 2. 503 estruturado + frontend honesto

**Backend** (`acoes/api.py`): `_acoes_disponivel(session)` — checagem barata (uma
contagem de `CvmFiling`, cacheada em processo, nunca chama `build_decisao`) chamada no
início de toda rota que precisa de dado real. Banco vazio → `503` com mensagem clara
("módulo de Ações sem dado neste ambiente..."), nunca mais um 500 mudo. Nova rota
`GET /api/acoes/disponivel`, nunca gateada por ela mesma, para o frontend checar antes
de qualquer erro acontecer. `warm_up_cache_em_background` também checa disponibilidade
antes de gastar tempo aquecendo um banco vazio.

**Frontend**: `AcoesIndisponivelError` (novo, `acoes/api/client.ts`) — `getJSON`
distingue `503` de qualquer outro erro. Componente `IndisponivelLocal` (novo, mesma
disciplina de estado vazio honesto da Seção 11.3, agora para o módulo inteiro) usado
nas 5 telas em vez da mensagem genérica "não foi possível carregar".

**Bônus pedido pelo usuário, implementado**: `App.tsx` checa `/api/acoes/disponivel`
uma vez no carregamento (otimista — começa disponível, só desabilita depois de
confirmar banco vazio ou backend fora do ar); `ModuleSwitch` desabilita o botão "Ações"
com título explicando o motivo, sem escondê-lo. Verificado com o backend
deliberadamente parado — o clique fica literalmente bloqueado (Playwright confirmou
via timeout esperado, `element is not enabled`).

## 3. Hospedagem registrada como decisão (spec 14, Seção 11.12, nova)

Três opções documentadas — local (escolhida, sem custo de infra para um uso mensal de
um usuário só), volume persistente no Railway (resolveria o deploy vazio, mas amarra o
módulo à infra do bot sem benefício de uso real), Postgres (a opção certa se o
critério abaixo disparar, mas overkill hoje). **Critério explícito para reconsiderar**:
querer acessar de outro dispositivo — hoje o acesso é sempre pela máquina com
`results/acoes.db`. Migração para Postgres, se/quando o critério disparar, é mecânica
(`persistence.py` já segue o mesmo padrão `DATABASE_URL`/SQLite do bot).

**Achado colateral conectado a um achado anterior**: o "achado colateral" da Seção 13
(EPS implausível, `compute_demeaned_percentiles` quebra com universo 100% ausente,
`TypeError`) tem uma segunda manifestação real — universo genuinamente **vazio**
dispara `ZeroDivisionError` no mesmo trecho, por um caminho ligeiramente diferente
(divisão por `len()` zero em vez de comparação de `None`). Mesma classe de bug, dois
gatilhos, nenhum corrigido na função em si — mitigado evitando o caminho (checagem de
disponibilidade antes de chamar `build_decisao`), não consertando a função.

## Testes + suíte

8 testes novos (`test_acoes_api.py`): disponibilidade true/false, 503 estruturado em
todas as rotas que precisam de dado (parametrizado), `/historico` (lista) não gateada
por não tocar o banco. Fixture `client_sem_dado` nova, ambiente idêntico ao `client`
mas nunca popula o banco — reproduz produção sem volume/Postgres de verdade, não uma
aproximação. Suíte completa (`--ignore=tests/test_binance_ws_live.py`): 499 passed.
Frontend: `tsc -b` limpo, `vite build` sem erro, `oxlint` limpo.

## Pendente

- Escrever como script commitado (não ad hoc) a orquestração que popula
  `results/acoes.db` do zero — hoje só existiria de novo reescrevendo a lógica descrita
  na Seção 7.7, nunca promovida a `scripts/`.
- Corrigir `compute_demeaned_percentiles`/`winsorize` na origem (nunca dividir por
  zero nem ordenar `None`) em vez de só evitar o caminho — mesma pendência da Seção 13,
  agora com dois gatilhos confirmados em vez de um.

## Decisão

- Aprovado por: Brian — pediu as três tarefas desta rodada, com o "melhor ainda" da
  aba desabilitada como sugestão explícita, não obrigatória (2026-08-27).
- Justificativa: um 500 mudo em produção custaria uma tarde de investigação a alguém
  tratando ambiente como bug de dado — a mesma economia de tempo que já motivou outros
  estados vazios honestos nesta spec (Seção 11.3), agora aplicada ao módulo inteiro.
  Documentar a decisão de hospedagem evita a mesma investigação se repetir daqui a dois
  meses.
