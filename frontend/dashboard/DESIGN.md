# Design — Trading Bot Dashboard

Decisões de design do redesign de 2026-08-18 (tema de exchange cripto). Para o histórico
completo de decisões de UI anteriores, ver `specs/08-dashboard-e-visualizacao.md`.

## Por que este redesign

O produto exibe dado de mercado, P&L e sinais de compra/venda — o mesmo tipo de
informação que o usuário já lê todo dia em exchanges como Binance/Bybit/OKX. Um tema
claro e quente (a versão anterior) obriga o usuário a "traduzir" cada elemento pra esse
vocabulário visual que ele já conhece de cor. Herdar o vocabulário reduz esse atrito —
ver `specs/08` para o objetivo geral do dashboard ("a interface de confiança do
usuário").

## Paleta

Tema escuro por padrão (`color-scheme: dark`), único tema — não há alternância
claro/escuro. Tokens em `src/index.css` (`:root`), espelhados em `src/theme.ts` pros
gráficos em canvas (`lightweight-charts`/Recharts não leem CSS custom properties).

| Token | Valor | Uso |
|---|---|---|
| `--bg` | `#0b0e11` | Fundo da página |
| `--bg-elevated` | `#12151a` | Sidebar |
| `--surface` | `#181b20` | Cards/painéis |
| `--surface-hover` | `#21252b` | Hover de linhas/itens |
| `--border` / `--border-strong` | `#262a31` / `#363b44` | Divisores |
| `--text` / `--text-secondary` / `--text-muted` | `#eaecef` / `#b7bdc6` / `#848e9c` | Hierarquia de texto |
| `--accent` / `--accent-strong` | `#f0b90b` / `#f8d33a` | Marca — navegação ativa, foco, curva de capital. Evoluído do amber já usado na versão anterior (`#b45309`), não trocado por um genérico |
| `--positive` / `--positive-strong` | `#0ecb81` / `#3ddb99` | Alta, P&L positivo, "resumir"/ações de ir |
| `--negative` / `--negative-strong` | `#f6465d` / `#f97a8c` | Baixa, P&L negativo, stop-loss, ações destrutivas |

Verde/vermelho é vocabulário semântico, não decoração — aplicado de forma consistente em
preço, delta de P&L, badges de estado e botões (ver `impeccable`'s craft-floor: "Accent
color used for primary actions, current selection, and state indicators only"). Todos os
pares texto/fundo do tema foram checados contra WCAG AA (≥4.5:1 pra texto de corpo;
`--text-muted` foi ajustado especificamente pra passar nesse teste até no fundo mais
claro do sistema, `--surface-hover`).

## Tipografia

Mantida sem alteração — já era a escolha certa pro gênero antes deste redesign:
- **Space Grotesk** (`--font-ui`) — texto geral, labels, headings.
- **JetBrains Mono** (`--font-mono`) — todo número (preço, P&L, timers, tabelas) via
  `.num { font-variant-numeric: tabular-nums }`, garantindo alinhamento de dígitos em
  colunas numéricas.

## Componentes novos

- **`CoinSelector`** (`src/components/CoinSelector.tsx`) — placeholder estrutural pra
  expansão multi-moeda (spec 08). Mostra o par ativo (`state.symbol`, hoje sempre
  BTCUSDT) com preço/variação reais, e uma lista de pares "em breve" — sem `onClick`,
  sem estado, sem lógica de troca real. Trocar de ativo no futuro é mudança de dado
  (adicionar ao array `COMING_SOON` e ligar no backend), não mudança de design.
- **`.terminal-grid`** (LiveView) — layout de 3 colunas (seletor de par | gráfico
  dominante | controles/posição), inspirado na hierarquia típica de terminal de trading.
  Colapsa pra 1 coluna abaixo de 1100px. Os controles do lado direito são os que já
  existiam (play/pause/reconhecer circuit breaker, dados de posição) — não é um
  formulário de compra/venda fabricado; este bot não expõe entrada manual de ordens
  (fora de escopo do MVP, ver `specs/08`).

## O que não mudou

Nenhum endpoint, dado, regra de negócio ou fluxo de decisão do bot. Nenhuma view perdeu
ou ganhou funcionalidade — só reorganização visual e de hierarquia da mesma informação
já exposta pela API.
