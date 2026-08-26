# 2026-08-26 — Módulo de Ações: `build_decisao` implementado e travado contra 2015 e 2016 reais

## Contexto

Rodada anterior parou deliberadamente antes de tentar montar os 10 anos restantes da
série sem um driver reutilizável — reconstruir a orquestração de memória, ano a ano,
era o próprio risco que a disciplina desta spec existe para evitar. Usuário aprovou
parar e pediu, nesta ordem: (1) verificar se o lookback de fundamento de dois anos (achado
FY2013 da rodada anterior) está de fato ingerido antes de assumir que basta um ano; (2)
implementar o driver como infraestrutura de produção (contrato claro, determinística, sem
estado escondido, nunca reimplementando `compute_score_composto`); (3) travar contra
**dois** anos conhecidos (2015: 106: 2016: 97), não um — um único ponto de referência
pode bater por coincidência ou por ajuste até bater, dois pontos independentes não.

## `build_decisao` implementado

`backend/src/tradingbot/acoes/decisao.py`: uma função, `build_decisao(session,
data_decisao, setor_by_cnpj, *, pesos=PESOS_PADRAO, **kwargs_universo)`. Materializa o
universo elegível (`build_universo_elegivel`, Seção 6), computa os três fatores por
empresa respeitando a matriz de aplicabilidade (dívida líquida/EBITDA nunca entra na
lista de bancos como `None` a ser imputado — inaplicável nunca é confundido com faltante),
roda `compute_demeaned_percentiles` uma vez por fator sobre o universo que participa
dele, e chama `compute_score_composto` — nunca reimplementado — para o score final.
`DecisaoResultado.n_score_computavel` conta empresa com **pelo menos um fator de dado
real** (não imputado), a métrica que decide se um ranking é confiável, distinta de
"`compute_score_composto` devolveu um número" (que é quase sempre verdade, porque a
imputação por mediana preenche todo fator faltante antes do percentil).

Spec 14, nova Seção 7.6.

## Testes automatizados: fiação correta, dado 100% real (reusa fixtures já comitadas)

`backend/tests/test_acoes_decisao.py`, 3 testes, reusando integralmente as fixtures reais
já comitadas para 2016-07-15 (ITUB4/BBAS3/PETR4 — universo, earnings yield, ROE, dívida
líquida/EBITDA, cada uma de uma rodada anterior): (1) as três empresas saem com score
composto; (2) dívida líquida/EBITDA inaplicável para os dois bancos nunca aparece como
`None` por dado faltante, PETR4 (aplicável) recebe percentil real, os dois bancos ainda
têm score via renormalização; (3) monkeypatch em `compute_score_composto` prova que o
driver de fato delega — se a função for substituída, o resultado muda de acordo, só
possível se não houver reimplementação escondida.

## Verificação contra dado real, escala completa — não só a fixture pequena

Além dos testes automatizados, o driver foi rodado contra o universo real inteiro dos
dois anos já auditados (125 empresas 2015-02-27, 115 empresas 2016-02-29) — mesmo dado
das Seções 7.4/7.5. Não comitado como fixture (escala de centenas de MB de CVM/COTAHIST
reais), mas reproduzível: master index CVM 2011-2015, itens financeiros (DRE/BPP/BPA/
DFC_MI, consolidado) para os exercícios fiscais 2013/2014/2015, os 129 CNPJs únicos dos
dois universos.

**Resultado**: universo bate **exatamente** nos dois anos (125/125, 115/115). Score
computável bate exatamente em 2015 (106/106). Em 2016 saiu 98, não 97 — causa única,
identificada: `GOLL4` tem dado real de dívida líquida/EBITDA (terceiro fator), mas não de
earnings yield/ROE, e "97" (Seção 7.5) foi definido explicitamente sobre **dois** fatores
(earnings yield/ROE, os afetados pela limitação de versão retificada medida naquela
rodada) — nunca incluiu dívida líquida/EBITDA na contagem. `build_decisao` usa a
definição de produção correta (três fatores), então 98 é o número certo para esse
critério mais completo; 97 continua certo para o critério mais estreito que a Seção 7.5
mediu. Não é divergência a corrigir — é a mesma disciplina de sempre (categorias de
ausência nunca confundidas) aplicada a uma métrica que ficou mais completa depois da
medição original.

