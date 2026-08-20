# 2026-08-19 — Módulo de Ações: Seção 6 (universo elegível) e Seção 7 (fatores) detalhadas

## Contexto

Com a fonte de preço confirmada (Seção 5.3, COTAHIST primária), a Seção 6 deixou de
depender de um contrato desconhecido — usuário apontou explicitamente que escrever 6
antes disso seria "escrever contra um contrato desconhecido", e que 7 depende de 6 (fator
só se calcula sobre o universo que já foi definido). Nesta rodada as duas seções saem de
uma linha cada para desenho completo, mais um achado que afeta a Seção 9.

## Achado que motivou a mudança mais importante: proventos deslistados não são adiáveis

O item mais aberto da Seção 5.3 (não existe fonte bulk gratuita de proventos, `brapi.dev`
só cobre líquidos atuais) parecia adiável para perto do início da Fase 1. Usuário
corrigiu: não bloqueia a Seção 6, mas morde a 7 e o backtest de um jeito específico — se
há provento dos sobreviventes e não dos deslistados, o retorno total é medido de formas
diferentes em dois subgrupos do mesmo universo, com o erro concentrado exatamente na
população que existe para corrigir survivorship. Pior que um erro uniforme.

**Regra registrada, independente de quando a fonte de proventos for resolvida:**
price-only para todo o universo, ou total-return só quando há provento coberto para
100% dos nomes elegíveis naquela data — nunca misturado. Consequência direta: a família
de dividendos (Seção 7) fica marcada como não utilizável em fator validado por backtest
até a fonte existir, e a Seção 9 (simulação) foi corrigida — dizia "dividendos
reinvestidos ou não (configurável)", o que permitiria reinvestimento parcial e violaria a
regra que acabou de ser escrita ao lado.

## Seção 6 — o que ficou fechado

Duas perguntas condicionavam o texto e já estavam respondidas pela rodada anterior
(`changes/2026-08-19-modulo-acoes-b3-fonte-preco-cotahist.md`), sem precisar de nova
verificação: COTAHIST devolve volume financeiro em campo próprio (`VOLTOT`, separado de
`QUATOT`) e cobre papéis deslistados (`OGXP3` no arquivo de 2013, ausente em 2024).
Survivorship resolvido na origem — Seção 6 herda isso como dado, não precisa resolver de
novo.

- Liquidez por **mediana** de `VOLTOT` em janela móvel (não média — média é dominada por
  dias de pico e superestima liquidez sustentável).
- Uma classe por empresa: a mais líquida na data de decisão, **registrada por data** (não
  fixa), para rastrear troca de classe mais líquida ao longo do histórico.
- Exclusões declaradas: BDR/ETF/FII via campos da COTAHIST, recuperação judicial (flag
  CVM), histórico insuficiente para os fatores.
- Universo materializado por data de decisão (mesmo princípio da janela fixa do bot —
  reprodutibilidade não pode depender da lógica do filtro não ter mudado depois).
- Assertiva de tamanho mínimo ligada diretamente ao critério transversal da Seção 10 —
  universo abaixo do piso falha explicitamente, não produz ranking sobre amostra pequena
  demais silenciosamente.

## Seção 7 — três armadilhas

1. **Matriz de aplicabilidade de fator por setor.** Banco não tem EV/EBITDA nem dívida
   líquida no sentido usual (ativo é majoritariamente crédito concedido). B3 é pesada em
   bancos — excluí-los perde um terço do mercado, mas calcular a métrica mesmo assim
   produz número sem significado, errado por construção. Setor sem fator aplicável fica
   ausente daquela família no score, não zerado nem excluído do universo.
2. **Earnings yield em vez de P/L bruto** para o fator de valor baseado em lucro — P/L de
   deficitária é negativo e aparece como "mais barata" num ranking ingênuo, sinal
   invertido, erro clássico de fator de valor.
3. **Regra de dado faltante declarada por fator**, idêntica em backtest e produção —
   excluir (risco de viés de seleção) ou imputar mediana do setor (risco de número
   falso), mas nunca implícita ou divergente entre os dois ambientes.

Mais uma trava operacional: percentil setorial exige população mínima (setor com 3
empresas não tem percentil com significado) — abaixo do mínimo, agrega a classificação
mais ampla ou o fator não pontua ali.

## Pendente, não resolvido nesta rodada

- Fonte de proventos com cobertura equivalente ao COTAHIST — segue em aberto, agora com a
  regra de consistência escrita para que o gap não vire erro silencioso enquanto isso não
  for resolvido.
- Nenhum código de ingestão, universo ou fator foi escrito — desenho de spec.

## Decisão

- Aprovado por: Brian — "Comece, sim — pela Seção 6, que condiciona a 7" (2026-08-19),
  com a correção do achado de proventos deslistados vinda antes de qualquer código de
  Seção 6/7, e o checklist completo de itens que cada seção precisa fechar, verbatim.
- Justificativa: consistência acima de completude é a regra que resolve o gap de
  proventos sem esperar a fonte existir; earnings yield e a matriz de aplicabilidade por
  setor são correções de erro clássico de fator de valor, não escolha estética.
