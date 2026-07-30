# Trading Bot — Sistema de Análise e Execução Inteligente

Sistema de day trade automatizado (cripto/Binance) que analisa mercado em tempo real,
gera sinais via modelos de ML, executa ordens com gestão de risco embutida, e aprende
continuamente a partir da própria performance.

Este projeto é desenvolvido no modelo **SDD (Spec-Driven Development)**: toda
funcionalidade nasce de uma especificação em `.md` antes de existir código. O código é
a implementação de uma spec, nunca o contrário. Isso vale tanto para humanos quanto
para o Claude Code operando dentro do Cursor.

## Aviso importante

Este é um projeto de engenharia de software. As decisões aqui documentadas são
técnicas (arquitetura, modelos, infraestrutura), não recomendações financeiras.
Nenhuma spec deste projeto deve ser lida como orientação de investimento.

## Como navegar este repositório

1. **[`CLAUDE.md`](./CLAUDE.md)** — a "constituição" do projeto. Regras não
   negociáveis, convenções de código, e como o agente (Claude Code) deve operar
   aqui. Leia isso antes de qualquer outra coisa se você é um agente de IA.
2. **`specs/`** — especificações funcionais e técnicas, em ordem de leitura recomendada
   (prefixo numérico). Cada spec descreve o *contrato* de um módulo: o que ele recebe,
   o que ele entrega, e as regras que não podem ser violadas.
3. **`learnings/`** — relatórios diários gerados automaticamente pelo motor de
   aprendizado, analisando a performance do sistema. Ver [`learnings/README.md`](./learnings/README.md).
4. **`changes/`** — backlog de mudanças propostas a partir dos aprendizados, pendentes
   de revisão humana antes de virar spec/código. Ver [`changes/README.md`](./changes/README.md).

## Ordem de leitura das specs

| # | Spec | Conteúdo |
|---|------|----------|
| 00 | [`00-visao-geral-e-objetivos.md`](./specs/00-visao-geral-e-objetivos.md) | Visão, objetivos, não-objetivos, critérios de sucesso |
| 01 | [`01-arquitetura-sistema.md`](./specs/01-arquitetura-sistema.md) | Camadas do sistema e contratos entre módulos |
| 02 | [`02-ingestao-de-dados.md`](./specs/02-ingestao-de-dados.md) | Conexão com a Binance, streams, buffers |
| 03 | [`03-motor-de-features.md`](./specs/03-motor-de-features.md) | Indicadores incrementais, feature store |
| 04 | [`04-modelo-ml-e-scoring.md`](./specs/04-modelo-ml-e-scoring.md) | Modelo preditivo, treino, retreino, versionamento |
| 05 | [`05-gestao-de-risco.md`](./specs/05-gestao-de-risco.md) | Position sizing, stop-loss, circuit breaker, kill switch |
| 06 | [`06-camada-de-execucao.md`](./specs/06-camada-de-execucao.md) | Execução de ordens, testnet/mainnet, estados do sistema |
| 07 | [`07-backtesting-e-validacao.md`](./specs/07-backtesting-e-validacao.md) | Simulação event-driven, walk-forward, critérios de promoção |
| 08 | [`08-dashboard-e-visualizacao.md`](./specs/08-dashboard-e-visualizacao.md) | Painel: views, gráficos, play/pause, timer |
| 09 | [`09-aprendizado-continuo.md`](./specs/09-aprendizado-continuo.md) | Ciclo diário de aprendizado e o fluxo learnings → changes → spec |
| 10 | [`10-stack-tecnica-e-dependencias.md`](./specs/10-stack-tecnica-e-dependencias.md) | Stack, estrutura de pastas, ambientes |
| 11 | [`11-roadmap-e-fases.md`](./specs/11-roadmap-e-fases.md) | Fases de entrega, do zero até execução real |

## Status atual

**Fase 1 — Infraestrutura de dados e backtesting (em andamento).** Implementados:
ingestão (spec 02), motor de features incremental (spec 03), gestão de risco
estrutural (spec 05) e motor de backtesting event-driven (spec 07), com um
backtest de ponta a ponta já validado contra dados históricos reais da Binance.
Ver [`backend/README.md`](./backend/README.md) para como rodar. Modelo de ML
(spec 04), execução real (spec 06), dashboard (spec 08) e aprendizado contínuo
(spec 09) ainda não foram implementados — ver
[`specs/11-roadmap-e-fases.md`](./specs/11-roadmap-e-fases.md) para as próximas fases.