## Bug pego pela própria verificação — exatamente o que o teste contra dois anos existe para fazer

A primeira tentativa usou vigência de identidade simplificada ("para sempre" em vez da
vigência real derivada da COTAHIST) e produziu 116 empresas / 99 com score computável em
2016 — um erro de 2 sobre o esperado, não 1. Diagnosticado: `GETI4` tinha vigência real
encerrada em 2015-12-30 (`compute_vigencia` sobre a COTAHIST real confirma), antes da
decisão de 2016-02-29, mas apareceu no universo por causa da vigência simplificada do
próprio script de verificação — não um bug em `build_decisao`, um bug na preparação dos
dados de verificação. Corrigido recalculando vigência real; resultado final (125/106,
115/98) já reflete a correção. Sem o número de referência conhecido, 116/99 teria passado
sem ninguém notar — a mesma lição de sempre, provada de novo nesta própria verificação.

## Lookback de fundamento de dois anos: confirmado ingerido, não assumido

Master index CVM 2011-2015 e itens financeiros FY2013/2014/2015 (DRE/BPP/BPA/DFC_MI)
ingeridos antes de rodar a verificação — o achado da rodada anterior (68/125 resolvendo
para FY2013 na decisão de 2015) exigia isso, e a verificação contra 2015 só bateu
(106/106) porque o fundamento de FY2013 estava de fato disponível no banco, não só
teoricamente resolvível.

## Testes + suíte

`test_acoes_decisao.py`: 3 testes novos, todos passando. Suíte completa
(`--ignore=tests/test_binance_ws_live.py`): 428 passed.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Nova Seção 7.6: contrato do driver, por que nunca reimplementa `compute_score_composto`,
o teste de aceite de dois anos (não um), a distinção 2-fatores/3-fatores que a
verificação revelou, e o achado colateral (GETI4/vigência) como exemplo do próprio
mecanismo de proteção funcionando.

## Pendente

- Os 10 anos restantes da série (2017-2026) — agora execução sobre o driver já travado,
  não montagem nova. Cada ano precisa da mesma preparação (master index + itens
  financeiros para os exercícios fiscais que aquele ano resolve, identidade com vigência
  real).
- As duas medições finais que alimentam a Seção 10 antes do backtest (quantos anos o
  N≥100 reprova; distribuição de cobertura ao longo do ciclo) — dependem da série
  completa.
- Decidir se `n_score_computavel` (3 fatores) substitui formalmente o "n efetivo" de 2
  fatores da Seção 7.5 como a métrica de referência daqui para frente, agora que o driver
  existe — inclinação registrada: sim, é a métrica que corresponde ao score real usado,
  mas não decidido nesta rodada.

## Decisão

- Aprovado por: Brian — aprovou parar a rodada anterior antes de montar os 10 anos sem
  driver; pediu o driver como infraestrutura de produção (contrato, determinismo, nunca
  reimplementar a composição); pediu travar contra os dois anos conhecidos, não um, com a
  justificativa explícita de que um ponto só pode bater por coincidência ou ajuste;
  pediu confirmar o lookback de dois anos de fundamento antes de assumir que um ano basta
  (2026-08-26).
- Justificativa: o teste contra dois anos independentes fez exatamente o que foi
  desenhado para fazer — pegou um bug real (vigência simplificada deixando `GETI4`
  vazar para 2016) que um teste de fiação pequena, ou um teste contra um ano só, não
  pegaria. E a distinção 2-fatores/3-fatores só apareceu porque a verificação usou o
  universo real inteiro, não a fixture de 3 empresas — nenhuma das três (ITUB4/BBAS3/
  PETR4) tem o padrão "só dívida líquida/EBITDA real" que `GOLL4` tem.
