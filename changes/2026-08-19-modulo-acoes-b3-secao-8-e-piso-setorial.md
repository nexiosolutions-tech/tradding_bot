# 2026-08-19 — Módulo de Ações: piso setorial medido, segundo canal de survivorship, N=100 reformulado

## Contexto

Usuário revisou a medição do universo elegível (`changes/2026-08-19-modulo-acoes-b3-medicao-universo.md`)
e apontou que a hipótese corrigida ("universo é cíclico, não cresce monotonicamente")
ainda não respondia a pergunta que realmente decide viabilidade: o número que morde não é
o total (113 no vale de 2016), é a distribuição por setor — 113 empresas espalhadas por
~10 setores pode significar vários setores abaixo da população mínima que a Seção 7 acabou
de definir. Três leituras, nesta ordem: medir o piso setorial, corrigir um segundo canal
de survivorship (perda de liquidez, não só deslistagem), e reformular o que o critério
N=100 do gate realmente testa.

## Medição 1: piso setorial no vale de 2016, contra dado real

Sem `cnpj_ticker_map` (pendência de Fase 2 já registrada), não há join direto entre
ticker e setor. Usado o mesmo princípio de "baixar e olhar" da CVM/COTAHIST: baixado
`cad_cia_aberta.csv` (Cadastro de Companhias Abertas, CVM Dados Abertos —
`https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv`), que tem o
campo `SETOR_ATIV` por CNPJ. Casamento com as 113 empresas do vale de 2016
(`2016-02-29`, ver medição anterior) feito por nome (`NOMRES` da COTAHIST vs.
`DENOM_SOCIAL`/`DENOM_COMERC` da CVM, normalizado e por interseção de tokens) — 83 de 113
casadas (73%), 30 não casadas por variação de nome que a heurística simples não cobriu.

**Resultado, taxonomia CVM (mais granular que a B3, ~40 categorias incluindo
"Emp. Adm. Part. - X" como categoria própria para holdings):** 31 de 35 setores com pelo
menos 1 empresa ficaram abaixo do mínimo de 6 (Seção 7). Só Bancos (6), Metalurgia e
Siderurgia (7), Energia Elétrica (8) e Construção Civil (12) passaram.

**Sensibilidade — colapsando holdings ("Emp. Adm. Part. - X") no setor-base X**, aproximação
mais próxima da classificação B3 (mais grosseira, referida pela Seção 7 como fonte de
produção): **22 de 27 setores continuaram abaixo do mínimo**. Só Bancos, Metalurgia,
Energia Elétrica, Construção Civil e Comércio (Atacado e Varejo) sobreviveram mesmo na
leitura mais conservadora.

O total de 113 escondia essa fragmentação por completo — confirma diretamente a leitura
do usuário.

## Ressalvas desta medição, declaradas

- `SETOR_ATIV` da CVM é uma taxonomia diferente (mais granular) da classificação B3 que a
  Seção 7 assume como fonte de produção — usado como proxy por ser a única fonte de setor
  já verificada nesta sessão; a leitura "colapsada" acima é a tentativa de aproximar a
  granularidade real, não uma medição direta contra o dado que vai para produção.
- Casamento por nome (73%) é heurística, não join por identificador — mesmo problema que
  o `cnpj_ticker_map` (Seção 5.1) existe para resolver definitivamente.
- Um único vale (2016-02-29) examinado, não toda a série temporal.
- Nenhum código de produção escrito — script de medição ficou no scratchpad da sessão.

Apesar das ressalvas, a direção e a magnitude do achado (a maioria dos setores fica abaixo
do piso num vale de liquidez) são fortes o suficiente para virar decisão de desenho agora,
não esperar a fonte de setor definitiva.

## Achado 2: filtro de liquidez é um segundo canal de survivorship, não coberto pela tabela de deslistagem

