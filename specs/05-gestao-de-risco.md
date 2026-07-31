# 05 — Gestão de Risco

Esta é a spec mais importante do projeto. Os riscos aqui não são de bug de
software abstrato — são de perda de capital real. Nada nesta spec é
contornável por configuração informal ("decidido na hora"); tudo é estrutural
no código.

## Princípio

O modelo de ML pode errar a previsão sem que isso quebre a conta. A camada de
risco é o que garante isso — ela é independente da qualidade do modelo.

## Requisitos funcionais

### Position sizing
- Sempre calculado como **percentual do capital disponível**, nunca valor
  monetário fixo hardcoded.
- O percentual usado é função de: capital total, confiança/score do sinal
  (dentro de limites), e exposição já aberta em outras posições.
- Existe um teto de exposição total simultânea (ex.: soma de todas as posições
  abertas não excede X% do capital) — parâmetro de configuração, não decisão
  ad-hoc por trade.

### Stop-loss obrigatório
- Toda ordem de entrada é enviada **junto com** (ou imediatamente seguida, de
  forma atômica/garantida) de uma ordem/condição de stop-loss.
- Não existe caminho de código — nem modo de debug, nem flag de teste — que
  permita abrir posição sem stop-loss associado. Ver `CLAUDE.md`, regra 2.
- Stop-loss é definido antes do envio da ordem de entrada, não calculado
  "depois de ver como o mercado reage".

### Circuit breaker
- Se o sistema perder X% do capital em uma janela de tempo Y (parâmetros em
  `changes/`, versionados), a camada de orquestração transita para o estado
  `PARADO_CIRCUIT_BREAKER` (ver `01-arquitetura-sistema.md`).
- Esse estado **não se recupera automaticamente**. Requer reconhecimento humano
  explícito (ação no dashboard) para retomar operação.
- O circuit breaker é avaliado continuamente, não só no fechamento de trade —
  uma sequência de perdas não realizadas (drawdown intra-trade) também conta
  conforme os critérios definidos.
- Dois gatilhos complementares, ambos precisam bater `circuit_breaker_loss_pct`
  para não deixar buraco de cobertura entre eles:
  1. **Janela rolante** (`circuit_breaker_window_minutes`): drawdown desde o
     pico *dentro dessa janela*. Pego perdas rápidas e concentradas.
  2. **Pico de sessão**: drawdown desde o pico de capital de toda a sessão
     atual (nunca descartado por tempo, só reiniciado no reconhecimento
     humano). Fecha a lacuna que a janela rolante sozinha deixa: uma perda
     lenta e constante (ex.: 1%/10min por várias horas) nunca aparece dentro
     de nenhuma janela isolada, porque o pico de referência "escorrega" junto
     com a queda — mas o pico de sessão continua fixo e detecta o acúmulo.
  - Ao reconhecer o circuit breaker, o pico de sessão é reiniciado para o
    capital do momento — sem isso, a próxima atualização de capital
    re-acionaria o breaker instantaneamente, antes de o capital ter chance de
    se recuperar.

### Idempotência de ordens
- Toda ordem enviada usa um `client order id` determinístico e idempotente —
  se a conexão cair e o sistema reenviar por retry, a exchange rejeita a
  duplicata em vez de executar duas vezes.
- Reconciliação periódica entre estado local (o que o sistema acha que tem
  aberto) e estado real na exchange (fonte de verdade) — divergência dispara
  alerta e, dependendo da severidade, pausa a execução até resolução.

### Kill switch manual
- Botão/comando explícito no dashboard que interrompe toda nova execução
  imediatamente (equivalente a forçar `PAUSADO`), independente do estado do
  circuit breaker automático. Sempre disponível, mesmo durante posição aberta
  (nesse caso, para novas entradas — não força liquidação de posição existente
  sem confirmação adicional, para evitar liquidar em condição de mercado ruim
  por acidente).

## Auditoria

- Para qualquer trade histórico, deve ser possível reconstruir: qual era o
  capital disponível no momento, qual percentual foi usado, onde estava o
  stop-loss, e qual era o estado do circuit breaker — sem isso, a gestão de
  risco não é verificável e essa spec não está sendo cumprida.

## Status de implementação (Fase 4)

`backend/src/tradingbot/risk/manager.py` implementa sizing percentual,
rejeição estrutural de ordem sem stop-loss (`MissingStopLossError`) e circuit
breaker sem recuperação automática — usado tanto pelo backtesting (Fase 1)
quanto pelo `Orchestrator` real (Fase 4), o mesmo código em ambos os
contextos. **Reconciliação de posição/equity no startup do processo**
(2026-07-31, ver `06-camada-de-execucao.md`) fecha a lacuna mais comum na
prática — um restart (local, redeploy ou crash) esquecer silenciosamente uma
posição real já persistida, ou resetar o capital acumulado de volta ao
valor de configuração. Uma lacuna mais estreita ainda permanece — ver
`06-camada-de-execucao.md`. Fechar as lacunas restantes é
pré-requisito antes de qualquer capital real (Fase 6), não da validação em
testnet.

O gatilho de pico de sessão (queda lenta acumulada) foi adicionado em
2026-07-30 a partir de achado de auditoria técnica — ver
[`changes/2026-07-30-circuit-breaker-queda-lenta.md`](../changes/2026-07-30-circuit-breaker-queda-lenta.md).

## O que esta spec não define

- Valores específicos de percentual de risco, drawdown máximo tolerado, ou
  alavancagem. Esses são parâmetros de configuração, e sua escolha é uma
  decisão do operador humano (usuário), não uma recomendação de engenharia —
  ver aviso em [`00-visao-geral-e-objetivos.md`](./00-visao-geral-e-objetivos.md).
  Esta spec garante apenas que, uma vez escolhidos, esses parâmetros são
  **respeitados estruturalmente pelo código**.
