# 10 — Stack Técnica e Estrutura de Pastas

## Stack

### Backend / dados / ML
- **Python** (versão a fixar no ambiente de desenvolvimento) para ingestão,
  features, modelo e execução.
- **`python-binance`** e/ou **`ccxt`** para integração com a Binance (REST +
  WebSocket). `ccxt` mantém a porta aberta para múltiplas exchanges no futuro
  sem custo de reescrita.
- **`asyncio` + `websockets`** para o caminho crítico de ingestão em tempo
  real (evitar wrappers pesados nesse caminho).
- **`collections.deque`** / estruturas rolling em memória para o motor de
  features no MVP.
- **`ta-lib`** (ou implementação incremental própria) para indicadores
  técnicos.
- **LightGBM / XGBoost** como modelo baseline.
- **`pandas`/`numpy`** para prototipagem e backtesting offline.

### Persistência
- Banco relacional **PostgreSQL**, provisionado como addon do Railway (mesma
  plataforma de hospedagem — ver "Hospedagem" abaixo), para trades, métricas,
  logs de decisão e metadados de modelo — schema exato a definir na fase de
  implementação.
- Armazenamento de artefatos de modelo (arquivos serializados) versionado por
  timestamp/hash.
- **Fase 1 (atual) não depende de Postgres.** O motor de backtesting grava
  relatórios como arquivos (`results/<run>/report.json` + `report.md`) — é
  suficiente para o critério de saída da Fase 1 e evita provisionar
  infraestrutura de banco antes de existir dado de produção real para
  persistir. A integração com Postgres entra junto da camada de execução
  (Fase 4) ou do motor de aprendizado contínuo (Fase 5), o que vier primeiro.

### Hospedagem
- **Railway** é a plataforma de deploy alvo para o sistema rodando
  continuamente (ingestão + execução + motor de aprendizado). PostgreSQL via
  addon do Railway, sem infraestrutura de banco separada a gerenciar.
- Implicações a resolver quando a Fase 4/5 chegar (registrar como `changes/`
  quando decidido, não são requisito da Fase 1):
  - Variáveis de ambiente (credenciais testnet/mainnet, connection string do
    Postgres) via painel de env vars do Railway — nunca commitadas, ver
    "Gestão de segredos" abaixo.
  - Processo de longa duração (ingestão via WebSocket) precisa de um serviço
    Railway do tipo worker/always-on, não uma função serverless/cron.
  - Dashboard (spec 08) e backend podem ser dois serviços Railway separados no
    mesmo projeto, ou um único serviço servindo API + estáticos — decisão a
    tomar na Fase 3.

### Frontend / Dashboard
- **React** + **TradingView Lightweight Charts** (gráficos de mercado) +
  **Recharts** (métricas agregadas).
- **WebSocket** para updates ao vivo; REST para consultas históricas.
- Skills de UI de terceiros conforme [`CLAUDE.md`](../CLAUDE.md).

### Ambientes de execução
- **Testnet Binance** (`testnet.binance.vision`) — obrigatório antes de
  qualquer mudança em produção (`06-camada-de-execucao.md`).
- Ambiente local de desenvolvimento com variáveis de ambiente separadas por
  ambiente (testnet/mainnet) — nunca a mesma credencial/config usada nos dois.
  Em produção (Railway), essa separação é feita por environment do próprio
  Railway (ex.: `staging`/`production`), cada um com seu próprio conjunto de
  variáveis.

## Estrutura de pastas (proposta inicial, sujeita a `changes/`)

```
/
├── CLAUDE.md
├── README.md
├── specs/              # especificações (este diretório)
├── learnings/           # relatórios diários do motor de aprendizado
├── changes/             # backlog de mudanças propostas, pendentes de revisão
├── backend/
│   ├── ingestion/       # spec 02
│   ├── features/        # spec 03
│   ├── model/            # spec 04
│   ├── risk/             # spec 05
│   ├── execution/        # spec 06
│   ├── backtesting/      # spec 07
│   └── learning_engine/  # spec 09 — job diário
├── frontend/
│   └── dashboard/        # spec 08
└── infra/                 # scripts de deploy, configuração de ambiente
```

## Gestão de segredos

- Credenciais de API (testnet e mainnet) nunca commitadas — via variáveis de
  ambiente/arquivo de secrets ignorado pelo controle de versão.
- Credenciais de mainnet só configuradas no ambiente que efetivamente vai
  operar com capital real, após todos os gates de `06-camada-de-execucao.md`.

## Nota sobre versões

Este documento intencionalmente não fixa números de versão exatos de cada
biblioteca — isso é decidido e registrado no `requirements.txt`/`package.json`
no momento da implementação (fase 1 do roadmap), para usar as versões estáveis
disponíveis naquele momento.
