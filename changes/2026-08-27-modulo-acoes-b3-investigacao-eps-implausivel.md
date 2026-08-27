# 2026-08-27 — Módulo de Ações: investigação do EPS implausível — causas múltiplas, mitigação por detecção

## Contexto

Usuário pediu para investigar os 28 casos de earnings yield implausível achados na
rodada da interface, como uma coisa só (caracterização + correção), com duas condições:
usar o método que fechou o `EX` (olhar a distribuição inteira, não só a cauda, achar
vão real) para derivar o limiar em vez de escolher um número redondo; e checar
clustering por exercício/setor/conta para saber se é uma causa só (corrigível com regra
de `DS_CONTA`) ou várias (limiar precisa ser conservador de verdade).

## 1. Distribuição completa, não só a cauda

Earnings yield de todas as 12 datas de decisão (1534 pontos com dado real) ordenado por
módulo: salto de **3,52x** entre |23,93| e |6,80| — o maior salto de toda a cauda, o
resto fica entre 1,0x-1,3x. Vão real, mesmo padrão do `EX` (Seção 5.3). Com esse limiar
(não os 300% de conveniência usados no achado original), **11 pontos** ficam acima do
vão, não 28 — o número original superestimava porque capturava distress real
(`RSID3` etc.) junto com dado ruim de verdade.

ROE passou pelo mesmo teste e **não tem vão real** — maior salto 2,41x, resto sob 1,6x,
distribuição contínua. Os valores extremos (`CVCB3`, `RCSL3`) são patrimônio líquido
perto de zero em empresas reais em distress. Nenhum limiar novo criado para ROE —
inventar um sem vão real seria exatamente o erro que este método existe para evitar.

## 2. Clustering — causas múltiplas confirmadas, não uma só

Checagem independente decisiva (sugerida pelo usuário): número de ações implícito
(`lucro_controladores / eps`) é estável entre anos de uma mesma empresa quando o dado é
bom, e colapsa por ~1000x exatamente nos anos contaminados — não coincidência,
confirmado empresa a empresa.

- **Dado corrompido na própria fonte CVM**: `AMAR3` (`-27.439.999.999.999.998,00`
  literal no CSV publicado), `MEAL3` (`-285.444.400,00`) — nenhuma correção de escala
  resolve.
- **Erro de escala ~1000x**: `ITUB4` (EPS bruto 2.780 em 2020-02-28; ações implícitas
  batem exatamente ao dividir por 1000, ~9,7 milhões → ~9,75 bilhões, consistente com o
  resto da série do banco), `EVEN3`, `MOSI3`.
- **`ESCALA_MOEDA='MIL'` não é sinal confiável sozinho**: testado como possível regra de
  correção automática, mas `AZUL4` (earnings yield -680%, plausível, dentro do vão)
  também tem `ESCALA_MOEDA='MIL'` no mesmo `CD_CONTA`, com valor já correto. Dividir
  "sempre que MIL" quebraria esse caso. Nenhuma correção automática de escala foi
  implementada por causa disso — risco de "consertar" errado maior que o de excluir.
- **Possivelmente real**: `PDGR3` aparece em 3 anos — tem eventos reais de grupamento
  registrados (`CorporateEventFlag`) em datas próximas, então a checagem de
  "ações estáveis entre anos" não se aplica a ela do mesmo jeito. Não resolvido caso a
  caso nesta rodada.

**Conclusão direta do usuário confirmada**: com causas múltiplas, o limiar não é rede
de segurança de uma correção única — é o que faz o trabalho de verdade, e por isso fica
conservador (nunca tenta adivinhar escala).

## 3. Mitigação implementada: detecção, nunca correção automática

`fatores.py`: `EARNINGS_YIELD_IMPLAUSIVEL_LIMIAR = 10.0` (derivado do vão, não
escolhido por conveniência). `earnings_yield_raw` devolve `None` (indefinido) acima do
limiar — mesmo tratamento já dado a EBITDA≤0/patrimônio≤0, entra na imputação por
mediana como qualquer outro fator ausente, nunca vira um número que distorce ranking.

`api.py`: `_detalhe_earnings_yield` atualizado para o mesmo padrão já usado em
`_detalhe_divida_liquida_ebitda` — `motivo="indefinido"` quando o valor bruto existe
mas é implausível, carimbo preservado (sabe-se a data do filing, mesmo sem valor
utilizável).

**Achado colateral, registrado não corrigido**: testando o limiar com um valor
agressivo, `compute_demeaned_percentiles`/`winsorize` quebra (`TypeError`) se **nenhuma**
empresa do universo tiver valor real para um fator — caso degenerado nunca antes
exercitado. Baixa probabilidade em produção (o limiar real de 1000% nunca chega perto
de excluir um universo inteiro), mas real.

## Testes + suíte

4 testes novos: `earnings_yield_raw` implausível vira `None` (dois casos reais,
`ITUB4`/`EVEN3`) e continua computando normal para caso plausível mas grande (`AZUL4`);
teste de API confirma `motivo="indefinido"` + carimbo preservado, sem afetar as demais
empresas. Suíte completa (`--ignore=tests/test_binance_ws_live.py`): 491 passed.

## Pendente

- Causa raiz na ingestão (capturar `ESCALA_MOEDA`, hoje totalmente ignorado por
  `cvm_ingestion.py`) e uma regra de correção real (seguindo o número de ações
  implícito, não o campo sozinho) — reduziria a taxa de exclusão, não implementado.
- `PDGR3`: resolver caso a caso se os 3 anos são reestruturação real de capital ou
  dado ruim, cruzando a data exata do grupamento contra `dt_refer` de cada filing.
- Corrigir o caso degenerado do `winsorize` (achado colateral acima).
- **Decisão em aberto, não tomada aqui**: rerodar o backtest (Seção 9.6) uma vez com a
  mitigação aplicada, para saber se o resultado nulo muda com o dado implausível
  excluído. Não é reabertura de busca — é uma confirmação, e fica para quem lê este
  registro decidir.

## Decisão

- Aprovado por: Brian — pediu a investigação como uma coisa só (caracterização +
  correção), com o método de olhar a distribuição completa e derivar o limiar do vão
  real, e checar clustering para saber se é uma causa ou várias (2026-08-27).
- Justificativa: a checagem de ações implícitas confirmou múltiplas causas distintas —
  a pergunta que decidia se o limiar seria rede de segurança ou trabalho de verdade.
  Não implementar correção automática de escala foi decisão deliberada, não omissão —
  o caso `AZUL4` mostrou que a regra óbvia (`ESCALA_MOEDA='MIL'` → dividir por 1000)
  quebraria dado que já estava certo.