O mais importante dos três, segundo o usuário: o universo encolhe **na crise**, porque o
volume seca — não porque a empresa deslistou. A tabela de survivorship (COTAHIST, Seção
5.3) cobre deslistagem; não cobre um ativo em carteira que cai abaixo do limiar de
liquidez sem sair da bolsa. Se o backtest simplesmente parasse de considerar essa posição
no mês em que ela cruza o limiar, a posição desapareceria do sample exatamente no momento
em que daria o pior resultado — viés otimista, silencioso, não corrigido por nada que já
estava na spec.

**Regra registrada na Seção 8** (motor consciente da carteira, como primeiro item —
pedido explícito do usuário): quando um ativo em carteira sai do universo elegível, o
motor modela a saída. No backtest, liquidação simulada com slippage compatível com a
iliquidez que causou a exclusão (não o slippage "normal" da Seção 9). Em produção, alerta
de perda de elegibilidade ao lado das sugestões de aporte — informação nova no menu Ações,
não uma ordem automática (módulo não executa). Regra declarada e idêntica nos dois
ambientes, mesmo princípio da regra de dado faltante da Seção 7.

## Achado 3: N=100 do gate não faz o trabalho que parecia fazer

Como o mínimo histórico observado (~113) já fica acima de N=100 em todos os 9 anos
medidos, o critério 2 do gate (Seção 10) nunca reprova nada por construção — não é um
filtro calibrado contra o histórico atual, é uma guarda contra degradação futura.
Reformulado na Seção 10 para deixar isso explícito, e para apontar que **o critério que
de fato tem poder de reprovação é o 5** (piso de amostra mínima por segmento) — a mesma
medição que achou o piso setorial.

Consequência adicional registrada: a largura do corte transversal variou de ~113 a ~235
ao longo do histórico — um fold cujo período caiu num vale de liquidez tem menos poder
estatístico que um fold num pico, mas o critério 1 do gate conta os dois igualmente hoje.
Registrado como lacuna conhecida na Seção 10 e 13, não resolvida nesta rodada (ponderar
por N transversal do fold é candidato para quando o gate for implementado de fato).

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

- Seção 7: achado do piso setorial, com a consequência de que o fallback de agregação é o
  caminho comum em estresse, não caso raro.
- Seção 8: regra de saída por perda de liquidez, como primeiro item da seção (antes de
  entradas/saídas do motor de carteira) — inclui novo item na lista de saídas ("alerta de
  perda de liquidez").
- Seção 10: critério 2 reformulado (guarda, não filtro calibrado), nota de que o critério
  5 é quem morde de fato, nova observação sobre poder estatístico desigual entre folds.
- Seção 13: survivorship desdobrado em dois canais, achado do piso setorial, achado da
  desigualdade de poder estatístico entre folds.

## Pendente, não resolvido nesta rodada

- Fonte de classificação setorial B3 real (não o proxy CVM `SETOR_ATIV` usado aqui).
- `cnpj_ticker_map` (Seção 5.1) — resolveria o join por identificador em vez de nome.
- Medição do piso setorial em outros vales/picos do histórico, não só 2016.
- Nenhum código de ingestão, universo, fator ou motor de carteira foi escrito — desenho de
  spec.

## Decisão

- Aprovado por: Brian — três leituras em sequência antes de liberar a Seção 8: "O número
  que decide não é o total, é o setorial" (com o pedido explícito de rodar a medição
  desagregada por setor no vale de 2016), "o filtro de liquidez é um segundo canal de
  survivorship... é o achado mais importante escondido no seu resultado", e "o N=100 hoje
  não faz trabalho... documente como guarda contra degradação futura" (2026-08-19).
- Justificativa: medir o piso real antes de escrever o motor de carteira evita descobrir
  em produção que o fallback de agregação setorial dispara o tempo todo em crise, e que
  posições perdidas por iliquidez estavam inflando os resultados do backtest sem que
  nenhuma regra existente cobrisse esse caso.
