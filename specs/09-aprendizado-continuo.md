# 09 — Aprendizado Contínuo (o sistema "vivo")

## Objetivo

Fazer o sistema investigar a própria performance de forma contínua e autônoma —
não só analisar, mas formular hipóteses, rodar experimentos, validá-los e
redigir a mudança pronta para revisão — sem nunca aplicar sozinho uma mudança
de risco, execução ou arquitetura (`CLAUDE.md`, regra 6). A fronteira entre
"autônomo" e "exige humano" não é "análise vs. ação" — é **"proposta pronta
vs. aplicada"**. Tudo até o ponto de gerar uma entrada completa e validada em
`changes/` pode rodar sozinho; cruzar de `pendente` para `aplicada` continua
exigindo uma decisão humana explícita, registrada.

## Os quatro elementos do loop

Todo agente de raciocínio contínuo precisa de quatro peças. Esta seção fixa o
que cada uma é *neste projeto*, não em abstrato:

1. **Modelo de raciocínio** — um LLM (Claude) que lê o estado atual (seção
   "Memória de estado" abaixo) e decide a próxima ação: rodar um experimento,
   ler mais dado, encerrar a investigação, ou redigir uma proposta.
2. **Ferramentas** — os scripts já existentes em `backend/scripts/`
   (`train_model.py`, `sweep_thresholds.py`, `feature_importance.py`,
   `run_backtest.py`) e as funções de `learning_engine/`, expostas como ações
   que o loop pode invocar — os mesmos scripts que hoje um humano roda
   manualmente numa sessão de investigação.
3. **Memória de estado** — `learnings/`, `changes/` e um novo índice de
   experimentos (ver abaixo), tudo em arquivo, versionado.
4. **Controlador de loop** — substitui o job único de `run_daily_learning.py`
   por um ciclo iterativo com orçamento e condição de parada explícitos (ver
   "O ciclo" abaixo).

## Isolamento e limites estruturais (não negociáveis, mesmo padrão de `CLAUDE.md`)

Estas invariantes existem para que "autônomo" nunca signifique "com acesso ao
que pode perder dinheiro":

1. **O loop nunca tem credenciais de execução.** Não recebe
   `BINANCE_API_KEY`/`BINANCE_API_SECRET`, não importa `execution/client.py`
   nem `execution/orchestrator.py`. Só lê histórico já persistido (trades,
   `engine_events`) e roda backtests sobre dado histórico — a mesma
   separação que já existe entre `backtesting/` (sem rede/execução) e
   `execution/` (com rede/execução).
2. **O loop nunca escreve em `main`.** Toda saída do loop — proposta em
   `changes/`, rascunho de spec, diff de código, testes — vai para uma branch
   dedicada (ou fica como patch não commitado). Abrir PR é permitido; fazer
   merge não é.
3. **O loop nunca marca sua própria proposta como `aprovada` ou `aplicada`.**
   Só quem revisa (humano, ou uma sessão de Claude Code dirigida por humano,
   como hoje) muda esse campo — mesma regra do template de `changes/`.
4. **Orçamento por ciclo é explícito e finito.** Máximo de N iterações (a
   fixar na implementação, ex. 10) e/ou tempo máximo de execução por ciclo —
   nunca um loop sem teto que possa rodar indefinidamente consumindo API/custo
   sem supervisão.

## O ciclo

