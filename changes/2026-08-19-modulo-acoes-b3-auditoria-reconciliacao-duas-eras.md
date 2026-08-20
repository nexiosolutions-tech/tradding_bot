# 2026-08-19 — Módulo de Ações: auditoria da reconciliação por nome, histórico avaliável começa em 2018

## Contexto

Usuário não aceitou fechar a fundação de identidade só com a medição de cobertura da
rodada anterior. Argumento: cobertura 0% até 2017 mudou reconciliação por nome de
fallback para único mecanismo de identidade em metade do histórico, e isso propaga em
cascata — identidade errada → setor errado (o demeaning da Seção 7 vira ruído) →
survivorship de volta pela porta dos fundos (quem não casa some do sample) → folds de
2010-2016 são de qualidade diferente dos de 2018+. Pediu uma auditoria concreta antes de
decidir: pegar um ano antigo, rodar a reconciliação, e auditar manualmente uma amostra —
os 27% que faltam são cauda ilíquida (recuperável) ou nomes líquidos (era comprometida)?

## Auditoria rodada: universo elegível de 2016-12-29 (129 tickers)

Reconciliação por nome (mesmo método da Seção 5/7: normalizar razão social, casar por
interseção de tokens contra `cad_cia_aberta.csv`) deu 94 casados (72,9%), 35 não casados
(27,1%) — a mesma ordem de grandeza do 73% já registrado antes. A auditoria foi além da
taxa bruta, exatamente como pedido.

### Pergunta 1: os 27% não casados são cauda ilíquida?

Não. `ITUB4` (Itaú Unibanco) é o **2º ticker mais líquido de todo o universo** de 2016
(R$450 milhões/dia de mediana) e ficou sem match. `BBAS3` (Banco do Brasil, 3º mais
líquido, R$225 milhões/dia) e `BVMF3` (a própria bolsa, R$175 milhões/dia) também.
Mediana de liquidez dos não casados (R$13,1 milhões/dia) ficou próxima da mediana dos
casados (R$15,2 milhões/dia) — nenhuma separação por porte.

Causa identificada, não misteriosa: o normalizador usado descarta "BRASIL" como sufixo
genérico de razão social (correto na maioria dos casos) — mas `BBAS3` tem
`NOMRES="BRASIL"`, a própria abreviação do ticker, e perder essa palavra mata o único
token útil. `ITUB4` tem `NOMRES="ITAUUNIBANCO"` (sem espaço, campo de 12 caracteres da
COTAHIST) contra os tokens separados "ITAÚ"/"UNIBANCO" do cadastro CVM — nunca bate por
token inteiro. Um heurístico mais cuidadoso resolveria esses casos específicos — mas isso
reforça o ponto do usuário: a heurística simples não é segura para produção sem revisão
manual.

### Pergunta 2: dos 73% casados, quantos estão certos?

Auditados manualmente os 19 matches de confiança baixa (score 0,5 — um único token
genérico bateu, não o nome inteiro): **10 de 19 (53%) apontam para a empresa errada.**
Seis colisões diferentes na mesma palavra genérica "PART" (de "Participações") empurraram
`ESTC3` (Estácio, educação), `TIMP3` (TIM Participações, telecom), `RAPT4` (Randon,
autopeças), `QGEP3` (petróleo), `JHSF3` e `TPIS3` (Triunfo) todos para o CNPJ de
`CYRELA BRAZIL REALTY` (construção civil) — nenhuma relação real. `GOAU4` (Gerdau
Metalúrgica) foi atribuído ao CNPJ de `GERDAU S.A.` — holding e subsidiária, CNPJs
distintos.

Contando as 84 identificações corretas (75 de alta confiança, presumidas corretas, + 9 de
baixa confiança auditadas como certas) sobre os 129 elegíveis: **precisão real ≈ 65%, não
73%**. E o erro é **invisível** no schema atual — `fonte='reconciliacao_nome'` não
distingue match certo de errado, diferente do não-match, que ao menos é visível e contado
pela decisão de saída já registrada (Seção 5.4).

## Decisão: histórico avaliável do gate começa em 2018

Não é "melhorar a reconciliação" — é reconhecer duas eras de qualidade diferente:

- **Era confiável (2018+)**: FCA popula ticker, cobertura 78-95% crescente, identidade
  majoritariamente direta.
- **Era degradada (2010-2017)**: cobertura 0% via FCA, reconciliação por nome como único
  mecanismo, ~65% de precisão real medida, erros hoje indistinguíveis de acertos.

Registrado como Seção 5.5 nova: **nenhum fold cujo período cai inteiramente antes de 2018
conta para o critério de vitórias do gate de promoção (Seção 10, critério 1)**.
2010-2017 permanece na base como dado de contexto (lookback de médias móveis/momentum),
nunca como evidência de promoção.

## Tensão aberta, não resolvida nesta rodada

Cortar o histórico avaliável de ~16 para ~8-9 anos reduz a amostra de folds temporais
para perto (possivelmente abaixo) do piso de 8 folds que o gate já assume — reconecta com
o problema de amostra pequena já registrado na Seção 13, agora no eixo temporal também,
não só no transversal. Dimensionamento final (folds mais curtos vs. esperar mais anos de
era confiável acumularem) fica pendente para o desenho detalhado da Fase 3, quando o gate
for implementado de fato.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

- Nova Seção 5.5: auditoria completa, as duas perguntas respondidas, decisão de era.
- Seção 10, critério 1: folds antes de 2018 não contam, tensão de amostra sinalizada.
- Seção 13: bullet de amostra pequena corrigido (16 anos não são todos utilizáveis) +
  novo bullet dedicado às duas eras.

## Pendente

- Dimensionamento do gate diante da amostra reduzida de folds — não resolvido, registrado
  como tensão aberta.
- Heurística de reconciliação por nome não foi corrigida (os bugs de tokenização
  identificados — stopword "BRASIL" e concatenação sem espaço — ficam para quando a
  reconciliação for implementada de fato, não nesta rodada de spec).
- Nenhum código escrito — desenho de spec.

## Decisão

- Aprovado por: Brian — "Não feche ainda... 0% até 2016 realmente significa... reconciliação
  por nome deixou de ser fallback... a pergunta não é 'como melhorar a reconciliação'. É:
  o backtest deve usar 2010-2017 como período de avaliação válido?" — com o método de
  verificação especificado explicitamente: "pegar um ano da era degradada, fazer a
  reconciliação por nome, e auditar manualmente uma amostra dos matches... os 27% que
  faltam são líquidos ou cauda ilíquida?" (2026-08-19).
- Justificativa: a auditoria confirmou o pior cenário nos dois eixos que o usuário
  identificou — não-match concentrado em nomes líquidos (não cauda), e match com taxa de
  erro real de 53% no segmento de baixa confiança. Isso justifica tratar 2010-2017 como
  contexto, não evidência, e evita que o gate de promoção conte "vitórias" construídas
  sobre atribuição setorial ~35% adivinhada como se fossem prova estatística real.
