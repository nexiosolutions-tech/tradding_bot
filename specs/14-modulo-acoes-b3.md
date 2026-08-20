# 14 — Módulo de Ações (B3): apoio à decisão de aporte mensal

> **Status:** proposta inicial, não implementada
> **Depende de:** infraestrutura de ingestão, validação e gate de promoção já existentes (specs 02–07)
> **Não depende de:** nada do bot de cripto em runtime — os dois módulos compartilham fundação, não estado

---

## 1. Objetivo

Fornecer, uma vez por mês, uma **base de evidência consolidada e auditável** para a decisão de aporte em ações da B3: quais empresas do universo elegível estão melhor posicionadas segundo critérios explícitos, com cada número rastreável até sua fonte primária e sua data de publicação.

O sistema **ordena e evidencia**. Quem decide o aporte é o usuário.

## 2. Não-objetivos

Delimitados explicitamente para evitar deriva de escopo:

- **Não** emite recomendação de compra/venda nem opera ordens.
- **Não** projeta preço-alvo nem retorno futuro de ativo individual.
- **Não** substitui análise de consultor ou assessor certificado.
- **Não** usa fonte não rastreável: nada de "sentimento de rede social", relatório sem autoria, ou número sem data de publicação.
- **Não** exibe gráfico que não sustente uma decisão — todo elemento de UI precisa responder a uma pergunta do fluxo de aporte.

## 3. Princípios herdados do bot

Aplicam-se integralmente, e são o motivo de esta frente ser barata:

| Princípio | Origem | Aplicação aqui |
|---|---|---|
| Janela fixa (`start_ms`/`end_ms`) | incidente de janela relativa | todo backtest e diagnóstico usa datas fixas, nunca relativas a `now()` |
| Régua honesta | benchmark vs. buy-and-hold | toda carteira sugerida é comparada a IBOV, IBrX-100, SMLL e CDI |
| Teste de nulidade | permutação de labels | permutar a correspondência fator→retorno; o pipeline não pode achar alfa no ruído |
| Gate de promoção | `promotion.py` | nenhum conjunto de fatores entra em produção sem passar o gate |
| Asserção de frescor | `run_daily_learning.py` | dado desatualizado bloqueia a geração do relatório mensal |
| `environment` / proveniência | captura mainnet vs. testnet | cada número carrega fonte, data de coleta e data de publicação |
| Documentação em `changes/` | prática atual | toda decisão de desenho registrada com evidência |
| Log de experimentos | `learning_engine/experiment_log.py` | mesmo componente, campo de domínio na entrada e contadores separados por módulo — o N do DSR é específico do problema; tentativas do bot não podem inflar (nem ser infladas por) o viés de seleção do módulo de ações |

## 4. Fontes de dados

**Regra inegociável:** só entra fonte primária, pública e com termo de uso compatível. Antes da implementação, cada fonte abaixo precisa ter disponibilidade, formato e ToS **verificados** — a lista é candidata, não confirmada.

### 4.1 Fundamentos (prioridade máxima)

- **CVM — Dados Abertos** (`dados.cvm.gov.br`): DFP (anual) e ITR (trimestral) estruturados, com **data de entrega**. É a fonte canônica e a única que permite montar dado *point-in-time* corretamente.
- **Formulário de Referência (FRE)**: composição acionária, governança, fatores de risco declarados.
- **Site de RI da companhia**: apenas para conferência pontual, nunca como fonte primária automatizada.

### 4.2 Mercado

- **B3 — COTAHIST**: fonte primária de preço, confirmada (Seção 5.3). Preço bruto, não ajustado.
- **`brapi.dev`**: fonte secundária/conveniência para proventos de tickers líquidos atuais e dado recente (Seção 5.3) — não para o histórico ponta a ponta.
- **`yfinance`**: descartado (Seção 5.3) — o COTAHIST cobre tudo que ele cobriria, com menos risco de ToS e sem o problema de série pré-ajustada.

### 4.3 Macro

- **Banco Central — SGS**: Selic, CDI, câmbio.
- **IBGE**: IPCA.

### 4.4 Fontes explicitamente rejeitadas

Sites agregadores que proíbem scraping em ToS; qualquer "carteira recomendada" de terceiro; conteúdo de rede social; qualquer número sem data de referência e data de publicação.

## 5. Camada point-in-time (a parte crítica)

> Esta seção é a diferença entre um sistema honesto e um backtest que mente.

**Problema:** o balanço do exercício encerrado em 31/12 é publicado em março. Um backtest que use o dado de 31/12 a partir de janeiro está enxergando o futuro. Em ações, esse é o vazamento mais comum e o mais devastador.

**Requisito:** toda tabela de fundamento tem duas datas — `data_referencia` (a que o número se refere) e `data_publicacao` (quando ficou público, extraída da entrega à CVM). **Toda consulta histórica filtra por `data_publicacao <= data_da_decisao`.** Sem exceção.

