# 2026-08-26 — Módulo de Ações: piso de liquidez deflacionado por IPCA, correção de identidade, sequenciamento 9 antes de 8

## Contexto

Revisão da rodada anterior (série completa 2015-2026) levantou quatro pontos antes do
backtest: (1) o piso de liquidez é nominal, provavelmente afrouxando sozinho ao longo de
uma série que atravessa mais de uma década; (2) a divergência do pico (194 em 2022 medido
vs ~235 citado antes) já tinha uma explicação registrada ("provavelmente identidade"),
mas não verificada — usuário pediu fechamento, não mais uma divergência aberta; (3) N=100
reprovando só 1/12 é evidência fraca de calibração, não forte, distinção que precisa
ficar registrada; (4) proposta de inverter a ordem — formação mínima de carteira +
backtest antes do motor de carteira completo (Seção 8), mesma lógica que já levou a
provar um fator ponta a ponta antes de escrever os outros dois.

## 1. Piso de liquidez era nominal — confirmado e corrigido

`MIN_VOLUME_MEDIANO_PADRAO = R$ 500.000` comparado sem ajuste contra qualquer data entre
2015 e 2026 — confirmado no código antes de qualquer suposição. Fonte real verificada:
Banco Central — SGS, série 433 (IPCA, variação mensal), já a fonte declarada para
Selic/CDI/câmbio (Seção 4.3) — cobre IPCA também, sem integração nova com o IBGE.
Inflação acumulada real, fev/2015 a fev/2026: **fator 1,80×** — R$500 mil de 2026 vale,
em poder de compra, o equivalente a ~R$278 mil de 2015.

`backend/src/tradingbot/acoes/ipca.py` (novo): `build_indice_acumulado` (encadeia
variação mensal num número-índice), `ingest_ipca_series` (persistência append-only),
`get_ipca_as_of` (mesma convenção point-in-time do resto da spec), `deflacionar_piso`
(reexpressa um piso ancorado numa data-base para o poder de compra de outra data —
degrada para o piso nominal sem ajuste se o IPCA não estiver ingerido, nunca bloqueia o
cálculo do universo por falta de um dado macro auxiliar). `IpcaIndice` (novo modelo).
`universo_elegivel.py`: piso deflacionado automaticamente a partir de `DATA_BASE_
LIQUIDEZ = 2015-02-27` (mesma âncora que fecha a fronteira de identidade, Seção 5.6).

6 testes novos (`test_acoes_ipca.py`), com variação mensal **real** do IPCA (BCB SGS 433,
jan/2015-fev/2016, consultada em 2026-08-26) — inclusive o caso de degradação (sem IPCA
ingerido, piso nominal sem ajuste, mesmo comportamento de todo teste já existente que não
precisou mudar).

## 2. Série reexecutada com o piso corrigido — efeito isolado do resto

Reexecução é barata: nenhum dado novo de CVM/COTAHIST, só `build_universo_elegivel`
reprocessado sobre o que já estava ingerido. Isolado o efeito puro do IPCA (mesma
identidade, antes/depois):

| Ano | Sem IPCA | Com IPCA | Efeito |
|---|---|---|---|
| 2015 | 128 | 128 | 0 (data-base) |
| 2016 | 117 | 116 | -1 |
| 2020 | 169 | 164 | -5 |
| 2022 | 194 | 190 | -4 |
| 2024 | 206 | 196 | -10 |
| 2026 | 178 | 168 | -10 |

Efeito cresce com o tempo decorrido da âncora, exatamente como esperado de um piso que
vinha afrouxando sozinho. **Contração 2023-2026 mais forte depois da correção**: 210→178
(-15,2%) sem IPCA, **200→168 (-16,0%) com IPCA** — confirma a hipótese registrada.

## 3. Achado colateral: 2015/2016 estavam com identidade inconsistente com o resto da série

Ao reprocessar, 2015 subiu de 125→128 e 2016 de 115→117 (independente do IPCA) — a
Seção 7.6 travou o driver contra 2015/2016 usando identidade construída *antes* do
pipeline de produção completo (`load_fca_identity` + `compute_vigencia` sobre a COTAHIST
inteira, 754 tickers) ter sido montado para a Seção 7.7; 2017-2026 já usavam a versão
completa. Pequeno (2-3 empresas), mas real — corrigido reprocessando os dois anos com a
mesma identidade de todo o resto.

## 4. Divergência do pico reconciliada — a explicação registrada antes estava errada

A Seção 7.7 tinha registrado "provavelmente identidade não resolvida" como explicação
mais provável para 194 (2022, medido) vs ~235 (citado antes) — não confirmada. Investigado
agora: **não era identidade**. A medição antiga (`changes/2026-08-19-modulo-acoes-b3-
medicao-universo.md`) exigia só 20 pregões na janela para o ticker contar;
`build_universo_elegivel` exige `MIN_PREGOES_HISTORICO_PADRAO = 252` (ano cheio) — piso de
histórico muito mais rigoroso, não comparável ao da medição antiga. A diferença bate quase
exatamente com a contagem de `historico_insuficiente` do próprio ano 2022 (41 empresas
excluídas por esse motivo, contra a diferença de pico de 235-194=41 na comparação
original) — correspondência forte o bastante para substituir a explicação errada por
esta. **A curva de sanidade usada para validar a série anterior foi calibrada contra a
medição antiga desatualizada** — registrado para não repetir o erro numa reexecução
futura.

