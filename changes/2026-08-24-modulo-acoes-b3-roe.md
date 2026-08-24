# 2026-08-24 — Módulo de Ações: ROE, primeiro fator ponta a ponta a cruzar duas demonstrações

## Contexto

Terceiro fator da família Qualidade, escolhido pelo usuário porque é o primeiro a cruzar
DRE e BP num único quociente (lucro/patrimônio), trazendo uma armadilha que os dois
fatores anteriores não tiveram. Pediu, na ordem: localizar lucro líquido dos
controladores e patrimônio líquido por `DS_CONTA` (não código), verificado contra
industrial e banco, **antes** de calcular qualquer coisa — aplicando preventivamente a
lição do `CD_CONTA "3.05"` (Seção 7.2) em vez de descobrir o mesmo problema de novo
durante a implementação.

## Verificação (feita antes de qualquer código, como pedido)

Confirmado contra a DRE/BP reais de Itaú, Banco do Brasil e Petrobras (2015):

- `DS_CONTA "Atribuído a Sócios da Empresa Controladora"` — idêntico nas duas variantes
  de plano de contas, mas `CD_CONTA` muda por empresa (`"3.09.01"` banco, `"3.11.01"`
  Petrobras) — confirma que a lição do "3.05" se aplica de novo, exatamente como o
  usuário previu.
- `DS_CONTA "Patrimônio Líquido Consolidado"` — mesmo padrão (`"2.08"` banco, `"2.03"`
  Petrobras).
- **Achado adicional**: patrimônio líquido consolidado inclui participação de
  minoritários (`DS_CONTA "Participação dos Acionistas Não Controladores"`, linha
  separada e real nas três empresas) — subtraída para consistência com o numerador
  (lucro dos controladores), senão o denominador ficaria maior que o correspondente ao
  numerador, subestimando o ROE.

## O que foi implementado

`backend/src/tradingbot/acoes/fatores.py`:

- `get_lucro_liquido_controladores_as_of` / `get_patrimonio_liquido_controladores_as_of`
  — busca por `DS_CONTA` dentro do prefixo da demonstração certa (`"3."` DRE, `"2."`
  BPP), nunca por código.
- `roe_raw(lucro, patrimonio)` — `None` (indefinido) quando `patrimônio ≤ 0`. Testado
  explicitamente que a categoria "indefinido" (introduzida para `EBITDA ≤ 0`, Seção 7.2)
  generaliza para este segundo gatilho independente, sem acoplamento de código entre as
  duas funções.
- `pearson_correlation` — implementação direta, sem nova dependência, usada para medir
  ortogonalidade entre fatores.

## A armadilha do ROE, confirmada com dado real

Petrobras teve prejuízo real em 2015 (ROE real -13,68%), mas o patrimônio líquido dos
controladores continuou positivo (R$254.731 milhões) — **não** é o caso indefinido, é
prejuízo genuíno corretamente refletido. Testado separadamente, com números ilustrativos,
o caso perverso que o usuário descreveu: prejuízo dividido por patrimônio negativo
devolveria ROE positivo (empresa quebrando parecendo excelente) se não fosse bloqueado —
`roe_raw` devolve `None` nos dois sinais de lucro quando o patrimônio é negativo.

## Demeaning setorial, não matriz

ROE se aplica a banco (diferente de dívida líquida/EBITDA) — banco tem lucro e
patrimônio, ROE de banco é métrica central. Mas ROE real dos bancos (Itaú +22,93%, BB
+17,04%) é estruturalmente mais alto que o da industrial (Petrobras -13,68%) —
comparação em nível absoluto seria injusta. Dois testes:

- **Dado real**: os dois bancos (`ITUB4`/`BBAS3`, mesmo segmento `Bancos`) demeaned
  contra a própria média de par (`min_bucket_size=2`, reduzido deliberadamente — a
  fixture desta rodada só tem 3 empresas ao todo, o piso de produção nunca formaria
  bucket de segmento com só 2 bancos).
- **Mecanismo isolado** (dado ilustrativo, não real — declarado explicitamente):
  bucket "bancos" (~20% ROE) e bucket "industriais" (~5% ROE), bem separados em nível
  absoluto. Depois do demeaning, o banco e a industrial "típicos" do próprio setor ficam
  com percentil parecido (perto de 50), não um sistematicamente acima do outro só pela
  estrutura de capital.

## Ortogonalidade medida, com a ressalva estatística correta

Correlação de Pearson entre earnings yield e ROE sobre as três empresas desta fixture:
**≈0,92** — alta. Mas `n=3` não é amostra suficiente para aplicar o limiar de 0,7
pré-especificado pelo usuário com qualquer confiança estatística: três pontos quase
sempre produzem correlação alta por acaso. O número foi calculado e registrado
honestamente (não escondido por ser inconveniente ou por não decidir nada ainda), mas a
decisão real sobre ortogonalidade fica explicitamente pendente até a correlação ser
medida sobre o universo de 2016 inteiro (115 empresas, já materializado na Seção 6.1) —
não fabricada aqui só para fechar a pergunta com uma amostra que não sustenta a resposta.

## Testes novos

`backend/tests/test_acoes_fatores_roe.py`, 9 testes: lucro/patrimônio dos controladores
reais (busca por `DS_CONTA`); ROE negativo real da Petrobras, distinto do caso
indefinido; ROE real dos bancos mais alto que industrial; patrimônio ≤ 0 → indefinido
(dois sinais de lucro); categoria indefinido generaliza (dois gatilhos independentes,
sem acoplamento); demeaning de bancos reais contra a própria média de par; mecanismo de
demeaning banco/industrial (ilustrativo, declarado); correlação real com ressalva
estatística. Fixtures novas, reais:
`dre_con_2015_itub_bbas_petr_lucro_controladores_real_extract.csv`,
`bpp_con_2015_itub_bbas_petr_patrimonio_real_extract.csv`. 422 testes passam na suíte
completa (413 + 9 novos), zero regressão.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Nova Seção 7.3: a verificação preventiva do padrão "3.05", o achado da participação de
minoritários no patrimônio, a armadilha do patrimônio negativo, o ROE real das três
empresas, os dois testes de demeaning (real + mecanismo ilustrativo) e a correlação
medida com a ressalva de `n=3`. Seção 12 (Fase 3) atualizada.

## Pendente

- Correlação ROE × earnings yield sobre o universo real de 115 empresas de 2016 — a
  medição que de fato decide se ROE é ortogonal ou redundante.
- Demais famílias de fator (Crescimento, Momentum, Tamanho).
- Seção 8 (motor de carteira) ainda sem código.

## Decisão

- Aprovado por: Brian — pediu a verificação de `DS_CONTA` para lucro/patrimônio
  aplicada preventivamente (não esperar descobrir a armadilha de novo), a generalização
  da categoria "indefinido" para o gatilho de patrimônio negativo, o teste de demeaning
  provando banco/industrial comparáveis, e a medição honesta de correlação como "o
  número que diz se o fator vale a pena" (2026-08-24).
- Justificativa: a verificação preventiva confirmou que a lição do "3.05" generaliza
  (mesmo padrão, duas contas diferentes) — validando que a disciplina aprendida em uma
  rodada se transporta corretamente para a próxima sem precisar ser redescoberta. A
  correlação de 0,92 sobre `n=3`, registrada com a ressalva em vez de usada para decidir
  qualquer coisa, é o mesmo tipo de honestidade estatística que já apareceu antes nesta
  spec (o 22/27 direcional da Seção 8, não calibrado até ser remedido em escala real).