**Survivorship bias:** o universo histórico precisa incluir empresas que saíram da bolsa (falência, fechamento de capital, incorporação). Backtest só com sobreviventes superestima retorno sistematicamente. Requisito: tabela de universo com `data_entrada` e `data_saida` por ticker, e o backtest reconstrói o universo elegível em cada data de decisão.

**Eventos corporativos:** preços ajustados por desdobramento, grupamento, bonificação, JCP e dividendos. Série não ajustada gera retorno falso em toda data de evento.

### 5.1 Fonte CVM confirmada, com contrato de ingestão (2026-08-19)

A Seção 4 marcava CVM Dados Abertos como candidata, não confirmada. Verificado agora por
acesso direto (não pela documentação do portal, que não expõe as colunas) — baixado
`https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_2024.zip` (e
confirmado o mesmo padrão para `ITR`) e inspecionados os CSVs reais:

- **`data_publicacao` existe e tem o nome exato `DT_RECEB`** — mas só no arquivo-índice
  mestre (`dfp_cia_aberta_AAAA.csv`), não nos arquivos de linha de item financeiro
  (`dfp_cia_aberta_DRE_con_AAAA.csv` etc., que só têm `DT_REFER`). Contrato de ingestão:
  toda linha de fundamento é join com o índice mestre por
  `(CNPJ_CIA, DT_REFER, VERSAO)` para herdar `data_publicacao = DT_RECEB`. Confirmado
  com dado real: Banco do Brasil, exercício 2024-12-31, `DT_RECEB=2025-02-19`; BRB Banco
  de Brasília, mesmo exercício, `DT_RECEB=2025-04-09` — o lag varia por empresa,
  exatamente por isso não dá para assumir um atraso fixo.
- **Armadilha adicional, não estava na Seção 5 original**: cada filing traz o exercício
  atual (`ORDEM_EXERC=ÚLTIMO`) **e** o exercício anterior comparativo
  (`ORDEM_EXERC=PENÚLTIMO`) na mesma linha de dado. O mesmo ano-fiscal aparece em dois
  filings diferentes (como ÚLTIMO no filing do próprio ano, como PENÚLTIMO comparativo no
  filing do ano seguinte) — possivelmente com valor **reapresentado/diferente**, cada um
  com sua própria `data_publicacao`. Regra de ingestão: só `ÚLTIMO` entra como fato
  point-in-time primário; `PENÚLTIMO` fica disponível só para detecção de reapresentação,
  nunca como fonte de um fator.
- **`VERSAO` existe** — um filing pode ser retificado depois da entrega original, gerando
  uma nova versão com sua própria `DT_RECEB` (posterior). Consulta point-in-time correta:
  para cada `(CNPJ_CIA, DT_REFER)`, usar a versão de maior `VERSAO` cuja `DT_RECEB <=
  data_da_decisão` — nunca a versão mais recente publicada até hoje, cujo `DT_RECEB` pode
  ser posterior à data da decisão sendo consultada.
  - **Consequência estrutural para o armazenamento (2026-08-19)**: isso obriga a tabela de
    filings a ser **append-only**. Uma retificação chega como uma linha nova
    `(CNPJ_CIA, DT_REFER, VERSAO+1, DT_RECEB_nova)`, nunca sobrescrevendo a linha da
    versão anterior — se a ingestão fizer `UPDATE` in place, a versão antiga desaparece e
    a consulta point-in-time para uma data anterior à retificação passa a devolver o valor
    retificado, quebrando a garantia point-in-time silenciosamente (a consulta continua
    rodando sem erro, só devolve o número errado). Chave primária de fato é
    `(CNPJ_CIA, DT_REFER, VERSAO)`, e o pipeline de ingestão só faz `INSERT`.
- **Refinamento da regra de `ORDEM_EXERC` (2026-08-19)**: se `PENÚLTIMO` for usado algum
  dia (detecção de reapresentação, auditoria), ele precisa ser carimbado com o `DT_RECEB`
  do filing que o **contém** (o filing do ano seguinte, que é quando esse número
  reapresentado ficou público), nunca com a `DT_REFER` do próprio exercício a que se
  refere — carimbar com a data do exercício injetaria, na prática, informação do futuro
  (o valor reapresentado, disponível só depois, aparecendo como se fosse conhecido desde
  a data original).
- Arquivos são CSV `;`-delimitado, **latin-1** (não UTF-8) — confirmado por erro de
  decodificação direto. Escala: ~870 filings/ano no índice DFP, ~33k linhas de item por
  arquivo de demonstração (`DRE_con`, por exemplo) — tamanho trivial para armazenamento
  relacional local.
