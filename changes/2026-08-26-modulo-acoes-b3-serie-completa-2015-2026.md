# 2026-08-26 — Módulo de Ações: série completa 2015-2026 executada, N≥100 confirmado, dois bugs reais pegos no caminho

## Contexto

`build_decisao` fechou a rodada anterior travado contra 2015 (106) e 2016 (97/98, com
a distinção de dois-fatores/três-fatores explicada e registrada). Usuário aprovou seguir
para os dez anos restantes, mas com uma condição explícita: não um laço que ou completa
os dez anos ou deixa o banco em estado ambíguo — um ano por vez, com asserção entre
exercícios fiscais, sanidade de universo contra a curva conhecida (~113-130, pico ~235
em 2022), e progresso registrado por ano para que uma interrupção vire inconveniência,
não investigação.

## Infraestrutura preparada antes de rodar

- **Identidade real, não atalho**: `cnpj_ticker_map` reconstruído do zero via o pipeline
  de produção real (`load_fca_identity` + `compute_vigencia` + `build_cnpj_ticker_map`),
  não o atalho de vigência "para sempre" usado na verificação de 2015/2016 — 754 tickers
  únicos extraídos diretamente da COTAHIST 2014-2026 (`NOMRES`, offset verificado contra
  dado real), FCA para todos os anos 2015-2026 (2015-2017/2023/2026 baixados nesta
  rodada, antes só 2018-2022/2024/2025 estavam disponíveis), 691 resolvidos / 63
  não resolvidos (`identidade_nao_resolvida`, contável, não escondido).
- **Convenção de data de decisão confirmada empiricamente**: último pregão de fevereiro
  de cada ano — verificado contra os dois anos já conhecidos (2015-02-27, 2016-02-29
  batem exatamente) antes de generalizar para 2017-2026.
- **Script de execução ano a ano** (`executar_ano.py`, scratchpad, não commitado —
  orquestração de medição, não infraestrutura de produção): por ano, garante o índice
  mestre + itens financeiros (DRE/BPP/BPA/DFC_MI) dos dois exercícios fiscais que aquela
  decisão precisa, roda `build_decisao`, checa sanidade do universo contra a banda
  (90-260), grava resultado em `progresso_serie.json` — só então segue para o próximo
  ano.

## Dois crashes reais durante a execução, os dois pegos pela própria estrutura de verificação

**1. Linhas duplicadas idênticas da CVM** (`backend/src/tradingbot/acoes/fatores.py`).
FY2023, 2 empresas reais: mesmo `CD_CONTA "3.99.01.01"` (EPS) repetido 2-3 vezes no
arquivo bruto, sempre com o mesmo valor. `get_eps_as_of` (e os helpers compartilhados
`_linha_unica`/`_linha_por_ds_conta`, mais o laço de candidatos do D&A) assumiam no
máximo uma linha e quebravam com `MultipleResultsFound` — bug real em produção, achado
só porque a série rodou 434 empresas reais em vez das 3 de sempre. Corrigido:
`_unica_por_conteudo` deduplica por `(vl_conta, ds_conta)` — uma cópia ou várias
idênticas resolvem normalmente; conteúdo divergente entre "duplicatas" continua `None`,
mesma disciplina de nunca adivinhar já usada no resto do módulo. 2 testes novos
reproduzindo os dois casos.

**2. `UniversoElegivel`/`UniversoExclusao` são append-only por desenho** — a primeira
tentativa de 2024 materializou o universo (206 empresas) e só depois morreu no laço de
fatores (bug 1, antes do fix). Reprocessar sem limpar fez todo `INSERT` falhar por
duplicata: universo saiu **zero**, mas a sanidade pegou (0 está fora de qualquer banda
razoável) em vez de deixar passar em silêncio. Corrigido no script de execução: limpa
`UniversoElegivel`/`UniversoExclusao` daquela data de decisão antes de cada tentativa —
mesmo raciocínio já aplicado a `CvmFinancialLineItem` para os exercícios fiscais na
rodada anterior (o achado `GETI4`).

Os dois bugs confirmam exatamente o que a estrutura "um ano por vez, com verificação
entre eles" foi desenhada para fazer: nenhuma interrupção corrompeu estado, cada uma foi
diagnosticada, corrigida e retomada exatamente de onde parou, sem reprocessar os anos já
verificados.

## Resultado: tabela completa 2015-2026

