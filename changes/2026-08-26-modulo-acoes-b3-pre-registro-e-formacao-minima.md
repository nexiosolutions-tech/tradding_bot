# 2026-08-26 — Módulo de Ações: critérios pré-registrados, log de experimentos por domínio, formação mínima

## Contexto

Usuário fechou a rodada anterior confirmando o achado mais importante dela — a
explicação "provavelmente identidade" (proposta pelo próprio usuário) estava errada, e
medir em vez de aceitar achou a causa real (piso de histórico mínimo, 41=41 exato). Antes
de rodar o backtest pela primeira vez, pediu duas guardas do mesmo espírito das já usadas
no bot: contabilizar toda configuração testada (o `experiment_log` com contador por
domínio, já desenhado na Seção 3 da spec como componente compartilhado) e declarar os
critérios de leitura do resultado antes de existir qualquer resultado. Só depois, tocar a
formação mínima e o backtest.

## 1. Critérios de leitura pré-registrados (Seção 9.1, nova)

Escritos e commitados **antes de rodar o backtest pela primeira vez** — a data no
cabeçalho da seção é a prova de que vieram antes do resultado, não depois. Três critérios,
os três juntos: bate o equal-weight em risco-ajustado; fica fora da nuvem nula com
p<0,05; não concentra vantagem num setor nem numa era de cobertura. Nenhum pode ser
adicionado nem relaxado depois do primeiro resultado sem `changes/` explicando por quê.
Registrada também a expectativa calibrada: três fatores, dois compartilhando lucro no
numerador, corte transversal de 100-210 empresas — chance de vantagem robusta não é alta,
e um resultado nulo não invalida a fundação construída até aqui.

## 2. `experiment_log` com contador por domínio (Seção 9.2, nova)

Já desenhado na Seção 3 (tabela de componentes herdados do bot): "mesmo componente,
campo de domínio na entrada, contadores separados por módulo". Implementado:
`ExperimentRecord` ganha campo `domain` (default `"bot"` — linhas antigas sem o campo
continuam carregando sem erro); `already_tried` fica escopado por domínio (um match de
tool/params entre bot e ações nunca suprime uma tentativa genuinamente nova no outro
domínio); `contar_experimentos_por_dominio` para o N do DSR. `DEFAULT_EXPERIMENTS_PATH_
ACOES` aponta para um arquivo físico separado (`learnings/experiments_acoes.jsonl`) — o
*código* é reutilizado, o *log* de cada domínio não se mistura, mesma disciplina de
"fundação de engenharia compartilhada, nunca estado ou dado" do `CLAUDE.md`.

3 testes novos, todos os 5 já existentes continuam passando sem alteração (backward
compatible por desenho — o default preserva o comportamento de antes desta mudança).

## 3. Formação mínima de carteira (`formacao_minima.py`, novo)

Top-N por `score_composto`, peso igual, desempate por ticker alfabético quando o score
empata exatamente (determinístico, não depende de ordem de iteração do banco). Empresa
sem score computável nunca entra, mesmo com vaga sobrando — carteira sai menor que N em
vez de forçar uma posição sem ranking. `N_PADRAO = 20`. Único ponto de acoplamento com o
resto do pipeline: consome `DecisaoResultado` de `build_decisao` diretamente, não
reimplementa nada da Seção 7.

5 testes novos: top-N com peso igual, empresa sem score nunca entra, desempate
alfabético, universo vazio, e todas sem score — os dois últimos como casos degenerados
que a carteira precisa devolver vazia, não quebrar.

## Testes + suíte

8 testes novos no total. Suíte completa (`--ignore=tests/test_binance_ws_live.py`):
443 passed.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Nova Seção 9.1 (critérios pré-registrados) e 9.2 (log de experimentos por domínio).
Preâmbulo de Seção 8 (já da rodada anterior) mantido, sem mudança.

## Pendente

- Backtest (Seção 9): simulação (custo/slippage), walk-forward com purga, os quatro
  benchmarks (IBOV/IBrX-100/SMLL, equal-weight, aleatória/nuvem nula, CDI), métricas por
  fold, teste de nulidade N≥100, DSR sobre todas as configurações via `experiment_log`
  (agora com contador por domínio pronto para uso). Próximo passo direto.
- Motor de carteira completo (Seção 8) — depois do backtest validar sinal, não antes
  (decisão já registrada na rodada anterior).

## Decisão

- Aprovado por: Brian — confirmou a correção da explicação do pico como o achado mais
  importante da rodada anterior; pediu as duas guardas de pré-registro antes de qualquer
  resultado de backtest existir, com justificativa explícita (evitar escolher o critério
  que o primeiro resultado bonito bateu); autorizou seguir para formação mínima e
  backtest (2026-08-26).
- Justificativa: pré-registrar depois que o backtest já rodou não vale nada — a prova de
  que os critérios vieram antes do resultado é a ordem em que foram commitados, não o
  conteúdo do texto. Fazer isso nesta rodada, antes de escrever uma linha do motor de
  simulação, é o que torna a leitura do resultado da próxima rodada auditável.