```
[Novo dia de dado real disponível]         ← cadência inicial: diária, como hoje;
        │                                    nada aqui impede aumentar a frequência
        ▼                                    depois, mas o dado (um dia de trading)
[Loop de investigação — até N iterações]      não muda mais rápido que isso por ora.
    │
    ├─ 1. Lê memória de estado (learnings/, changes/ pendentes/aplicadas,
    │     índice de experimentos) — nunca repete um experimento já registrado
    │     com o mesmo resultado.
    ├─ 2. Modelo de raciocínio decide: investigar mais, ou encerrar o ciclo.
    ├─ 3. Se investigar: invoca uma ferramenta (backtest, sweep, SHAP,
    │     comparação backtest-vs-produção), registra o resultado na memória.
    ├─ 4. Achado com evidência suficiente (mesmos critérios estatísticos já
    │     usados — specs/07: amostra mínima, validação out-of-sample)?
    │        → Sim: redige changes/ completo (evidência + proposta + números
    │          reais de validação já rodada) com **Status: pendente**, e
    │          encerra o ciclo. **v1 (implementada): só o texto da proposta**
    │          — rascunho de spec, diff de código e testes gerados
    │          automaticamente, e abrir PR numa branch dedicada, ficam para
    │          uma extensão futura (ver "Status de implementação" abaixo);
    │          por ora, quem aprova a proposta também escreve o código, como
    │          já acontece hoje numa sessão de Claude Code dirigida por humano.
    │        → Não: volta ao passo 2, até esgotar o orçamento de iterações.
    ▼
[changes/AAAA-MM-DD-descricao.md, pendente]  ← ponto de parada estrutural
        │
        ▼
[Revisão humana do PR/proposta]               ← única porta de decisão
        │
        ▼
[Aprovado → aplicada, spec+código entram | Rejeitado → rejeitada, registrado]
```

## Fronteira autônomo vs. revisão humana

| Tipo de ação | Pode ser autônomo? |
|---|---|
| Ler `learnings/`/`changes/`/dado histórico, formular hipótese | Sim |
| Rodar backtest, sweep de hiperparâmetro, análise SHAP sobre dado histórico | Sim |
| Redigir a entrada completa em `changes/` (evidência + proposta + números reais de validação), com **Status: pendente** | Sim — implementado |
| Redigir também rascunho de spec + diff de código + testes, e abrir PR numa branch dedicada | Sim, é a visão da spec — **ainda não implementado** (v1 entrega só o texto da proposta) |
| Retreino de modelo dentro da mesma arquitetura/target, promovido automaticamente se bater specs/07 | Sim — já permitido hoje, sem mudança |
| Marcar uma proposta como `aprovada`/`rejeitada`/`aplicada` | **Não** — sempre humano |
| Fazer merge do PR em `main` | **Não** — sempre humano |
| Qualquer mudança de threshold de decisão, position sizing, stop-loss, circuit breaker chegar a rodar em produção | **Não** — só depois de `aplicada` |
| Qualquer mudança de arquitetura de modelo ou definição de target chegar a rodar em produção | **Não** — só depois de `aplicada` |

A diferença para a versão anterior desta spec: antes, o motor só *analisava*
e deixava a investigação/validação para uma sessão humana de Claude Code.
Agora, a investigação e validação em si — a parte demorada — também é
autônoma; só a decisão final de aplicar continua sendo humana. O motor entrega
uma proposta já testada e pronta para um "aprovar" ou "rejeitar" rápido, não
um achado cru que ainda precisa de trabalho.

## Memória de estado

- `learnings/AAAA-MM-DD.md` — achados objetivos do dia, como hoje.
- `changes/AAAA-MM-DD-descricao.md` — propostas, como hoje, mas agora podendo
  chegar já com validação embutida (ver template atualizado em
  `changes/README.md` — a seção "Validação proposta" passa a conter o
  resultado real do backtest/experimento, não só uma promessa de validação
  futura).
- **Novo**: um índice de experimentos (formato a definir na implementação,
  ex. `learnings/experiments.jsonl`) registrando cada hipótese testada,
  parâmetros, e resultado — para o loop nunca repetir um experimento já
  feito e para um humano auditar o que o loop tentou, mesmo quando não gerou
  proposta nenhuma.

## Por que esse limite existe

Um sistema que investiga e aplica mudanças de risco sozinho, sem revisão, é
exatamente o cenário onde um bug na análise se transforma em prejuízo real da
noite para o dia, sem ninguém no circuito para pegar o erro antes que ele
aconteça — e bugs de análise são reais e já aconteceram neste projeto mais de
uma vez (ex. indexação errada de dia da semana, filtro de regime que piorava
o resultado até ser recalibrado corretamente). Ampliar o que o motor pode
*investigar e propor* sozinho não muda esse risco, porque a decisão de
aplicar continua humana; automatizar a *aplicação* mudaria, e é exatamente
isso que esta spec continua recusando a fazer.

