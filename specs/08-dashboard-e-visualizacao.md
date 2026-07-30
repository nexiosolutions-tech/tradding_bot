# 08 — Dashboard e Visualização

## Objetivo

Dar visibilidade completa sobre o que o sistema está analisando, decidindo e
executando, mesmo sem o operador intervir diretamente em cada trade. O
dashboard é a interface de confiança do usuário no sistema — se algo não é
visível aqui, é como se não estivesse acontecendo.

## Views

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
