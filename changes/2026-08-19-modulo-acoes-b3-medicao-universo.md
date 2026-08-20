# 2026-08-19 — Módulo de Ações: medição real do universo elegível (COTAHIST)

## Contexto

Seções 6 e 7 fechadas nesta mesma data. Antes de avançar para a Seção 8, usuário pediu
uma medição barata que calibra o resto do desenho: rodar o filtro de liquidez da Seção 6
sobre o histórico real da COTAHIST e contar quantas empresas passam em cada data de
decisão — mesmo raciocínio dos folds degenerados do bot, "número que parece detalhe
define viabilidade". A medição também transforma o N mínimo do gate de promoção (Seção
10, critério 2) de placeholder em número justificado, e testa a hipótese de que o
universo cresce ao longo do tempo.

## Duas perguntas que condicionavam a Seção 6, respondidas sem nova verificação

Já estavam confirmadas na rodada anterior (`changes/2026-08-19-modulo-acoes-b3-fonte-preco-cotahist.md`):
COTAHIST devolve volume **financeiro** em campo próprio (`VOLTOT`, separado de `QUATOT`),
e cobre papéis deslistados (`OGXP3`, presente no arquivo de 2013, ausente no de 2024).
As duas eram positivas — Seção 6 não está apoiada em suposição.

## Método

Baixados 9 arquivos anuais reais da COTAHIST, amostra bienal 2010–2025 (2010, 2012, 2014,
2016, 2018, 2020, 2022, 2024, 2025). Layout confirmado de novo via `pdftotext` sobre o PDF
oficial já baixado na rodada anterior (posições `CODBDI` 11-12, `TPMERC` 25-27, `ESPECI`
40-49, `CODNEG` 13-24, `VOLTOT` 171-188), não assumido de memória.

Filtro aplicado por data de decisão (último pregão de cada mês):

- Registro tipo `01`, `CODBDI == "02"` (lote padrão), `TPMERC == "010"` (mercado à vista).
- `ESPECI` começando com `ON`/`PN`/`PR`/`OR` ou igual a `UNT` — exclui BDR, fundos (`CI`,
  cobre FII e ETF), direitos de subscrição, recibos, bônus, warrants.
- Mediana de `VOLTOT` em janela móvel de 63 pregões (~3 meses) terminando na data de
  decisão, mínimo de 20 pregões na janela para o ticker entrar na conta.
- Uma classe por empresa: agrupado pelo prefixo de 4 letras do ticker (`PETR` para
  `PETR3`/`PETR4`), mantida só a classe com maior mediana — a mesma regra da Seção 6.
- Testado em dois patamares de corte, R$500 mil/dia e R$1 milhão/dia — ordens de grandeza
  ilustrativas, ainda não comprometidas na spec como valor final de produção.

## Resultado

| Ano | pregões | tickers de ação/unit | N mín. (≥R$500k) | N máx. (≥R$500k) | N mín. (≥R$1M) | N máx. (≥R$1M) |
|---|---|---|---|---|---|---|
| 2010 | 247 | 543 | 145 (0 em jan, janela incompleta) | 159 | 127 | 146 |
| 2012 | 246 | 499 | 148 | 154 | 130 | 143 |
| 2014 | 248 | 452 | 142 | 147 | 128 | 139 |
| 2016 | 249 | 438 | **113** (0 em jan, janela incompleta) | 132 | **107** | 118 |
| 2018 | 245 | 428 | 144 | 152 | 133 | 140 |
| 2020 | 249 | 429 | 171 | 198 | 162 | 188 |
| 2022 | 250 | 464 | 230 | **235** | 214 | **227** |
| 2024 | 251 | 434 | 204 | 207 | 186 | 194 |
| 2025 | 250 | 421 | 189 | 198 | 178 | 184 |

(Contagens de janeiro em 2010 e 2016 zeradas por artefato de borda — arquivo daquele ano
sozinho não tem pregões suficientes em janeiro para preencher a janela de 63 dias; não é
colapso real do universo, é a amostragem não carregar o ano anterior. Excluídas da leitura
de mínimo/máximo.)

## Achado principal: o universo não cresce de forma monotônica — é cíclico

A hipótese registrada na conversa ("provavelmente ele cresce bastante") não se confirmou.
O padrão real é cíclico, correlacionado com o ciclo econômico: queda acentuada em 2016
(recessão brasileira 2015–2016, mínimo do período ≥R$500k), recuperação gradual até pico
em 2022, e um recuo moderado em 2024–2025. Nenhum ano posterior a 2016 chegou a repetir o
mínimo de 2016, mas o formato geral é "sobe, desce, sobe" — não uma reta crescente.

Consequência prática, registrada na Seção 13: folds temporais em anos de recessão têm
corte transversal mais estreito que a média, **não só os anos mais antigos do histórico**
— o piso do gate precisa sobreviver ao pior ano observado, não ao ano médio nem só aos
primeiros anos.

## N=100 para o gate de promoção (Seção 10, critério 2)

Escolhido abaixo do pior ano observado (~113 em ≥R$500k/dia, ~107 em ≥R$1M/dia), com
margem — não o valor médio, nem otimista. Registrado em Seção 10 com referência a este
documento. Sujeito a revisão quando: (a) a amostra deixar de ser bienal e cobrir todos os
16 anos, (b) o threshold de liquidez de produção for definido (aqui só testados dois
valores ilustrativos), (c) o agrupamento por prefixo de ticker for substituído pelo
`cnpj_ticker_map` real (Seção 5.1, pendência de Fase 2).

## Limitações desta medição, declaradas

- Amostra bienal (9 de 16 anos), não exaustiva — tendência visível, não todo o histórico.
- Agrupamento "uma empresa" por prefixo de 4 letras do ticker é aproximação, não o
  mapeamento CNPJ↔ticker real (ainda não implementado).
- Threshold de R$500k/1M é ilustrativo — não determina o valor de produção, só ancora a
  ordem de grandeza para justificar N.
- Não segmenta por setor — a pergunta de concentração setorial dentro do universo elegível
  (relevante para a população mínima por setor da Seção 7) fica para quando houver fonte
  de classificação setorial B3 mapeada, algo ainda não resolvido nesta frente.

Nenhum código de produção foi escrito — script de medição ficou no scratchpad da sessão,
não faz parte do repositório.

## Decisão

- Aprovado por: Brian — pediu a medição "antes de partir para a Seção 8", com o
  raciocínio explícito de que "número que parece detalhe define viabilidade" (paralelo
  direto com os folds degenerados do bot), e a expectativa de que o universo "provavelmente
  cresce bastante" — hipótese que a medição não confirmou (2026-08-19).
- Justificativa: medir antes de escrever código evita descobrir tarde que o piso do gate
  (Seção 10) ou a população mínima por setor (Seção 7) são inviáveis para o histórico real
  disponível — mesma disciplina de "dado real, não suposição" do resto da Fase 1.
