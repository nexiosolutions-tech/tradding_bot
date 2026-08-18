# Change Proposal — 2026-08-18 — Redesign visual para tema de exchange cripto

**Status:** aplicada

## Evidência (origem)
- Pedido explícito e detalhado do usuário: a interface funcional não transmitia "a cara
  do negócio" — o tema anterior (claro, tons quentes, `#faf8f4`/`#b45309`) não tinha
  sinergia visual com o mercado em que o sistema opera. Pedido de aproximação ao padrão
  visual consolidado de exchanges (Binance/Bybit/OKX): tema escuro, verde/vermelho de
  sinalização de mercado, tipografia sans + monoespaçada pra números, hierarquia de
  terminal de trading, seletor de moedas preparado pra expansão futura.

## Proposta
- Paleta convertida pra tema escuro único (`#0b0e11`/`#181b20`/`#12151a`), verde
  (`#0ecb81`) e vermelho (`#f6465d`) como vocabulário semântico de mercado aplicado
  consistentemente (preço, P&L, stop-loss, badges de estado, botões primário/perigo) —
  accent âmbar evoluído do já existente (`#b45309` → `#f0b90b`), não trocado por um
  genérico. Space Grotesk + JetBrains Mono mantidos sem alteração (já eram a escolha
  certa pro gênero — números tabulares em mono, texto geral em sans). Tokens em
  `index.css` + espelhados em `theme.ts` (canvas dos gráficos `lightweight-charts` não lê
  CSS custom properties).
- `CoinSelector` (componente novo) — placeholder estrutural pra expansão multi-moeda
  (bot só opera BTCUSDT hoje, fase de validação). Mostra o par ativo com preço/variação
  reais (calculados da janela de candles já carregada — não é ticker 24h, o backend não
  expõe um ainda) e uma lista de pares "em breve" (`ETH`, `BNB`, `SOL`, `XRP`) — sem
  `onClick`, sem estado, sem lógica de troca real, conforme pedido explícito de não
  implementar troca de ativo de verdade.
- View Live reorganizada num grid de 3 colunas (`terminal-grid`): seletor de par |
  gráfico de candles dominante | posição + controles do engine — inspirado na hierarquia
  de um terminal de trading real. Colapsa pra 1 coluna abaixo de 1100px. Os controles do
  lado direito são os que já existiam (play/pause/reconhecer circuit breaker via
  `EngineControls`, dados de posição aberta) — **não** um formulário de compra/venda
  fabricado, já que este bot não expõe entrada manual de ordens (fora de escopo do MVP,
  spec 08).
- `frontend/dashboard/DESIGN.md` (novo) documenta a paleta, tipografia e componentes pra
  manter consistência em telas futuras.
- **O que não muda:** nenhum endpoint, dado, regra de negócio, fluxo de decisão do bot
  ou funcionalidade de view — reorganização e reestilização da mesma informação já
  exposta pela API.

## Classificação de risco da mudança
- [ ] Não é mudança de parâmetro de risco/execução — estritamente camada visual do
  dashboard (CSS + componentes React), não toca `execution/orchestrator.py`, API do
  backend, nem lógica de negócio.

## Validação
- `tsc -b && vite build` sem erros.
- Contraste de todos os pares texto/fundo do tema checado contra WCAG AA (≥4.5:1
  corpo) — `--text-muted` ajustado de `#76808f` (4.32:1 no pior caso) pra `#848e9c`
  (4.64:1 no pior caso, `--surface-hover`).
- Verificado visualmente com `google-chrome --headless --screenshot` contra o dev
  server: Live (com dado mockado localmente pra simular `state.configured=true`, já que
  não há credenciais Binance neste ambiente), Performance e Aprendizado (ambos com dado
  real do backend local — 3 backtests reais, 34 changes reais, 1 learning real).
- Regra do CLAUDE.md seguida: skills de UI de terceiros do projeto usadas
  (`redesign-existing-projects`, `emil-design-eng`, `impeccable`,
  `design-taste-frontend` — esta última se autodeclarou fora de escopo pra dashboards
  densos, usada só como referência de princípios gerais de dark mode/contraste).

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-18
- Justificativa: pedido explícito e detalhado de redesign, com referência visual
  (screenshot de exchange) e restrições claras de escopo (sem mudança de lógica/dados).
