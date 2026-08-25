# 2026-08-25 — Módulo de Ações: diagnóstico bancário acha bug real, piso de cobertura fica separado de identidade

## Contexto

A rodada anterior mediu incidência e perfil da limitação de versão retificada, achando
concentração forte em bancos (mais da metade das ausências) e reportou 84,3-84,8% como
"na fronteira do piso de 85%". Usuário separou duas decisões coladas: (1) aceitar score
parcial — concordou, com justificativa própria (excluir por dado faltante enviesado
importa o viés para o universo inteiro; ranquear com fatores parciais o confina ao fator
afetado); (2) pediu diagnóstico específico do viés bancário no ROE (os excluídos diferem
dos incluídos?) e correção da leitura do piso — 84,3% é **abaixo** de 85%, não "quase
passando", e reusar/afrouxar o piso de identidade para cobertura de fator seria o mesmo
erro que a Seção 5.6 já corrigiu (piso medindo o risco errado).

## Diagnóstico: bancos excluídos têm ROE mais baixo, direção consistente nos dois anos

ROE calculado com a versão errada (nunca para uso, só como sonda) para os bancos com
versão divergente, comparado ao ROE real dos bancos incluídos:

| | Incluídos (ROE real) | Excluídos (ROE diagnóstico) |
|---|---|---|
| 2015 (mediana) | 18,0% | 14,4% |
| 2016 (mediana) | 17,6% | 14,8% |

Direção consistente nos dois anos (excluídos mais baixos), amostra pequena (2 incluídos
vs. 5 excluídos por ano — não robusta para magnitude, mas o sinal direcional se repete,
não é ruído de uma amostra só).

## Achado mais específico, embutido no diagnóstico: só 2 de 7 bancos com ROE real

Em ambos os anos, o setor "Bancos" tinha 7 membros no universo, mas só 2 com ROE real —
os outros 5 imputados pela mediana do universo inteiro (bem mais baixa que o nível
bancário típico).

## Bug real achado e corrigido, antes do backtest

`compute_demeaned_percentiles` contava população e calculava média de bucket incluindo
os valores **imputados**. Com 5 dos 7 bancos imputados, `len(grupo)=7 >= min_bucket_size
(3)` passava o piso — a "média dos bancos" saía calculada com 5 valores que eram, na
prática, a mediana do universo inteiro, não dado bancário. Isso deslocava o demeaned de
*toda* empresa no bucket "Bancos", inclusive as com ROE real (a média inflada pra baixo
por diluição fazia os bancos reais parecerem melhores do que são contra os pares reais).

**Corrigido**: população e média de bucket usam só valores reais; um bucket com poucos
membros reais sobe a hierarquia mesmo que a contagem total (real + imputada) pareça
suficiente. `backend/src/tradingbot/acoes/fatores.py`, `compute_demeaned_percentiles`.
Teste novo (`test_bucket_com_maioria_imputada_sobe_hierarquia_em_vez_de_diluir`) prova o
mecanismo com caso ilustrativo (2 bancos reais + 5 imputados + universo com mediana bem
distante) — confirma que os dois bancos reais sobem para o universo em vez de formarem
um bucket "Bancos" fantasma.

**Consequência para a Seção 7.3**: o teste de demeaning banco-contra-banco daquela
seção usava dado real de 2016-07-15 (onde a versão do BB já estava disponível — data
diferente da medição de 115 empresas, sem conflito real). A ressalva correta não é "a
Seção 7.3 está errada" — é que a comparação banco-contra-banco só tem massa real
suficiente quando o setor não está sob a limitação de versão retificada, que reduz
justamente a massa no setor onde ROE mais importa.

## Correção da leitura do piso: 84,3-84,8% está abaixo de 85%, não na fronteira passando

84,3% (2016) e 84,8% (2015) são **abaixo** de 85%, ponto. A rodada anterior descreveu
como "na fronteira do piso, não folgado, mas muito mais perto" — impreciso; deveria ter
dito "abaixo". Reusar (ou afrouxar) o piso de 85% de identidade para cobertura de fator
seria o mesmo erro que a Seção 5.6 já corrigiu: **o piso de identidade foi desenhado para
um risco diferente** (erro que corrompe em silêncio, empresa errada inteira no ranking).
Cobertura de fator tem natureza diferente (ausência visível, contável, mitigada pela
renormalização) — precisa de piso próprio, justificado por natureza de risco própria, não
o número emprestado nem um número calibrado para caber.

