# 00 — Visão Geral e Objetivos

## Contexto

Decisões de day trade tomadas por humanos sofrem de viés emocional: impulso,
aversão a perda irracional, revenge trading após um erro. A premissa deste projeto
é que um sistema baseado em regras estatísticas e ML, com gestão de risco embutida
estruturalmente, remove essa fonte de erro — não elimina risco de mercado, mas
elimina o risco comportamental somado a ele.

## Objetivo do sistema

Construir um sistema que:

1. **Analisa** o mercado (inicialmente cripto via Binance) em tempo real, usando
   indicadores técnicos e modelos de ML para identificar condições favoráveis.
2. **Decide e executa** ordens automaticamente, sem intervenção humana no
   momento do trade, respeitando uma camada de gestão de risco não contornável.
3. **Expõe** todo esse comportamento em um dashboard visual — o operador humano
   deve conseguir ver o que o sistema está pensando e fazendo, mesmo sem agir
   diretamente sobre cada trade.
4. **Aprende continuamente**: analisa a própria performance diariamente, gera
   relatórios estruturados, e propõe mudanças versionadas ao próprio
   comportamento, sob revisão humana para mudanças de risco/lógica.

## Segundo módulo: apoio à decisão de aporte em ações (B3)

`14-modulo-acoes-b3.md` descreve uma frente independente — apoio à decisão de aporte
mensal em ações da B3, não um bot de execução automática. **Compartilha fundação de
engenharia com o bot de cripto** (ingestão, validação point-in-time, gate de promoção,
`changes/`), **mas não compartilha estado, dado, modelo nem runtime com ele**. Decisões,
resultados e conclusões de um módulo não transferem para o outro — nenhuma leitura deste
documento ou de qualquer `changes/` sobre um módulo deve ser aplicada ao outro sem
verificação própria. Status: proposta inicial, não implementada.

## Não-objetivos (explicitamente fora de escopo)

- Este projeto **não** é uma ferramenta de aconselhamento financeiro nem faz
  recomendações de alocação de capital ao usuário.
- **Não** busca eliminar risco de mercado — isso é impossível. Busca eliminar
  erro comportamental e operar com gestão de risco consistente.
- **Não** compete inicialmente com infraestrutura institucional de baixíssima
  latência (colocation, FPGA). O foco é robustez e consistência, não velocidade
  extrema.
- **Não** opera com capital real antes de: (a) validação em backtesting
  rigoroso, (b) validação em testnet, (c) aprovação humana explícita de ir a
  produção.

## Critérios de sucesso

Critérios de sucesso são técnicos/de engenharia, não financeiros:

- O sistema opera de forma **estável** por longos períodos sem intervenção
  manual (uptime, reconexão automática, sem duplicação de ordens).
- O comportamento do sistema é **totalmente observável**: todo trade, toda
  decisão de não-trade, e todo estado do modelo são visíveis no dashboard.
- O ciclo de aprendizado produz **relatórios úteis e acionáveis**, não ruído —
  medido pela taxa de `changes/` propostas que realmente melhoram métricas
  out-of-sample após revisão.
- A camada de risco é **auditável**: para qualquer trade histórico, é possível
  reconstruir por que o stop-loss, o tamanho de posição e o circuit breaker
  estavam configurados como estavam.
- Backtesting e comportamento em produção **não divergem de forma inexplicada**
  — divergência é sinal de bug ou de mudança de regime de mercado, e deve ser
  investigada, não ignorada.

## Princípios orientadores

- **Um humano aprova mudanças de risco e de lógica de negócio.** ML pode propor,
  não pode decidir sozinho o que é seguro.
- **Visibilidade antes de automação.** Cada capacidade nova primeiro aparece no
  dashboard em modo observação, depois em modo simulado (paper/testnet), só
  depois em execução real.
- **Specs antes de código.** Ver [`CLAUDE.md`](../CLAUDE.md).
- **Nenhuma parte deste projeto constitui aconselhamento financeiro.**