| Ano | Universo | Score computável | Cobertura |
|---|---|---|---|
| 2015 | 125 | 106 | 84,8% |
| 2016 | 115 | 98 | 85,2% |
| 2017 | 129 | 105 | 81,4% |
| 2018 | 135 | 115 | 85,2% |
| 2019 | 146 | 121 | 82,9% |
| 2020 | 169 | 147 | 87,0% |
| 2021 | 177 | 154 | 87,0% |
| 2022 | 194 | 175 | 90,2% |
| 2023 | 210 | 188 | 89,5% |
| 2024 | 206 | 195 | 94,7% |
| 2025 | 190 | 176 | 92,6% |
| 2026 | 178 | 165 | 92,7% |

## As duas medições que a rodada existia para produzir

**N≥100 reprova só 2016 (98) — 1 de 12 anos.** O vale já identificado, não uma fração
relevante da série. Confirma a previsão registrada na Seção 7.5 ("reprovar dois ou três
anos de vale é esperado; reprovar metade seria o número errado") — nem dois ou três, só
um. **N=100 fica confirmado, não só herdado** (Seção 10, critério 2) — decisão fechada.

**Cobertura sobe visivelmente a partir de ~2020 — segunda "duas eras", agora no eixo de
fator.** Média 2015-2019: 83,9%. Média 2020-2026: 90,5%. Subida real e sustentada, não
degrau único como a fronteira de identidade de 2018 (Seção 5.6) — consistente com FCA
populando ticker de forma mais confiável e menos retificação acumulada nos anos
recentes, mecanismo já antecipado na Seção 7.5.

## Achados colaterais, registrados sem forçar explicação

**Padrão cíclico com contração recente não antecipada**: universo cresce de 125 (2015) a
um pico de 210 (2023), depois contrai três anos seguidos (206 → 190 → 178, 2024-2026) —
padrão real, não ruído de um ano. Não investigado a fundo (fora do escopo desta rodada);
fica para quando o backtest cruzar esse período com resultado de mercado real.

**Divergência em aberto**: pico de universo medido aqui em 2022 é 194, não os "~235"
citados em rodadas anteriores. Explicação mais provável: o número anterior media só
liquidez (antes de identidade resolvida); `build_decisao` já materializa depois da
identidade (9-15 exclusões por `identidade_nao_resolvida` a cada ano). Não confirmado
revisitando a medição antiga nesta rodada — registrado como divergência aberta, não como
fato estabelecido.

## Testes + suíte

`test_acoes_fatores.py`: 2 testes novos (duplicata idêntica resolve; duplicata com
valores diferentes fica `None`). Suíte completa (`--ignore=tests/test_binance_ws_live.py`):
430 passed (commit anterior já capturou o fix + testes; esta rodada é spec/changes).

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Nova Seção 7.7: infraestrutura da execução, os dois crashes reais e como foram pegos, a
tabela completa, as duas medições finais, os dois achados colaterais. Seção 7.5:
"Pendente" trocado por "Confirmado (Seção 7.7)". Seção 10, critério 2: "Resolvido" —
N=100 confirmado, decisão fechada, não mais pendente de recalibração.

## Pendente

- Padrão de contração 2024-2026 — observação registrada, não investigada.
- Divergência do pico de 2022 (194 vs ~235 citado antes) — não confirmada.
- Motor de carteira (Seção 8) e backtest (Seção 9) — agora com série completa, piso
  confirmado, e driver travado, o próximo passo natural da sequência do usuário.

## Decisão

- Aprovado por: Brian — aprovou seguir com os créditos desconsiderados como
  preocupação, mas manteve a preocupação de fundo (estado inconsistente em caso de
  interrupção) como não-negociável; pediu a estrutura específica (um ano por vez,
  asserção entre eles, sanidade contra a curva conhecida, progresso registrado) antes de
  autorizar a execução dos dez anos (2026-08-26).
- Justificativa: a estrutura pedida não foi cautela por cautela — os dois crashes reais
  que aconteceram durante a execução são prova direta de que ela importava. Sem
  asserção de contagem e sanidade de universo, o segundo crash (append-only, universo
  zerado) teria produzido um número silenciosamente errado para 2024 em vez de parar
  para investigar. Sem progresso por ano, os dois crashes teriam custado reprocessar
  toda a série do zero, não só retomar do ponto exato onde cada um parou.
