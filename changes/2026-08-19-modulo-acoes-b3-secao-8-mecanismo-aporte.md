# 2026-08-19 — Módulo de Ações: mecanismo de sugestão de aporte (Seção 8 fechada)

## Contexto

Seção 8 já tinha a regra de saída por perda de liquidez (rodada anterior) e a lista de
saídas, mas a "sugestão de aporte" em si era só um item de lista ("respeita tetos
configuráveis") sem mecanismo especificado — o mesmo nível de vagueza que as Seções 6 e 7
tinham antes de serem detalhadas. Fechando a Seção 8 no mesmo padrão de rigor.

## Decisão de desenho: regra gulosa determinística, não otimizador de portfólio

Considerada e descartada a alternativa óbvia (otimização de portfólio com função-objetivo,
ex. Markowitz sobre o score como proxy de retorno esperado): o princípio fundador da spec
(Seção 1, "o sistema ordena e evidencia, quem decide é o usuário") não combina com uma
caixa-preta de otimização decidindo alocação por trás de uma função de utilidade. Adotado
em vez disso um algoritmo guloso sobre o ranking da Seção 7 — percorre do maior score ao
menor, aloca o que falta em cada candidato respeitando tetos por ativo/setor, pula (não
reduz) quando um candidato violaria o teto, reporta sobra não alocável explicitamente em
vez de forçar alocação. Cada decisão é rastreável até uma linha de regra escrita, mesma
disciplina de "regra declarada, não implícita" já usada nas Seções 6 e 7.

## Achado verificado antes de escrever a regra de lote

A sugestão de compra precisa lidar com o caso em que o valor a alocar não fecha um lote
padrão (100 ações). Em vez de assumir a existência de um mercado fracionário na B3, checado
o layout oficial da COTAHIST (já baixado nesta sessão) — tabela de `TPMERC` confirma
`020 = FRACIONÁRIO`, distinto de `010 = VISTA` (usado pela Seção 6 para o filtro de
liquidez). Regra: sugestão usa o mercado fracionário quando o valor não fecha lote padrão,
mesma disciplina de regra declarada e idêntica em backtest/produção.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`, Seção 8

- Entradas detalhadas: exclusões manuais, tetos por ativo/setor com default versionado,
  valor mínimo de posição.
- Mecanismo de sugestão especificado em 5 passos (algoritmo guloso, sobra explícita, regra
  de lote/fracionário).
- Restrição estrutural reforçada: este motor nunca envia ordem (referência cruzada à
  Seção 2).
- Saída "sugestão de aporte" atualizada para referenciar o mecanismo e o caso de sobra não
  alocada.

## Pendente

- Nenhum código escrito — desenho de spec.
- Default versionado dos tetos por ativo/setor ainda não tem valor numérico proposto —
  fica para quando a Fase 3 (motor de carteira) começar a ser implementada.

## Decisão

- Aprovado por: Brian — "Fecha a Seção 8, e o bot te espera num ponto muito melhor do que
  estava ontem" (2026-08-19), depois de registrar o marco do teste de nulidade do bot e as
  guardas de tuning, com a recomendação explícita de terminar o desenho de Ações antes de
  trocar de contexto para o bot.
- Justificativa: um mecanismo de alocação não especificado deixaria a Seção 8 no mesmo
  estado vago que as Seções 6 e 7 tinham antes de serem corrigidas nesta sessão — melhor
  fechar agora, com o mesmo padrão de regra declarada e auditável, do que descobrir a
  ambiguidade na implementação.
