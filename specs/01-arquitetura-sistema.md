# 01 — Arquitetura do Sistema

## Diagrama de camadas

```
┌─────────────────────────────────────────────────┐
│                   DASHBOARD (UI)                  │
│  Gráficos • Métricas • Play/Pause • Timer • Logs  │
└───────────────────┬───────────────────────────────┘
                     │ WebSocket (updates ao vivo)
┌───────────────────▼───────────────────────────────┐
│               CAMADA DE ORQUESTRAÇÃO                │
│   Engine principal • Estado (rodando/pausado)       │
│   Scheduler • Health check • Circuit breaker         │
└───┬──────────────┬──────────────┬──────────────────┘
    │              │              │
┌───▼────┐   ┌─────▼─────┐  ┌────▼─────┐
│Ingestão│   │  Modelo    │  │ Execução │
│dados WS│   │  ML/scoring│  │  ordens  │
└───┬────┘   └─────┬─────┘  └────┬─────┘
    │              │              │
┌───▼──────────────▼──────────────▼──────┐
│         PERSISTÊNCIA (banco de dados)     │
│  Trades • Métricas • Features • Logs      │
│  Snapshots de modelo • Histórico de erro  │
└───┬────────────────────────────────────────┘
    │
┌───▼─────────────────────────────────┐
│      MOTOR DE APRENDIZADO DIÁRIO       │
│  Analisa performance → gera .md de      │
│  mudanças → você revisa → aplica        │
└─────────────────────────────────────┘
```

## Contratos entre módulos

Cada módulo abaixo tem uma spec própria com o detalhe completo. Aqui documentamos
apenas a interface — o que entra, o que sai, e o que não pode ser violado.

### Ingestão de dados → Motor de features
- **Entrega:** eventos normalizados (kline, trade, orderbook delta) com timestamp
  de exchange e timestamp de recebimento local, em uma fila/stream.
- **Garantia:** ordem cronológica preservada por símbolo; nenhum evento
  duplicado (idempotência de stream); gaps de conexão são marcados explicitamente
  (não silenciosamente interpolados).
- Detalhe: [`02-ingestao-de-dados.md`](./02-ingestao-de-dados.md)

### Motor de features → Modelo
- **Entrega:** vetor de features calculado incrementalmente por símbolo/timeframe,
  com timestamp de "fechamento de conhecimento" (o modelo nunca recebe uma
  feature calculada com dado futuro ao timestamp da decisão).
- **Garantia:** cálculo determinístico — o mesmo histórico de eventos sempre
  produz o mesmo vetor de features (necessário para backtesting reproduzível).
- Detalhe: [`03-motor-de-features.md`](./03-motor-de-features.md)

### Modelo → Camada de decisão/orquestração
- **Entrega:** score/probabilidade contínuo (não decisão binária), mais metadados
  (versão do modelo, features mais influentes na inferência).
- **Garantia:** latência de inferência sob o orçamento definido em
  `04-modelo-ml-e-scoring.md`; toda inferência é logada com o snapshot de
  features que a gerou (auditoria).
- Detalhe: [`04-modelo-ml-e-scoring.md`](./04-modelo-ml-e-scoring.md)

### Orquestração → Camada de execução
- **Entrega:** ordem de intenção (símbolo, direção, tamanho sugerido, score que
  originou a decisão) — nunca um "envie ordem" sem passar pela gestão de risco.
- **Garantia:** toda intenção passa por `05-gestao-de-risco.md` antes de chegar
  em `06-camada-de-execucao.md`; a camada de execução recusa qualquer ordem que
  não venha acompanhada de stop-loss.

### Execução → Persistência
- **Entrega:** todo evento de ciclo de vida da ordem (enviada, confirmada,
  parcialmente executada, preenchida, cancelada, rejeitada) é persistido, não
  só o resultado final.
- **Garantia:** reconciliação periódica entre estado local e estado real na
  exchange (fonte de verdade é sempre a exchange).

### Persistência → Dashboard
- **Entrega:** dados via API/WebSocket para consumo do frontend — trades,
  métricas agregadas, estado do sistema, séries de score do modelo.
- **Garantia:** dashboard nunca escreve diretamente no motor de decisão; o
  Play/Pause do dashboard é um comando que passa pela orquestração, não um
  acesso direto ao banco.

### Persistência → Motor de aprendizado diário
- **Entrega:** todo o histórico necessário para análise de performance por
  horário, setup, regime de mercado.
- **Garantia:** o motor de aprendizado é somente leitura sobre o sistema de
  produção — ele nunca aplica mudanças diretamente, apenas gera artefatos em
  `changes/`. Ver [`09-aprendizado-continuo.md`](./09-aprendizado-continuo.md).

## Estados globais do sistema

O engine de orquestração mantém uma máquina de estados única, refletida no
dashboard:

| Estado | Significado |
|---|---|
| `ANALISANDO` | Recebendo dados e computando score, sem posição aberta |
| `POSICAO_ABERTA` | Ordem executada, monitorando saída/stop |
| `AGUARDANDO` | Score não atingiu threshold de entrada |
| `PAUSADO` | Execução suspensa pelo operador; análise pode continuar "a seco" |
| `PARADO_CIRCUIT_BREAKER` | Parada automática por limite de risco — requer ação humana para retomar |

Transição para `PARADO_CIRCUIT_BREAKER` nunca é automática de volta para
qualquer outro estado — sempre requer reconhecimento humano explícito.

**Nota de implementação (Fase 4):** `AGUARDANDO` não tem transição própria no
`Orchestrator` implementado — é um sub-caso de `ANALISANDO` (flat, sem sinal
qualificado) sem diferença de comportamento do sistema, só de leitura humana.
Ver detalhe em [`06-camada-de-execucao.md`](./06-camada-de-execucao.md#status-de-implementação-fase-4).
