# 2026-08-27 — Módulo de Ações: motor de backtest, bug de quebra de nível, primeiro resultado (nulo)

## Contexto

Com os critérios de leitura e o log de experimentos por domínio já pré-registrados
(rodada anterior), o usuário autorizou construir o motor de backtest com o que já tinha
fonte real verificada — CDI, equal-weight do universo, nuvem nula — deixando
IBOV/IBrX-100/SMLL como verificação separada (fonte ainda não confirmada, Seção 9.4).
Pediu também o registro, antes do índice existir, da armadilha price-only/total-return
e propôs um benchmark adicional (ponderada por liquidez) que não depende de fonte
externa.

## 1. Spec 9.3/9.4: armadilha price-only/total-return + status de fonte por benchmark

Registrado **antes** de qualquer benchmark de índice existir: IBOV é retorno total,
a série deste módulo é price-only, misturar os dois regimes subestima a estratégia
sistematicamente (4-6 p.p./ano no Brasil). Regra: consistência acima de completude,
nunca um lado price-only e o outro total-return. Tabela de status por fonte, benchmark
a benchmark, para a ordem de construção (backtest antes do motor de carteira completo)
não virar licença para trocar fonte real por aproximação não verificada.

## 2. `cdi.py` + `CdiTaxa` (novo)

Mesma fonte já declarada (BCB SGS 12), mesmo padrão de `ipca.py`. Diferente do IPCA
(encadeado numa base fixa), o CDI é consumido sob demanda por `cdi_equity_curve` — taxa
diária composta no intervalo exato de cada curva simulada, nunca número-índice
comparado fora do módulo. 7 testes com valores reais do BCB (jan/2015), incluindo
degradação sem dado ingerido.

## 3. `backtest.py` (novo) — motor de simulação, nulidade e walk-forward

- Métricas de curva de equity nativas (`total_return_pct`, `volatility_pct`,
  `max_drawdown`, `return_over_drawdown/volatility`) — nunca importa
  `backtesting/metrics.py` do bot (runtime não compartilhado, `CLAUDE.md`).
- Seleção (quem entra) separada de política de peso (como pesa): `selecionar_top_n`
  reusa `formar_carteira_minima` (Seção 8) sem reimplementar; `selecionar_universo_
  completo` cobre os dois benchmarks derivados do universo. `POLITICA_PESO_IGUAL` e
  `POLITICA_PESO_LIQUIDEZ` (nova — pondera por `volume_mediano_as_of`, o mesmo dado já
  usado no piso de liquidez).
- `simulate_estrategia`: seleção muda só em decisão anual (fundamento é anual),
  reequilíbrio mensal (custo de turnover a cada mês, não só na decisão), regra de saída
  por perda de liquidez (Seção 8) checada todo mês com penalidade de slippage — nunca
  deixa uma posição desaparecer sem custo.
- `teste_nulidade`: permuta score×retorno anual "de um tiro" (preço na decisão -> preço
  na próxima), independente por ano, N>=100 obrigatório — mais barato que rodar a
  simulação mensal completa por permutação, sem perder o que o teste mede.
- `walk_forward_folds`: folds contíguos de decisões anuais. **"Purga" não tem
  equivalente aqui** — os pesos dos fatores são fixos a priori (`PESOS_PADRAO`), nunca
  ajustados a partir de dado, então não existe parâmetro treinado que pudesse vazar
  entre folds. A garantia equivalente é estrutural (cada fold só agrega retorno
  realizado dentro do próprio intervalo), registrado explicitamente para não inventar
  uma janela de purga sem propósito real.
- `registrar_experimento`: wrapper de `experiment_log.py` com `domain="acoes"` (Seção
  9.2), arquivo físico `learnings/experiments_acoes.jsonl`.
- `DecisaoEmpresa` ganhou campo `volume_mediano` (Seção 7.6) — necessário para a
  política de peso por liquidez, não existia antes porque nada consumia esse dado fora
  de `universo_elegivel.py`. `preco_as_of` e `volume_mediano_as_of` promovidas a
  públicas (antes `_preco_as_of`/`_volume_mediano`, privadas de `decisao.py`/
  `universo_elegivel.py`) — `backtest.py` reusa a mesma consulta point-in-time, nunca
  reimplementada.