- **Cobertura histórica, verificada por sondagem direta de URL (2026-08-19)**: DFP
  disponível de **2010** a 2026 (`dfp_cia_aberta_2009.zip` → HTTP 404,
  `dfp_cia_aberta_2010.zip` → HTTP 200); ITR disponível de **2011** a 2026
  (`itr_cia_aberta_2010.zip` → 404, `itr_cia_aberta_2011.zip` → 200). ~16 anos de dado
  anual, ~60 trimestres de dado trimestral — número que decide a viabilidade estatística
  da frente inteira (Seção 13, "amostra pequena"): dá para sustentar algo como 8-10 folds
  de walk-forward com ~6 trimestres cada, na mesma ordem de grandeza do piso que o gate de
  promoção já assume (Seção 10, critério 1: mínimo de 8 folds) — não uma garantia de que
  vai passar no gate, mas confirma que o desenho do gate não está pedindo mais folds do
  que o histórico permite entregar.
- **Peça que faltava no contrato: mapeamento CNPJ↔ticker.** CVM identifica empresa por
  `CNPJ_CIA`; cotação (Seção 4.2) vem por ticker B3. Uma empresa pode ter múltiplas
  classes de ação (ON, PN, UNIT) mapeando pro mesmo CNPJ, e tickers mudam com
  incorporação/fusão/troca de nome — justamente os casos mais interessantes para o
  universo elegível (Seção 6) e para eventos corporativos (Seção 5). Sem uma tabela de
  mapeamento com vigência por data (`cnpj_ticker_map`: `cnpj_cia`, `ticker`,
  `data_inicio`, `data_fim`), o join histórico entre fundamento (CNPJ) e preço (ticker)
  erra silenciosamente exatamente nas empresas que passaram por evento societário. Precisa
  existir antes da Fase 2 (universo elegível + eventos corporativos), não antes da Fase 1
  — mas registrado aqui porque é a mesma disciplina point-in-time desta seção, não uma
  preocupação nova.
- **Ainda não verificado nesta rodada**: formato do FRE (Formulário de Referência, Seção
  4.1); e o ToS explícito do portal (dados.gov.br costuma ser aberto, mas não foi lido
  linha a linha).

### 5.2 Contrato de consulta point-in-time (Fase 1, critério de aceite)

```sql
-- "o que a empresa X tinha publicado, como sabido na data D"
SELECT li.*, f.dt_receb AS data_publicacao
FROM cvm_financial_line_items li
JOIN cvm_filings f USING (cnpj_cia, dt_refer, versao)
WHERE li.cnpj_cia = :cnpj
  AND li.ordem_exerc = 'ÚLTIMO'
  AND f.dt_receb <= :data_da_decisao
  AND f.versao = (
      SELECT MAX(f2.versao) FROM cvm_filings f2
      WHERE f2.cnpj_cia = f.cnpj_cia AND f2.dt_refer = f.dt_refer
        AND f2.dt_receb <= :data_da_decisao
  )
ORDER BY li.dt_refer DESC;
```

Teste automatizado de aceite (critério já listado na Seção 15, agora com dado real para
provar): usando o filing real do Banco do Brasil acima —
consultar com `data_da_decisao = 2025-02-18` deve **não** retornar o exercício
2024-12-31; consultar com `data_da_decisao = 2025-02-19` (ou depois) deve retornar. Sem
dado sintético — o dado real já baixado prova o contrato.

### 5.3 Fonte de preço confirmada — COTAHIST vira primária, `brapi`/`yfinance` rebaixadas (2026-08-19)

Mesma disciplina da Seção 5.1: baixado o arquivo real
(`https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A2024.ZIP`) e o layout oficial
(`SeriesHistoricas_Layout.pdf`, B3), em vez de confiar em documentação de terceiro.
Resultado do checklist rodado ponto a ponto:

- **Ticker deslistado — o teste que mais importava.** `OGXP3` (OGX Petróleo, faliu)
  aparece plenamente no arquivo de 2013 (ano em que era negociada) e está ausente do
  arquivo de 2024 — cada arquivo anual é um snapshot imutável do que foi negociado
  **naquele** ano, não uma lista de empresas atuais. Survivorship (Seção 5) resolvido na
  origem. Testado o oposto em `brapi.dev`: `PETR4` (líquida, atual) responde sem token;
  `OGXP3` e um ticker inválido (`XYZW9`) — mesmos parâmetros — devolvem
  `"Token de autenticação não fornecido"`. Evidência forte de que o plano gratuito do
  `brapi` é uma lista de tickers atuais/líquidos, inutilizável para backtest
  survivorship-correto sem plano pago.
- **Bruto vs. ajustado.** Confirmado bruto: o layout oficial não tem nenhum campo de
  ajuste — `PREABE`/`PREMAX`/`PREMIN`/`PREMED`/`PREULT` são preços de negociação diretos;
  documentação do produto declara explicitamente "sem ajuste para inflação ou
  distribuições". Sem o problema do `adjusted close` do Yahoo (recalculado
  retroativamente a cada provento, vazamento point-in-time análogo ao do `VERSAO` da
  CVM). Regra de ingestão: preço bruto do COTAHIST + eventos corporativos numa tabela
  separada, ajuste aplicado só na consulta — nunca ingerir série pré-ajustada de terceiro.
