# 09 — Aprendizado Contínuo (o sistema "vivo")

## Objetivo

Fazer o sistema revisar a própria performance diariamente e propor melhorias de
forma estruturada e versionada — sem contornar a exigência de revisão humana
para mudanças de risco ou de lógica de negócio (`CLAUDE.md`, regra 6).

## O ciclo diário

```
[Fim do dia de trading]
        │
        ▼
[Job de análise de performance]  ← lê apenas dados de produção (read-only)
        │
        ▼
[learnings/AAAA-MM-DD.md]  ← relatório objetivo, dados não julgamento
        │
        ▼
[Revisão: humana, ou sessão dedicada de Claude Code]
        │
        ▼
[changes/AAAA-MM-DD-descricao-curta.md]  ← proposta de mudança concreta
        │
        ▼
[Aprovação humana]
        │
        ▼
[Mudança entra em specs/ e depois em código]
```

## O job de análise (gera `learnings/`)

- Roda uma vez por dia (cron), **somente leitura** sobre a persistência de
  produção — nunca aplica mudanças diretamente.
- Analisa: quais setups/condições de score geraram acerto vs. erro, em que
  horários, em que condições de volatilidade, qual foi o comportamento do
  circuit breaker (se acionado), divergência entre backtest esperado e
  resultado real.
- Gera um arquivo `learnings/AAAA-MM-DD.md` com **achados objetivos** — números
  e observações, não decisões. Ver template em
  [`learnings/README.md`](../learnings/README.md).

## O backlog de mudanças (`changes/`)

- Cada achado relevante do `learnings/` que sugere uma ação concreta vira uma
  entrada em `changes/AAAA-MM-DD-descricao-curta.md`, com:
  - O que se propõe mudar (parâmetro, feature, threshold, lógica).
  - A evidência do `learnings/` que motiva a proposta.
  - O impacto esperado e como será validado (ligação com
    `07-backtesting-e-validacao.md`).
- Ver template em [`changes/README.md`](../changes/README.md).

## Regras de automação vs. revisão humana

Esta é a distinção central desta spec — reforçando `CLAUDE.md`:

| Tipo de mudança | Pode ser automatizado? |
|---|---|
| Retreino de modelo (mesmos hiperparâmetros/arquitetura/target) | Sim, desde que passe no critério de promoção de `07-backtesting-e-validacao.md` |
| Novo valor de hiperparâmetro dentro de um range já aprovado | Sim, via validação estatística automática |
| Nova feature | Não — proposta em `changes/`, revisão humana antes de entrar em `03-motor-de-features.md` |
| Mudança de threshold de decisão, position sizing, stop-loss, circuit breaker | Não — sempre revisão humana explícita, mesmo com evidência forte em `learnings/` |
| Mudança de arquitetura de modelo ou definição de target | Não — é uma mudança de spec, segue o processo SDD completo |

## Por que esse limite existe

Um sistema que analisa e aplica mudanças de risco sozinho, sem revisão, é
exatamente o cenário onde um bug na análise se transforma em prejuízo real da
noite para o dia, sem ninguém no circuito para pegar o erro antes que ele
aconteça. Separar "propor" de "aplicar" é o que torna esse ciclo seguro de
automatizar na parte de análise, sem herdar esse risco.

## Relação com o dashboard

A view "Aprendizado" do dashboard (`08-dashboard-e-visualizacao.md`) expõe o
histórico de `learnings/` e `changes/`, com o status de cada proposta —
mantendo o ciclo de aprendizado tão visível quanto a operação em tempo real.

## Status de implementação (Fase 5)

`backend/src/tradingbot/learning_engine/` — `daily_report.py` (lê
`trades`/`engine_events` do dia via `persistence/repository.py`, somente
leitura, reaproveita as mesmas funções de métrica do backtesting para que dia
real e backtest sejam julgados pelo mesmo critério) e
`change_proposals.py` (rascunha uma entrada em `changes/` só para achados com
amostra ≥ 10 trades — abaixo disso, o achado fica marcado "preliminar" no
`learnings/` e nenhuma proposta é gerada). Roda via `scripts/run_daily_learning.py`
(pensado para Railway Cron Jobs).

**Heurística atual é mecânica, não estatística/ML:** o único achado
implementado por ora é "win rate abaixo de 35% num horário UTC específico".
Isso é deliberadamente simples — o objetivo desta fase era o *fluxo*
`learnings/ → changes/ → revisão humana` funcionar de ponta a ponta, não ter
heurísticas sofisticadas. Novas heurísticas de achado são elas mesmas uma
mudança de spec/`changes/`, não algo a adicionar livremente depois.

**Ainda não validado contra dado de produção real** — não há trades reais
ainda (Fase 4 depende de chaves de testnet que o usuário ainda não configurou).
Toda a lógica está coberta por testes unitários com dados sintéticos
(`backend/tests/test_daily_report.py`, `test_change_proposals.py`); o primeiro
relatório "de verdade" só existe depois de um dia de operação real em testnet.