## Relação com o dashboard

A view "Aprendizado" do dashboard (`08-dashboard-e-visualizacao.md`) expõe o
histórico de `learnings/` e `changes/`, com o status de cada proposta, e passa
a também expor o que o loop está investigando *agora* (iteração atual,
hipótese em teste) — mantendo o ciclo de aprendizado tão visível quanto a
operação em tempo real, agora com mais a mostrar.

## Status de implementação (Fase 5)

**v1 implementada em 2026-08-01, no mesmo dia da reescrita da spec** (a spec
foi escrita e commitada primeiro, código depois, por SDD):

- `model/evaluation.py::evaluate_config` — walk-forward completo para uma
  config, extraído de `train_model.py`/`sweep_thresholds.py` (que passaram a
  reusá-lo) para não duplicar essa lógica uma terceira vez.
- `model/importance.py::compute_feature_importance` — SHAP extraído de
  `scripts/feature_importance.py` do mesmo jeito. A extração pegou um bug
  real no processo: correlação de direção virava `NaN` quando uma feature
  tinha SHAP constante (ex. `macd_pct`, que o modelo nunca usa) — corrigido.
- `learning_engine/experiment_log.py` — memória de experimentos
  (`learnings/experiments.jsonl`, append-only) com `already_tried` para
  dedup.
- `learning_engine/tools.py` — as quatro ferramentas que o loop pode chamar
  (`evaluate_strategy_config`, `analyze_feature_importance`,
  `list_recent_learnings`, `list_pending_changes`), fechadas sobre o
  histórico de candles buscado uma vez no início do ciclo.
- `learning_engine/agentic_loop.py` — o controlador (`run_agentic_cycle`):
  orçamento de iterações, dedup contra a memória, e `draft_change_proposal`
  (sempre `Status: pendente`). `ReasoningClient` é um Protocol — a lógica do
  controlador é testada inteiramente com `FakeReasoningClient` (scriptado),
  sem precisar de API key. `AnthropicReasoningClient` é a implementação real
  (tool-use da API do Claude), escrita mas **não exercitada contra a API de
  verdade neste ambiente** (sem `ANTHROPIC_API_KEY` de serviço configurada
  aqui) — validar um ciclo real antes de rodar sem supervisão.
- `scripts/run_agentic_learning.py` — entry point (mesma cadência de
  `run_daily_learning.py`).
- Testes: 187 passando no total, incluindo checagem estrutural (via `ast`,
  não busca por substring) de que `agentic_loop.py`/`tools.py` nunca
  importam `tradingbot.execution`, e um teste explícito de que o loop nunca
  produz uma proposta com status diferente de `pendente`.

**O que a v1 explicitamente não faz ainda** (é a lacuna entre a visão da
spec e o código de hoje, não um erro): a proposta gerada é só texto
(evidência + proposta + validação já rodada) — rascunho de spec, diff de
código, testes automáticos e abertura de PR continuam manuais, feitos por
quem revisa a proposta (hoje, uma sessão de Claude Code dirigida por
humano, como esta). Fechar essa lacuna é a próxima extensão natural, não
escopo desta rodada.

O motor anterior (`daily_report.py`/`change_proposals.py`, via
`scripts/run_daily_learning.py`) continua funcional e não foi removido —
`list_recent_learnings` no novo loop lê exatamente o que ele gera.

**Ainda não validado contra dado de produção real** — o motor de execução
(Fase 4) só começou a gerar dado real em 2026-08-01, no mesmo dia. O primeiro
ciclo do loop só tem algo substancial para investigar depois de alguns dias
de operação real acumulados.

Ver `changes/2026-08-01-loop-agentico-aprendizado-continuo.md` para a decisão
que motivou a reescrita da spec, e o commit desta mesma data para a
implementação v1.