- **Volume: em reais, campo próprio, separado de quantidade.** Layout confirma dois campos
  distintos — `QUATOT` (posições 153-170, quantidade de títulos) e `VOLTOT` (171-188,
  volume financeiro, formato `N(16)V99` = valor com 2 casas decimais). O filtro de
  liquidez da Seção 6 usa `VOLTOT`.
- **Retroatividade: 1986, bem além do necessário.** Confirmado por sondagem direta de URL
  (`COTAHIST_A1986.ZIP` → HTTP 200). O histórico conjunto (preço + fundamento) fica de
  qualquer forma limitado pelo piso da CVM (2010, Seção 5.1) — preço não é o fator
  limitante.
- **Cobertura: tudo que negociou, não só líquidos.** O mesmo teste do item 1 (`OGXP3`,
  uma ação em colapso, presente no arquivo) já é evidência disso. Arquivo mistura ações,
  fundos, opções, termo, leilões etc. — campos `CODBDI` (02 = lote padrão, o filtro certo
  pra ação regular; ver tabela completa no layout), `TPMERC` (010 = mercado à vista) e
  `ESPECI` (ON/PN/PNA-H/UNT/BDR/...) isolam o universo de ações do resto.
- **Limites e ToS.** Arquivo estático, servido pela própria infraestrutura da B3
  (`bvmf.bmfbovespa.com.br`), sem token, sem rate limit encontrado — perfil de risco bem
  mais baixo que o plano gratuito do `brapi` (allowlist + cota, como o item 1 sugere) ou
  o `yfinance` (scraping não oficial do Yahoo). ToS ainda não lido linha a linha
  (mesma ressalva da Seção 5.1 para a CVM) — mas o sinal operacional já é forte.
- **Formato**: texto de largura fixa (245 bytes/registro), não CSV — layout com posição
  exata de cada campo, oficial e estável (revisão de 2005, mesma desde então). Um parser
  por slice de posição é direto e não ambíguo, dado o layout documentado.
- **O que falta**: **não existe arquivo bulk oficial e gratuito da B3 para proventos
  (dividendos/JCP/desdobramentos)** equivalente ao COTAHIST — só produtos de API,
  pagos ou de terceiro. `brapi.dev` devolve `dividendsData.cashDividends` (com `paymentDate`,
  `approvedOn`, `rate`, `label`) para tickers líquidos atuais sem token — usável como
  fonte de proventos **recentes de nomes líquidos**, mas sujeita à mesma limitação de
  allowlist do item 1 para o histórico completo, inclusive de empresas hoje deslistadas.
  Este é o item mais aberto da camada de preço — decisão de como preencher proventos
  históricos de nomes não cobertos pelo `brapi` fica pendente para quando a Fase 1
  (cotação) estiver perto de começar. Enquanto isso não for resolvido, a regra de
  consistência abaixo evita que o gap vire erro silencioso.

**Veredito**: COTAHIST vira fonte primária de preço (bruto + volume + universo completo,
survivorship resolvido). `brapi.dev` fica como conveniência para proventos recentes de
tickers líquidos, não como fonte primária. `yfinance` descartado — o COTAHIST cobre tudo
que ele cobriria, com menos risco de ToS e sem o problema de série pré-ajustada.

**Regra de consistência (price-only vs. total-return): nunca misturar.** Ter provento dos
sobreviventes e não dos deslistados faria o retorno total ser medido de formas diferentes
em dois subgrupos do mesmo universo — erro concentrado exatamente na população que existe
para corrigir survivorship, pior que um erro uniforme. Enquanto não houver fonte de
proventos com a mesma cobertura do COTAHIST (todo ticker que já negociou, não só líquidos
atuais), o backtest roda **price-only para todo o universo**. Total-return só é permitido
quando houver provento coberto para 100% dos nomes elegíveis naquela data de decisão —
nunca parcial. Consequência direta para a Seção 7: a família de dividendos fica **marcada
como não utilizável em fator validado por backtest** até a fonte existir; pode aparecer na
camada de evidência do mês corrente (dado do `brapi` para nomes líquidos), mas não entra
no score.

## 6. Universo elegível

Filtros aplicados em cada data de decisão, todos configuráveis, versionados e
**materializados em tabela na própria data de decisão** — nunca recalculados
retroativamente a cada execução, mesmo princípio da janela fixa do bot
(`specs/07-backtesting-e-validacao.md`): reprodutibilidade exige que o universo de uma
data passada não mude porque a lógica do filtro mudou depois.

- **Liquidez mínima: mediana de `VOLTOT` (volume financeiro em R$) em janela móvel, não
  média.** Média é dominada por dias de pico (IPO, notícia, rebalanceamento de índice) e
  superestima liquidez sustentável — exatamente o tipo de nome que o backtest promete
  conseguir executar e a operação real não consegue. `VOLTOT` vem pronto da COTAHIST
  (Seção 4.2/5.3), não precisa ser derivado de quantidade × preço.
