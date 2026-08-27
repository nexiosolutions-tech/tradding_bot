# 08 — Dashboard e Visualização

## Objetivo

Dar visibilidade completa sobre o que o sistema está analisando, decidindo e
executando, mesmo sem o operador intervir diretamente em cada trade. O
dashboard é a interface de confiança do usuário no sistema — se algo não é
visível aqui, é como se não estivesse acontecendo.

## Seletor de módulo (Cripto / Ações)

O `CoinSelector` existente (ver "Redesign para tema de exchange cripto" abaixo) escolhe
um **par dentro do módulo cripto** — não serve para o módulo de Ações
(`14-modulo-acoes-b3.md`), que é um módulo inteiro diferente, com seu próprio conjunto de
telas e seu próprio dado (`specs/00`, disclaimer de independência: os dois módulos
compartilham fundação de engenharia — este mesmo shell de dashboard — mas nunca estado,
dado, modelo ou runtime). Seletor de nível acima do `CoinSelector` (`ModuleSwitch`),
que troca o conteúdo inteiro da sidebar: as 4 views abaixo quando em modo Cripto, as 5
telas de `14-modulo-acoes-b3.md` (Seção 11) quando em modo Ações.

**Implementado com troca real (2026-08-27)** — não é mais o placeholder estrutural
inerte descrito na versão anterior desta seção. A condição que adiava a lógica de
troca (Fase 1-3 de `14-modulo-acoes-b3.md` com dado funcional) já estava satisfeita;
`ModuleSwitch` (componente compartilhado, `src/components/ModuleSwitch.tsx`) renderiza
com uma variante de tema por módulo (`dark` para o `Sidebar` cripto existente, `light`
para o novo `AcoesSidebar`), e `App.tsx` desmonta um shell inteiro e monta o outro —
nunca os dois convivem na mesma árvore React, mesma disciplina de isolamento do
`CLAUDE.md` aplicada também no frontend. O engine WebSocket do módulo cripto
(`useEngineState`) permanece vivo em `App.tsx` mesmo com o módulo Ações ativo, para não
perder a conexão a cada troca — só a UI é trocada, não o estado de conexão.

## Views (módulo Cripto)

### 1. Live (operação em tempo real)

- Gráfico de candlestick com as linhas de tendência que o modelo está seguindo,
  sobrepostas com marcadores de entrada/saída.
- **Timer intuitivo:** tempo desde que o sistema foi ligado, e tempo da operação
  atual em aberto (quando houver posição aberta).
- **Play/Pause:** controla a camada de execução (`06-camada-de-execucao.md`).
  Pausar não necessariamente para a análise — o sistema pode continuar
  analisando "a seco" (sem executar) para permitir comparação posterior entre
  o que teria sido feito e o que foi de fato feito.
- Indicador de estado atual do sistema, refletindo a máquina de estados de
  [`01-arquitetura-sistema.md`](./01-arquitetura-sistema.md): `ANALISANDO`,
  `POSICAO_ABERTA`, `AGUARDANDO`, `PAUSADO`, `PARADO_CIRCUIT_BREAKER`.

### 2. Performance

- Curva de equity (capital ao longo do tempo).
- Win rate, profit factor, drawdown máximo.
- Distribuição de resultados por horário do dia / dia da semana (padrões de
  volatilidade por sessão são relevantes em cripto).
- Tabela de trades: entrada, saída, motivo do sinal, resultado, taxas pagas.

### 3. Modelo

- Score/confiança do modelo ao longo do tempo vs. o que de fato ocorreu
  (gráfico de calibração).
- Importância de features nas decisões recentes (ex.: SHAP).
- Histórico de versões de modelo e como a performance mudou a cada retreino
  (ligado a `04-modelo-ml-e-scoring.md` e `07-backtesting-e-validacao.md`).

### 4. Aprendizado (ligado ao ciclo diário)

- Lista de relatórios em `learnings/`, navegável por data.
- Lista de mudanças propostas em `changes/`, com status (pendente / aprovada /
  rejeitada / aplicada).

## Requisitos técnicos

- **Frontend:** React + TradingView Lightweight Charts (biblioteca oficial da
  TradingView, leve, feita para candlestick + overlays) para os gráficos de
  mercado; Recharts (ou equivalente) para gráficos de métricas agregadas
  (equity curve, distribuições).