25 testes novos (métricas, políticas de peso, seleção, simulação, custo, saída por
liquidez, nulidade, folds, log de experimentos), `build_decisao` monkeypatchado por um
dublê determinístico para isolar a lógica nova da máquina de ingestão pesada (mesma
disciplina já usada em `test_build_decisao_nao_reimplementa_compute_score_composto`).

## 4. Achado: quebra de nível virando retorno (Seção 9.5)

Primeira rodada real devolveu 931% em 11 anos — implausível. Usuário propôs não aceitar
e investigar a distribuição de retornos mensais antes de qualquer benchmark; a cauda
superior (5 maiores meses = +310 p.p.) coincidia no calendário com eventos
`is_level_break=True` reais, o maior (`BRPR3 EG`, 2023-02-24) explicando sozinho o mês
dominante. Causa raiz confirmada por leitura de código antes de medir: `preco_as_of`
foi desenhada para avaliação point-in-time (nunca precisa de ajuste por evento
societário — é uma razão numa única data) e reusada em `backtest.py` para calcular
retorno **entre duas datas**, o único uso que precisa da checagem contra
`CorporateEventFlag` que a própria spec já documentava como responsabilidade da
consulta, nunca da ingestão.

Corrigido com `tem_quebra_de_nivel` (nova função): quando o intervalo entre duas
marcações atravessa uma quebra de nível, o valor da posição fica congelado nesse passo
— `CorporateEventFlag` não carrega magnitude (a COTAHIST não tem razão de
bonificação/grupamento), então não dá para *ajustar* numericamente, só para *detectar*
e recusar a interpretar a razão de preço bruta como retorno real. Aplicada em
`_marcar_e_ajustar_mes` (simulação) e `_retorno_anual_por_ticker` (teste de nulidade).

**Ablação controlada, mesma seleção, único fator variado**: retorno caiu de 931% para
119% em 11 anos — queda de ~8x, confirmando que a maior parte do número original era
artefato de dado bruto, não sinal.

## 5. Resultado (Seção 9.6): nulo nos três critérios pré-registrados

Candidato (top-20, peso igual) perde do equal-weight em risco-ajustado (16,42 vs. 18,81
retorno/volatilidade), fica dentro da nuvem nula (p=0,52, N=200 permutações). Os três
fatores não têm poder preditivo detectável no período — resultado nulo, exatamente a
expectativa calibrada registrada na Seção 9.1 antes de qualquer resultado existir.
Achado adicional: nenhuma das três carteiras de ações bateu o CDI no período. Por fold,
quase toda vantagem aparente do candidato vem de um único fold antigo (2015-2019,
RoV=12,6 vs. 0,75 e 1,80 nos dois seguintes) — sem vantagem robusta e estável.

## Testes + suíte

32 testes novos (`test_acoes_cdi.py`: 7, `test_acoes_backtest.py`: 25 incluindo os 4 do
achado da Seção 9.5). Suíte completa (`--ignore=tests/test_binance_ws_live.py`): 475
passed.

## Pendente

- Fonte real de IBOV/IBrX-100/SMLL (Seção 9.4) — verificação separada, próximo passo
  quando retomado.
- Motor de carteira completo (Seção 8) — resultado nulo não invalida a fundação, mas
  também não justifica construir tetos/sobra/lote antes de entender se algum outro
  desenho de fatores/formação teria sinal; decisão de continuar ou não fica em aberto
  para o usuário.

## Decisão

- Aprovado por: Brian — autorizou construir o motor com CDI/equal-weight/nuvem nula
  agora, tratando fonte de índice como verificação separada; propôs o benchmark
  ponderado por liquidez; identificou o resultado de 931% como implausível e propôs
  quebra de nível como hipótese principal (confirmada), pedindo verificação da
  distribuição de retornos mensais antes de aceitar qualquer benchmark rodando sobre a
  série contaminada (2026-08-27).
- Justificativa: um resultado extremo pede ceticismo antes de leitura, não depois —
  medir a cauda da distribuição custou minutos e evitou publicar um resultado inteiro
  baseado em artefato de dado bruto não ajustado. O resultado final (nulo) é a resposta
  honesta que a Seção 9.1 já esperava como cenário provável, obtida sem atalho.