- **Uma classe por empresa.** Regra: a classe (ON/PN/UNIT) mais líquida (por `VOLTOT`) na
  data de decisão, **registrada por data** — não fixa para sempre. Uma empresa pode trocar
  de classe mais líquida ao longo do histórico (ex. migração de UNIT); gravar a escolha
  por data evita trocar de classe no meio da série sem rastro, e mantém o critério auditável
  (por que esta classe, nesta data).
- **Exclusões declaradas**: BDR e ETF/FII (via `ESPECI`/`TPMERC` da COTAHIST — não são
  ações de empresa, não passam pelos fatores da Seção 7); empresas em recuperação
  judicial (flag da CVM); histórico mínimo insuficiente para calcular todos os fatores da
  Seção 7 (sem dado suficiente, não entra no ranking daquele mês — não é penalizado, é
  omitido).
- **Assertiva de tamanho mínimo**, ligada diretamente ao critério transversal do gate de
  promoção (Seção 10): se o universo elegível em uma data cai abaixo do piso que a Seção
  10 assume para a margem de comparação, a geração do universo falha explicitamente
  naquela data em vez de produzir um ranking sobre amostra pequena demais silenciosamente.

**Medido contra dado real, não assumido.** O filtro acima (mediana de `VOLTOT`, uma
classe por empresa) foi rodado contra COTAHIST em 9 anos amostrados de 2010 a 2025 —
resultado, número de N=100 do gate e a correção da hipótese de crescimento monotônico em
`changes/2026-08-19-modulo-acoes-b3-medicao-universo.md` e Seção 10/13. A medição usou o
prefixo de 4 letras do ticker como proxy de "empresa" (ex. `PETR` para `PETR3`/`PETR4`) —
aproximação razoável para contar, mas não substitui o mapeamento `cnpj_ticker_map` já
identificado como pendência da Fase 2 (Seção 5.1) para a implementação real do filtro.

## 7. Fatores

Nenhum fator inventado. Cada um precisa de referência na literatura e de justificativa econômica documentada na spec — se não há explicação de *por que* deveria funcionar, é mineração de dado.

| Família | Exemplos de métrica | Fonte |
|---|---|---|
| Valor | P/L (earnings yield), P/VP, EV/EBITDA, FCF yield | CVM + preço |
| Qualidade | ROIC, ROE, margem, estabilidade de margem | CVM |
| Saúde financeira | dívida líquida/EBITDA, cobertura de juros, liquidez corrente | CVM |
| Crescimento | CAGR de receita e de lucro, consistência | CVM |
| Momentum | retorno 6–12 meses excluindo o mês mais recente | preço |
| Dividendos | dividend yield, payout, consistência plurianual | proventos — **não utilizável em fator validado por backtest** até a fonte de proventos ter a mesma cobertura do COTAHIST (Seção 5.3); pode aparecer na camada de evidência do mês corrente |
| Tamanho | valor de mercado | preço + capital social |

**Normalização:** cada métrica vira percentil **dentro do setor** na data de decisão, não valor absoluto. Comparar P/L de banco com o de mineradora é ruído. Setorização via classificação B3, versionada.

**Matriz de aplicabilidade de fator por setor.** Banco não tem EV/EBITDA, dívida líquida
nem capital de giro no sentido usual das demais empresas — o balanço de uma instituição
financeira não segue a mesma estrutura contábil (ativo é majoritariamente crédito
concedido, não capital fixo). A B3 é pesada em bancos: excluí-los perde um terço do
mercado, mas calcular EV/EBITDA de banco produz número sem significado econômico e o
score fica errado por construção, não por ruído. Requisito: tabela explícita declarando,
por família de fator, em quais setores ela se aplica (ex.: Saúde financeira usa índice de
Basileia + inadimplência para bancos, dívida líquida/EBITDA para o resto). Setor sem
fator aplicável não pontua naquela família — não recebe zero nem é excluído do universo,
fica ausente do score composto daquela família especificamente.

**Lucro negativo: earnings yield, não P/L bruto.** P/L de empresa deficitária é negativo
e, num ranking ingênuo por P/L cru, aparece como "a mais barata" — sinal invertido, erro
clássico de fator de valor. Métrica de valor baseada em lucro usa earnings yield
(lucro/preço, o inverso do P/L): deficitárias ficam corretamente no fundo do ranking, sem
precisar de tratamento especial.

**Dado faltante: regra declarada, não implícita.** Quando uma empresa não tem o campo
para um fator (demonstração incompleta, métrica não aplicável), duas opções — excluir a
empresa daquele fator (risco: viés de seleção, sistematicamente afasta setores/empresas
com reporte mais fraco) ou imputar a mediana do grupo (risco: número falso que não reflete
a empresa real). Não existe resposta certa; existe resposta **declarada por fator na
spec e idêntica no backtest e em produção** — a regra escolhida não pode divergir entre
os dois ambientes, senão o backtest valida um comportamento que produção não reproduz.