- **Comunicação com o backend:** WebSocket para updates ao vivo (estado,
  score, trades); REST para consultas históricas paginadas.
- **Play/Pause** é um comando que passa pela camada de orquestração — o
  dashboard nunca escreve diretamente no banco ou aciona a exchange
  diretamente.

## Padrão de qualidade de UI

O dashboard precisa transmitir "vivo" e responsivo sem ser ruidoso. Usar as
skills de UI definidas em [`CLAUDE.md`](../CLAUDE.md#skills-de-ui-a-utilizar-no-dashboard):

- Elementos vistos com muita frequência (ex.: o timer, o preço atual) não
  devem ter animação chamativa — animação se reserva a eventos que de fato
  importam (entrada/saída de trade, mudança de estado, alerta).
- Transições sob 300ms, sem easing artificial.
- Consistência visual e "bom gosto" seguindo as heurísticas da skill
  `taste-skill`.

## Fora de escopo no MVP

- Edição de parâmetros de risco/modelo diretamente pelo dashboard (mudanças de
  risco seguem o fluxo `changes/` com revisão humana fora da UI de operação,
  ver `09-aprendizado-continuo.md`) — o dashboard no MVP é observação + controle
  operacional (play/pause/kill switch), não um editor de configuração de risco.
- Múltiplos usuários/autenticação multi-perfil.

## Status de implementação (Fase 3)

- **Backend:** `backend/src/tradingbot/api/app.py` (FastAPI) — REST para
  backtests/modelos/trades/learnings/changes, WebSocket `/ws/engine` para
  estado ao vivo, comandos play/pause/reconhecer circuit breaker roteados
  sempre pelos métodos do `Orchestrator` (nunca acesso direto a banco/exchange
  a partir da API). Roda o `Orchestrator` + stream de ingestão como task de
  background no mesmo processo — decisão registrada em
  [`10-stack-tecnica-e-dependencias.md`](./10-stack-tecnica-e-dependencias.md#hospedagem)
  para simplificar o deploy inicial no Railway (um único serviço).
- **Frontend:** `frontend/dashboard/` (React + Vite + TypeScript), 4 views
  como especificado, TradingView Lightweight Charts para a curva de capital e
  Recharts para os gráficos de barra. Validado visualmente contra a API real
  (screenshot das 4 views com dados reais da Fase 1 carregando corretamente).
- View "Live" mostra "engine não configurado" enquanto
  `BINANCE_API_KEY`/`BINANCE_API_SECRET` não existirem no backend — as demais
  views não dependem disso.
- **Autenticação dos comandos de controle (2026-07-30):** os endpoints
  `pause`/`resume`/`acknowledge_circuit_breaker` e o WebSocket `/ws/engine`
  aceitam uma `DASHBOARD_API_KEY` opcional — via header `X-API-Key` nos
  endpoints REST, via query param `?key=` no WebSocket (navegadores não
  conseguem setar headers customizados num WebSocket nativo). Sem a variável
  configurada, o comportamento é o mesmo de antes (aberto) — ver
  [`changes/2026-07-30-autenticacao-endpoints-controle.md`](../changes/2026-07-30-autenticacao-endpoints-controle.md).
  Isso não é o "múltiplos usuários/autenticação multi-perfil" citado como fora
  de escopo acima — é uma chave única compartilhada.
- **Gráfico de preço com indicadores na view Live (2026-07-31):** `Orchestrator`
  mantém um buffer em memória (`candle_history`, últimos 500 candles) com OHLC
  e indicadores em escala de preço absoluto (EMA rápida/lenta, Bollinger,
  RSI) — deliberadamente **separado** do vetor de features normalizado que
  alimenta o modelo (`03-motor-de-features.md`): um humano olhando um gráfico
  de candles espera a EMA na mesma escala de preço, não em percentual.
  Exposto via `GET /api/engine/candles`. O buffer é populado a cada candle
  fechado, independente do estado de pausa do engine — o gráfico deve
  refletir o mercado real continuamente. Frontend renderiza via
  `lightweight-charts` (candlestick + overlays de EMA/Bollinger + painel
  secundário de RSI + marcadores de entrada/saída dos trades reais).
  de escopo acima — é uma chave única compartilhada, só para não deixar
  comandos que afetam execução real completamente abertos numa URL pública.
- **Gerar backtest a partir do dashboard (2026-08-18):** `POST
  /api/backtests/run` (protegido pela mesma `DASHBOARD_API_KEY` dos comandos
  de controle) busca klines reais da Binance e roda um backtest síncrono,
  escrevendo o relatório em `results/` do próprio processo em execução — a
  mesma pasta que `GET /api/backtests` já lê. Existia antes um script CLI
  (`scripts/run_backtest.py`) para isso, mas `results/` é local ao processo
  (`.gitignore`, sem volume persistente no Railway), então rodar o script na
  máquina do operador nunca alimentava a view Performance em produção —
  alguém precisava gerar o relatório *dentro* do container do serviço. A
  lógica de busca+execução+persistência foi extraída para
  `backtesting/runner.py::run_and_save_backtest`, reusada pelo script e pelo
  endpoint, para os dois caminhos não divergirem. View Performance ganhou um
  botão "Rodar backtest" (estado vazio e toolbar da lista) que chama esse
  endpoint e seleciona o run recém-criado. Ver
  [`changes/2026-08-18-endpoint-rodar-backtest.md`](../changes/2026-08-18-endpoint-rodar-backtest.md).

### Redesign para tema de exchange cripto (2026-08-18)

Pedido explícito do usuário: a interface não tinha "a cara do negócio" — o tema anterior
(claro, tons quentes) não puxava o vocabulário visual que o usuário já conhece de
exchanges como Binance/Bybit/OKX (tema escuro, verde/vermelho de mercado). Redesign
estritamente visual — nenhum endpoint, dado ou regra de negócio mudou. Decisões
completas de paleta/tipografia/componentes em
[`frontend/dashboard/DESIGN.md`](../frontend/dashboard/DESIGN.md); resumo:

- Tema escuro único (`#0b0e11`/`#181b20`), verde/vermelho (`#0ecb81`/`#f6465d`) como
  vocabulário semântico consistente (preço, P&L, stop-loss, badges), accent âmbar
  evoluído do já existente (não trocado por um genérico). Space Grotesk + JetBrains Mono
  mantidos (já eram a escolha certa pro gênero).
- **`CoinSelector`** (novo componente) — placeholder estrutural pra expansão
  multi-moeda: mostra o par ativo (`state.symbol`) com preço/variação reais, e uma lista
  de pares "em breve" sem lógica de troca real (nenhum `onClick`, nenhum estado) — trocar
  de ativo no futuro é mudança de dado, não de design.
- View Live reorganizada num grid de 3 colunas (seletor de par | gráfico dominante |
  posição + controles do engine) inspirado na hierarquia de um terminal de trading — os
  controles são os que já existiam (play/pause/reconhecer circuit breaker), não um
  formulário de compra/venda fabricado (segue "fora de escopo" abaixo).
- Ver `changes/2026-08-18-redesign-exchange-dark-theme.md`.

### Feed de atividade em tempo real (adicionado após feedback de uso)

O usuário reportou que a Fase 3 original não "parecia viva" — sem um jeito de
ver o engine avaliando candles entre um trade e outro, e a UI não seguia de
fato as skills de design listadas em `CLAUDE.md`. Duas mudanças:

1. **Redesign visual** aplicando a skill `redesign-existing-projects`
   (instalada conforme `CLAUDE.md`): sidebar com ícones próprios (não
   biblioteca genérica), tipografia com caráter (Space Grotesk + JetBrains
   Mono para números), paleta com um único accent considerado (âmbar
   dessaturado) em vez de azul/roxo genérico de IA, hero card com sparkline
   de capital da sessão, estados vazios compostos em vez de texto solto.
2. **`Orchestrator.activity_log`** (`backend/src/tradingbot/execution/orchestrator.py`)
   — um buffer em memória (não persistido, não é o audit trail de
   `EngineEvent`) que registra toda avaliação de candle, sinal, ordem e
   circuit breaker, exposto via `/api/engine/activity` e embutido no payload
   de `/api/engine/state` (REST e WS). A view Live renderiza isso num console
   com auto-scroll — é a resposta direta a "quero saber que o algoritmo está
   trabalhando".
