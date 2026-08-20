# 2026-08-20 — Módulo de Ações: 2015 e 2017 medidos, fronteira avaliável fecha em 2015–2026

## Contexto

Continuação direta da rodada anterior (propagação por CNPJ + dois pisos). Usuário pediu
para medir os dois anos ímpares restantes da amostra bienal (2015, 2017) com o mesmo par
de métricas (cobertura + precisão auditada) contra os mesmos dois pisos pré-registrados
(precisão ≥98%, cobertura ≥85%), com uma instrução explícita de disciplina: reafirmar os
pisos antes de olhar os números, e não deixar a régua ceder em nenhuma direção —
nem para dentro (se 2015 desse 90,7% "por estar perto"), nem para fora (se desse 84% e
"só um ponto" tentasse abrir exceção).

## Reafirmação do pré-registro, antes de medir

Adicionado ao arquivo de pré-registro da sessão (`pre_registro/dois_pisos.txt`), antes de
rodar qualquer número de 2015/2017: os mesmos dois pisos, sem alteração — precisão ≥98%
auditada, cobertura ≥85%, por ano, sem negociação mesmo perto da linha.

## Medição

Mesmo método da rodada anterior: propagação por CNPJ (dicionário `ticker→CNPJ` da era
confiável 2018-2025 + propagação por raiz de ticker) aplicada aos universos elegíveis de
2015 e 2017 (COTAHIST baixado nesta rodada), seguida de auditoria manual de precisão
sobre todos os resolvidos.

| Ano | Cobertura | Precisão (auditada) | ≥85% cobertura? | ≥98% precisão? | Avaliável? |
|---|---|---|---|---|---|
| 2015 | 85,5% (106/124) | 100% (0 erros/106) | Sim — caso-limite | Sim | **Sim** |
| 2017 | 90,1% (137/152) | 100% (0 erros/137) | Sim | Sim | **Sim** |

2015 caiu exatamente onde o usuário previu antes de medir — em cima da linha de 85% — e
passou sem precisar de tolerância (85,5% ≥ 85%, não um arredondamento). O cenário inverso
que testaria se a régua cederia sob pressão (cobertura abaixo de 85% com precisão
perfeita) não ocorreu — mas o critério estava pronto para reprovar mesmo assim, exatamente
como pré-registrado.

## Resultado consolidado (seis anos medidos, 2010-2017)

| Ano | Cobertura | Precisão | Avaliável? |
|---|---|---|---|
| 2010 | 69,8% | 100% | Não (cobertura) |
| 2012 | 79,9% | 100% | Não (cobertura) |
| 2014 | 83,1% | 100% | Não (cobertura, perto) |
| 2015 | 85,5% | 100% | **Sim** |
| 2016 | 90,7% | 100% | **Sim** |
| 2017 | 90,1% | 100% | **Sim** |

Precisão 100% em todos os seis anos, 712 identificações auditadas manualmente sem
nenhum erro — o problema em 2010/2012/2014 nunca foi identidade errada, sempre foi
cobertura insuficiente.

## Fronteira avaliável fecha em 2015–2026, contígua

2011 e 2013 não foram medidos (não baixados nesta rodada nem na anterior), mas dado o
padrão monotônico observado (69,8% → 79,9% → 83,1% → 85,5% → 90,1%/90,7%) é improvável
que mudem o formato — ficam fora da era avaliável por não terem sido confirmados, não por
suspeita de reprovar.

## Consequência para a tensão de amostra

A era avaliável para o gate de promoção passa de ~8-9 anos (só 2018 em diante, decisão da
rodada anterior a esta) para **~11-12 anos (2015-2026)** — três folds anuais adicionais
recuperados sem ceder o piso de precisão em nenhum momento, nem no caso-limite. Ainda não
é garantia de atingir o piso de 8 folds do gate (Seção 10, critério 1) dependendo da
duração exata de cada fold, mas a tensão registrada nas Seções 10 e 13 relaxa
substancialmente.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

- Seção 5.6: tabela consolidada dos seis anos, resultado de 2015/2017, fronteira
  2015-2026 declarada.
- Seção 10, critério 1: era avaliável atualizada para "2015 a 2026, contíguo".
- Seção 13: bullet reescrito com o resultado final e o número de identificações
  auditadas (712).

## Pendente

- 2011 e 2013 não medidos — próximo passo se a precisão exata da fronteira interessar
  (não crítico, já que ficam fora de qualquer forma dado que 2010/2012/2014 reprovaram).
- Nenhum código de produção escrito — desenho de spec.
- Dimensionamento final do gate (Seção 10) diante de ~11-12 anos de era avaliável —
  ainda pendente para a Fase 3.

## Decisão

- Aprovado por: Brian — pediu a medição de 2015 e 2017 com o mesmo par de métricas contra
  os mesmos pisos, com reafirmação explícita antes de rodar ("não olhe os números antes
  de reafirmar os pisos") e o aviso de disciplina simétrica: "segure a régua igual nos
  dois sentidos... um piso que cede sob pressão contamina toda decisão futura que se
  apoiar nele" (2026-08-20).
- Justificativa: o caso-limite de 2015 é exatamente o tipo de teste que valida se um
  critério pré-registrado funciona de verdade — decidido pela regra escrita antes de ver
  o número, não ajustado depois. Recuperar três anos de amostra sem tocar no piso de
  precisão é o resultado que só é confiável porque a régua não foi negociada em nenhuma
  direção.