**Percentil setorial exige população mínima.** Setor com 3 empresas não tem percentil com
significado estatístico. Definir um mínimo de empresas por setor (ex. 6) abaixo do qual o
setor é agregado a uma classificação mais ampla (ex. sub-setor → setor B3) para aquele
fator, ou o fator simplesmente não pontua ali — mesma lógica da "ausência de fator
aplicável" acima, mesmo tratamento no score composto.

**Score composto:** média ponderada dos percentis de fator, com pesos explícitos, versionados e justificados. Pesos não são otimizados livremente sobre o histórico — cada configuração testada é registrada no log de experimentos, porque **cada tentativa é insumo do DSR**, exatamente como no bot.

## 8. Motor consciente da carteira

É o que separa este sistema de um screener. O relatório mensal não responde "quais as melhores ações", e sim:

> *"Dado que minha carteira atual é X e tenho R$ Y para aportar este mês, o que faz mais sentido comprar?"*

Entradas: carteira atual (ticker, quantidade, preço médio), valor do aporte, restrições do usuário.

Saídas:

- Ranking do universo elegível com score e **decomposição por fator** (por que subiu, por que caiu).
- Exposição setorial atual vs. resultante de cada sugestão.
- Concentração: peso do maior ativo, dos cinco maiores, índice de concentração.
- Alerta quando o candidato melhor ranqueado aumenta concentração já elevada — evidência de tensão, não bloqueio.
- Sugestão de aporte que respeita tetos configuráveis por ativo e por setor.
- **Nota fiscal-tributária informativa:** lembrete das regras vigentes de tributação de venda e de proventos, com a ressalva de que a regra deve ser confirmada com contador. O sistema não calcula imposto devido.

## 9. Backtest e validação

Mesmo rigor do bot, com as adaptações do domínio.

**Simulação:** rebalanceamento mensal, custo de corretagem e emolumentos B3 parametrizados, slippage por faixa de liquidez. Dividendos reinvestidos **só quando houver cobertura de proventos para 100% do universo elegível na data** (regra de consistência da Seção 5.3/6) — do contrário a simulação roda price-only, nunca com reinvestimento parcial.

**Validação:** walk-forward com janela fixa; purga entre treino e teste dimensionada pelo horizonte de avaliação; nenhuma decisão usa dado com `data_publicacao` posterior à data da decisão.

**Benchmarks obrigatórios** (todos no mesmo período e com o mesmo custo):

1. IBOV, IBrX-100, SMLL — índices
2. Carteira equal-weight do universo elegível — controla se o score adiciona algo além do filtro de liquidez
3. Carteira aleatória do universo elegível (N sorteios) — a nuvem nula
4. CDI — o custo de oportunidade real no Brasil

**Métricas:** retorno total, volatilidade, drawdown máximo, retorno/volatilidade, retorno/drawdown, turnover (proxy direto de custo), exposição setorial média.

**Teste de nulidade:** permutar a associação entre score e retorno futuro, N ≥ 100. O score real precisa ficar fora da nuvem nula. Se não ficar, o conjunto de fatores não passa — independentemente de quão bem o backtest tenha ido.

## 10. Gate de promoção

Dois eixos de amostra diferentes decidem este gate, e não podem ser confundidos entre
si (erro corrigido em 2026-08-19, ver `changes/`): **amostra transversal** (quantas
empresas líquidas existem em cada data de decisão — pequena na B3, poucas centenas) e
**número de folds temporais** (quantos períodos de validação — abundante, função de
quantos anos de histórico CVM existem, não do tamanho do universo). A margem maior
exigida pela Seção 13 se aplica ao primeiro eixo, não ao segundo — fatores têm secas
plurianuais documentadas (valor perdeu de crescimento por mais de uma década em alguns
períodos), e cada fold aqui atravessa regimes macro completos, ao contrário dos folds de
45 dias do bot (mesmo regime, teste de consistência razoável). Exigir vitória em **todos**
os folds temporais reprovaria qualquer conjunto de fatores genuíno — vira erro tipo II
por desenho. A significância estatística (critério 3) já faz esse trabalho; robustez por
fold entra como checagem de que não há fold catastrófico, não como gate primário.

Um conjunto de fatores só vai a produção se, simultaneamente:

1. Supera o equal-weight do universo em risco-ajustado em pelo menos 70% dos folds, com
   mínimo de 8 folds, e nenhum fold com degradação de drawdown além do limite definido —
   espelha a checagem de degradação que `promotion.py` já faz no bot, como teste de
   robustez, não como régua de unanimidade.