## Tabela final — identidade consistente + IPCA, a que vale a partir de agora

| Ano | Universo | Score computável | Cobertura | N≥100 |
|---|---|---|---|---|
| 2015 | 128 | 104 | 81,2% | passa |
| 2016 | 116 | 97 | 83,6% | **falha** |
| 2017 | 127 | 104 | 81,9% | passa |
| 2018 | 132 | 112 | 84,8% | passa |
| 2019 | 144 | 120 | 83,3% | passa |
| 2020 | 164 | 143 | 87,2% | passa |
| 2021 | 174 | 152 | 87,4% | passa |
| 2022 | 190 | 172 | 90,5% | passa |
| 2023 | 200 | 178 | 89,0% | passa |
| 2024 | 196 | 186 | 94,9% | passa |
| 2025 | 181 | 168 | 92,8% | passa |
| 2026 | 168 | 156 | 92,9% | passa |

**N≥100 continua reprovando só 2016 — robusto às duas correções.** Nem identidade nem
IPCA mudaram a conclusão. Cobertura mantém o mesmo formato de "duas eras" (81-85% em
2015-2019, 87%+ a partir de 2020) com números levemente diferentes.

## N=100: confirmado, mas registrado como evidência fraca, não forte

Reprovar 1 de 12 (margem de 3, 97 contra 100) prova que o piso não quebrou nada
observável — não prova que 100 é o valor ótimo. Registrado explicitamente em Seção 10,
critério 2, para não deixar "confirmado" ser lido como "validado com força": o piso
continua sendo uma guarda contra uma degradação futura que ainda não aconteceu de fato.
Se a cobertura degradar adiante, aí sim vai haver evidência real sobre calibração.

## Novo requisito de relatório: cobertura de fator por era

2015-2019 (~83% cobertura média) e 2020-2026 (~89%) não têm a mesma qualidade de dado —
mesmo raciocínio que já motivou a linha própria do setor financeiro (Seção 7.5/10,
critério 5). Uma vantagem concentrada na era de cobertura melhor pode ser sinal genuíno
(fatores funcionam melhor com mais dado real) ou artefato (menos ruído de imputação) —
sem reportar as duas eras separadas, as duas leituras ficam indistinguíveis. Adicionado
como exigência ao critério 5 do gate.

## Sequenciamento: formação mínima + backtest antes do motor de carteira completo

Seção 8 completa (tetos por ativo/setor, sobra não alocada, lote fracionário,
decomposição por fator) só compensa construir se os fatores tiverem poder — o backtest
não precisa dela para responder isso. Decisão registrada: formação mínima (top-N por
score composto, peso igual, rebalanceada mensalmente) para a Seção 9; motor completo
fica para depois do backtest validar sinal. Exceção que não adia: a regra de saída por
perda de liquidez (Seção 8) é sobre survivorship, não sobre alocação — qualquer backtest,
mínimo ou completo, precisa dela desde já.

## Testes + suíte

`test_acoes_ipca.py`: 6 testes novos, todos com dado real do BCB. Suíte completa
(`--ignore=tests/test_binance_ws_live.py`): 435 passed.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Nova Seção 6.3 (piso deflacionado por IPCA). Nova Seção 7.8 (correções pós-7.7: IPCA
isolado, identidade corrigida, tabela final, reconciliação do pico). Seção 10, critério 2
(N=100 evidência fraca) e critério 5 (cobertura por era). Preâmbulo em Seção 8 e nota em
Seção 9 (sequenciamento formação mínima antes do motor completo).

## Pendente

- Formação mínima de carteira (Seção 8, top-N/peso-igual) e backtest (Seção 9) —
  próximo passo direto da sequência decidida nesta rodada.
- Motor de carteira completo (Seção 8: tetos, sobra, lote fracionário, decomposição por
  fator) — depois do backtest validar sinal, não antes.

## Decisão

- Aprovado por: Brian — pediu verificar se o piso de liquidez é comparável ao longo da
  série antes de confiar na curva; pediu fechar a divergência do pico em vez de deixá-la
  aberta; pediu registrar N=100 como guarda, não validação forte, e cobertura por era
  como novo requisito de relatório; propôs inverter a ordem (formação mínima + backtest
  antes do motor de carteira completo), mesma lógica de provar um fator antes dos outros
  dois (2026-08-26).
- Justificativa: o piso nominal era um viés real e mensurável (fator 1,80× de inflação
  acumulada) que ninguém tinha pedido — corrigi-lo, não só documentá-lo, era o certo. A
  divergência do pico tinha uma explicação registrada mas não verificada; verificar
  achou que a explicação estava errada (não era identidade, era o piso de histórico
  mínimo) — generalização do mesmo princípio de todo o resto da spec: divergência aberta
  é convite a "conserto no sentido errado" se não fechada com número, não com suposição
  plausível.