## A saída: generalizar N=100, não inventar um piso de porcentagem novo

Em vez de desenhar um piso percentual novo para cobertura de fator (risco real: acabar
calibrado para caber, não para o risco), a recomendação registrada é generalizar o
critério de amostra transversal **que a Seção 10 já usa** (N≥100 do universo elegível,
critério 2) para o **universo com score composto computável** — mesma preocupação
(amostra transversal pequena demais para poder estatístico), denominador diferente
(quantas empresas de fato entram na contagem, depois da atrição por fator).

Aplicando aos dois anos medidos: **2015 tem 106 empresas com score computável — passa.
2016 tem 97 — abaixo de 100, reprovaria pelo critério 2 já existente**, se aplicado a
este denominador. Isso corrige também uma afirmação da Seção 10 ("por construção este
critério nunca reprova nada no histórico medido até aqui") — passa a reprovar, uma vez
que o denominador certo (score computável, não universo bruto) é usado.

## Requisito novo para o backtest: setor financeiro com linha própria no relatório

Se o conjunto de fatores parecer funcionar mas a vantagem estiver concentrada no
financeiro — o setor mais afetado pela limitação e o único com massa real de ROE
reduzida — não há como distinguir sinal genuíno de artefato. Mesmo espírito do critério 5
já existente (não concentrar vantagem num setor/período); aqui vira exigência de
relatório, não só de gate.

## Testes novos

`backend/tests/test_acoes_fatores.py`: 1 teste novo
(`test_bucket_com_maioria_imputada_sobe_hierarquia_em_vez_de_diluir`), provando o
mecanismo do bug e da correção com caso ilustrativo declarado. 422 testes passam na
suíte completa (excluindo o teste live de rede, não relacionado a este módulo), zero
regressão nos testes já existentes — a correção não mudou nenhum resultado anterior
porque nenhum teste anterior tinha um bucket com maioria de membros imputados.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Seção 7 (normalização): parágrafo do piso de bucket atualizado para "população e média
contam só dado real". Seção 7.5: diagnóstico bancário, o bug e a correção, a leitura
corrigida do piso (abaixo de 85%, não na fronteira), a recomendação de generalizar N=100,
e o requisito de relatório segmentado. Seção 10, critérios 2 e 5: nota de atualização
cruzada — N=100 aplicado ao denominador certo reprova 2016, e o critério 5 ganha a
exigência de linha própria para o setor financeiro.

## Pendente

- Confirmar se o `n` de score computável (contagem absoluta, não fração) se sustenta
  acima de 100 em anos mais recentes da era avaliável (2024-2026).
- Decisão final da Seção 10 sobre aplicar N≥100 ao universo com score computável — aqui
  fica como recomendação registrada e justificada, não decisão tomada.
- Série completa 2015-2026 com ingestão otimizada (savepoint-por-linha ainda pendente de
  revisão de performance).

## Decisão

- Aprovado por: Brian — separou "aceitar score parcial" (concordou, com justificativa
  própria) de "o viés bancário está resolvido" (não está, precisa de diagnóstico
  específico); pediu o diagnóstico com o ROE de versão errada como sonda; corrigiu a
  leitura do piso (84,3% é abaixo de 85%, não fronteira) e pediu piso de cobertura de
  fator como decisão de desenho separada, com número próprio justificado, não reusando
  nem afrouxando o de identidade (2026-08-25).
- Justificativa: o diagnóstico pedido não só confirmou a direção do viés (bancos
  excluídos com ROE mais baixo) como expôs um bug de código real (bucket contando
  imputados na população/média) que a medição por incidência sozinha nunca teria achado
  — mesma lição de sempre: medir com uma pergunta específica encontra problemas que medir
  em agregado escconde. A generalização do N=100 em vez de um piso percentual novo evita
  o risco que o próprio usuário nomeou (calibrar para caber) ao reusar um critério já
  pré-registrado com outro propósito, aplicado ao denominador certo.