2. Universo elegível com mínimo de **N = 100 empresas** em toda data de decisão, e margem
   exigida sobre o equal-weight escalada inversamente ao tamanho do corte transversal
   naquela data — quanto menor o universo elegível, maior a margem necessária para
   passar. Este é o critério que opera o eixo de amostra transversal da Seção 13. N=100
   não é placeholder: medido rodando o filtro de liquidez da Seção 6 (mediana de
   `VOLTOT` ≥ R$500 mil/dia em janela de 63 pregões, uma classe por empresa) contra
   COTAHIST real em 9 anos amostrados de 2010 a 2025 — o universo elegível oscilou entre
   ~113 (mínimo observado, 2016, ano de recessão) e ~235 (2022); N=100 fica abaixo do pior
   ano observado, com margem, sem exigir do dado mais do que ele historicamente entregou.
   Ver `changes/2026-08-19-modulo-acoes-b3-medicao-universo.md` para a tabela completa.
3. Fica fora da nuvem nula com p < 0,05.
4. Tem DSR positivo, contabilizando **todas** as configurações de peso testadas.
5. Não concentra a vantagem inteira em um único setor ou em um único período — segmentação com piso de amostra mínima.
6. Turnover compatível com o orçamento de custo definido.

Enquanto nenhum conjunto passar, o sistema entrega apenas a **camada de evidência** (dados consolidados, rastreáveis, decompostos) — que já é útil por si e não depende de nenhum modelo funcionar.

## 11. Interface — menu Ações

Estende o mesmo dashboard descrito em `08-dashboard-e-visualizacao.md` — não é uma
aplicação separada, mesmo backend FastAPI + frontend React/Vite/TypeScript. Mas não é o
mesmo padrão do `CoinSelector` existente: aquele seleciona um **par dentro do módulo
cripto** (BTC/USDT vs. ETH/USDT); Ações é um **módulo inteiro diferente**, com seu próprio
conjunto de telas e dado próprio (specs/00, disclaimer de independência). Precisa de um
seletor de nível acima — módulo (Cripto | Ações), não par — que troca o conjunto de itens
da sidebar inteiro. Ver `08-dashboard-e-visualizacao.md`, nova seção sobre isso.

Todas as 5 telas abaixo carregam o disclaimer de `specs/00`/`CLAUDE.md` — "o sistema
ordena e evidencia, quem decide o aporte é o usuário", nunca recomendação — com destaque
visual próprio na tela 1 (Painel do aporte), que é a mais decision-facing das cinco.

### 11.1 Painel do aporte do mês (tela principal)

- Input do usuário: valor do aporte do mês (a carteira atual vem da tela "Minha carteira",
  não é redigitada aqui).
- Ranking do universo elegível (Seção 6): ticker, empresa, setor, score composto,
  variação do score desde o mês anterior.
- **Decomposição por fator** por linha do ranking (Seção 7): um indicador visual por
  família (Valor/Qualidade/Saúde financeira/Crescimento/Momentum/Dividendos/Tamanho) —
  responde "por que subiu, por que caiu", não só o número final.
- Para os candidatos no topo: exposição setorial resultante da carteira **se comprado**
  (antes/depois lado a lado), e o alerta de concentração da Seção 8 quando aplicável —
  evidência de tensão, não bloqueio (o usuário decide mesmo assim, se quiser).
- Sugestão de aporte respeitando tetos por ativo/setor (Seção 8) — quanto de cada
  candidato, não só a ordem do ranking.
- Nota fiscal-tributária informativa (Seção 8) — lembrete das regras vigentes, rodapé ou
  tooltip, nunca um cálculo de imposto devido.

### 11.2 Ficha do ativo

- Cabeçalho: ticker, razão social, CNPJ, classe (ON/PN/UNIT via `cnpj_ticker_map`,
  Seção 5.1), setor (classificação B3, Seção 7).
- Série de fundamentos com **`data_publicacao` visível ao lado de cada número, não só o
  valor** — a garantia point-in-time da Seção 5 precisa ser legível pelo usuário, não só
  correta internamente.
- Histórico de proventos (dividendos/JCP).
- Posição do ativo em cada fator ao longo do tempo — série temporal do percentil setorial
  por família de fator (Seção 7), não só o valor do mês corrente.
- Preço ajustado por eventos corporativos (Seção 5) — mesmo componente de chart do módulo
  cripto (`lightweight-charts` já é dependência do frontend, spec 08) é infraestrutura de
  UI compartilhada; o dado por trás não é.

### 11.3 Minha carteira

- Composição: ticker, quantidade, preço médio, valor atual, peso — **entrada manual**, não
  há corretora integrada (o sistema não custodia nem executa, Seção 2).
- Exposição setorial e concentração (peso do maior ativo, dos 5 maiores, índice de
  concentração — Seção 8).
- Evolução vs. os 4 benchmarks obrigatórios (Seção 9: IBOV, IBrX-100, SMLL, CDI) — mesma
  régua honesta usada na validação, agora sobre a carteira real do usuário.

### 11.4 Transparência

- Fontes (CVM/preço/macro), timestamp da última coleta, idade de cada dado — herda a
  asserção de frescor do bot (`run_daily_learning.py`, padrão já existente).
- Falhas de coleta recentes. Equivalente funcional da view "Aprendizado" do bot (spec 08),
  mas sobre proveniência de dado em vez de aprendizado de modelo.

### 11.5 Histórico de decisões

- Snapshot congelado do ranking + sugestão de cada mês (precisa ser persistido no momento
  da geração — não é recalculável depois, porque o universo elegível e os fundamentos
  point-in-time de hoje não são os mesmos de um mês atrás).
- Retorno realizado do que foi sugerido vs. do que não foi, comparado ao mês seguinte.
- Sem isso não há como auditar o próprio sistema com o tempo — é o que torna a Seção 14
  ("expectativa calibrada") verificável, não só uma afirmação de propósito.

Preparar a estrutura para múltiplos mercados desde o início, como já foi feito com o
seletor de moedas — mas sem implementar nada além da B3 agora.

## 12. Fases de entrega

| Fase | Entrega | Critério de conclusão |
|---|---|---|
| 1 | Ingestão CVM + cotações, com camada point-in-time | consulta histórica em qualquer data retorna só o que era público naquela data, com teste automatizado provando |
| 2 | Universo elegível + eventos corporativos + survivorship | universo reconstruído corretamente para datas passadas |
| 3 | Cálculo de fatores + percentis setoriais | ficha do ativo funcional; camada de evidência já entrega valor |
| 4 | Backtest + benchmarks + teste de nulidade | régua honesta operando |
| 5 | Score composto + gate de promoção | primeiro conjunto submetido ao gate (pode reprovar) |
| 6 | Motor de carteira + painel do aporte | relatório mensal completo |

As fases 1–3 entregam valor mesmo que nenhum score jamais passe no gate. Isso é intencional.

## 13. Riscos e armadilhas conhecidas

- **Vazamento por data de publicação** — mitigado pela seção 5; é o risco número um.
- **Survivorship bias** — mitigado pelo universo com data de saída.
- **Amostra pequena** — a B3 tem poucas centenas de empresas líquidas, contra milhares nos EUA. O corte transversal é estreito e a significância estatística é mais difícil. Consequência: exigir margem maior na comparação transversal (Seção 10, critério 2), não no número de folds temporais — os dois eixos de amostra são independentes e não devem ser confundidos. No eixo temporal, o histórico CVM confirmado (Seção 5.1: DFP desde 2010, ITR desde 2011, ~16 anos/~60 trimestres) sustenta o piso de 8 folds que o gate já assume — sem essa confirmação, o gate estaria pedindo um número de folds que o histórico talvez não entregasse.
- **Universo elegível não cresce de forma monotônica — é cíclico, sensível a recessão.**
  Medição direta contra COTAHIST (9 anos amostrados, 2010–2025, ver Seção 10 critério 2 e
  `changes/2026-08-19-modulo-acoes-b3-medicao-universo.md`) mostrou o universo elegível
  oscilando entre ~113 (2016, ano da recessão) e ~235 (2022) — não a trajetória de
  crescimento suave que se poderia supor a partir só do crescimento do mercado ao longo
  de 16 anos. Consequência: folds temporais em anos de recessão têm corte transversal mais
  estreito que a média, não só os anos mais antigos — o piso de N=100 empresas (critério 2)
  precisa sobreviver ao pior ano observado, não ao ano médio.
- **Concentração do mercado** — o índice brasileiro é pesado em commodities e bancos. Um fator pode parecer funcionar quando na verdade está apostando em um setor.
- **Regimes longos** — fatores passam anos sem funcionar. Um resultado ruim em 12 meses não invalida, e um bom não valida.
- **Mudança regulatória e tributária** — regras de tributação de proventos e ganho de capital mudam. O sistema informa, não calcula obrigação fiscal.
- **Overfitting de pesos** — o risco mais provável nesta frente. Mitigado pelo log de experimentos e pelo DSR.

## 14. Expectativa calibrada

Registrado na spec de propósito, para não se perder com o tempo:

Uma carteira de fatores bem construída historicamente entrega **alguns pontos percentuais ao ano acima do índice**, com longos períodos de underperformance e sem qualquer garantia de repetição. Não é um seletor de "ações que vão subir". O ganho mais confiável deste projeto é **decisão melhor informada e menos sujeita a impulso**, não retorno excepcional.

## 15. Critérios de aceite

- [ ] Toda consulta histórica respeita `data_publicacao`, com teste automatizado
- [ ] Universo histórico inclui empresas deslistadas
- [ ] Preços ajustados por todos os eventos corporativos
- [ ] Backtest com janela fixa e reprodutível entre execuções
- [ ] Quatro classes de benchmark implementadas
- [ ] Teste de nulidade com N ≥ 100
- [ ] Log de experimentos contabilizando toda configuração testada
- [ ] Camada de evidência funcional independentemente de qualquer score
- [ ] Nenhum número exibido sem fonte e data
- [ ] `changes/` documentando cada decisão de desenho
