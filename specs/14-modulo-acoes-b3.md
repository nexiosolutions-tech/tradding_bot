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
- **Peça que faltava no contrato — fonte real encontrada e verificada, ver Seção 5.4.**
  CVM identifica empresa por `CNPJ_CIA`; cotação (Seção 4.2) vem por ticker B3. Uma
  empresa pode ter múltiplas classes de ação (ON, PN, UNIT) mapeando pro mesmo CNPJ, e
  tickers mudam com incorporação/fusão/troca de nome — justamente os casos mais
  interessantes para o universo elegível (Seção 6) e para eventos corporativos (Seção 5).
  A atribuição setorial de que todo o score da Seção 7 depende também dependia deste
  mapeamento — o casamento por nome usado como substituto (73%) não falha
  aleatoriamente, vieses exatamente o tipo de empresa que mais precisa do mapa (trocou de
  nome, foi incorporada, é pequena/antiga). **Fonte confirmada**: FCA da CVM
  (`fca_cia_aberta_valor_mobiliario`) dá a identidade CNPJ↔ticker; COTAHIST dá a vigência
  real (o FCA tem campos de data que pareciam servir mas medem outra coisa — ver Seção
  5.4). Precisa existir antes da Fase 2 (universo elegível + eventos corporativos), não
  antes da Fase 1 — mas registrado aqui porque é a mesma disciplina point-in-time desta
  seção, não uma preocupação nova.
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

#### 5.3.1 `FATCOT`, `ESPECI` e o que a COTAHIST realmente dá para separar bruto de evento (2026-08-20)

Antes de desenhar o schema de preço, verificado contra o layout oficial (revisão 02,
`SeriesHistoricas_Layout.pdf`) e contra dado real — não assumido.

**`FATCOT` não é fator de ajuste corporativo — é escala de cotação.** Posições 211-217,
valores documentados `1` (cotação unitária) e `1000` (cotação por lote de mil ações,
prática histórica para papéis de baixo valor). Confirmado empiricamente, não só pelo
texto do layout: `VOLTOT/QUATOT` (preço médio real do dia, invariante a qualquer
convenção de escala) bate com `PREULT/FATCOT` tanto para `FATCOT=1000` (`FNAM11`,
2024-01-02) quanto para `FATCOT=10` — **um valor que existe no dado real mas não está
documentado em lugar nenhum do layout oficial** (só `1` e `1000` são descritos;
`SMLL11`, 2024-10-16, tem `FATCOT=10` e o preço médio bate exato com `PREULT/10`). A
armadilha real aqui: se o mesmo ticker mudar de `FATCOT` ao longo do tempo, a série bruta
salta de escala sem nenhum evento societário ter ocorrido — um filtro de liquidez ou um
cálculo de retorno engoliria isso como um movimento de preço absurdo. **Regra: todo preço
é normalizado por `FATCOT` na ingestão** (`normalize_price = raw/100/FATCOT`), antes de
qualquer outra coisa tocar o preço. Nenhum ticker do universo de ações propriamente dito
(`ESPECI` começando com ON/PN/PR/OR ou `UNT`) teve `FATCOT≠1` em 2024 — a armadilha existe
majoritariamente em fundos/ETFs (`FNAM11`, `SMLL11`), fora do escopo da Seção 6, mas a
normalização é aplicada sempre, por desenho, não condicionalmente.

**O sinal de evento societário está em `ESPECI`, não em `FATCOT`.** O campo (posições
40-49) tokeniza por espaço: classe (`ON`/`PN`/...), sufixo "ex-" opcional (sempre começa
com `E`: `ED`=ex-dividendo, `EJ`=ex-juros, `EB`=ex-bonificação, `ER`=ex-rendimento,
`ES`=ex-subscrição, `EG`=ex-grupamento, e combinações), tag de segmento opcional
(`NM`=Novo Mercado etc. — confirmado por inspeção de byte a byte: `'ON  EB  NM'` →
`['ON','EB','NM']`, não por posição fixa, porque a tag de segmento desloca onde o sufixo
aparece). **O sufixo persiste por vários pregões, não é um marcador de um dia só**
(confirmado: `ON EJ` do BBAS3 durou ~8 pregões seguidos em 2024) — a **primeira** data de
uma nova sequência de sufixo é o ex-date real; os pregões seguintes com o mesmo sufixo não
são um novo evento.

**Desdobramento não tem marcador — a COTAHIST dá "aconteceu e quando" para a maioria dos
tipos, nunca "quanto".** Achado real: `EG` (ex-grupamento, reverse split) existe na
tabela oficial; um "ex-desdobramento" (forward split) equivalente **não existe em
nenhuma linha da tabela**, documentada ou observada no dado real. Um sufixo `EX` aparece
no dado real sem estar documentado em lugar nenhum do layout oficial — capturado como
evento, tipo registrado explicitamente como "não documentado" (Seção 5.3.2 mede o que
esse rótulo esconde).

**Bonificação e grupamento quebram o nível da série sempre — confirmado, não assumido.**
Testado o efeito de preço de cada sufixo real do BBAS3 em 2024: `EB` (bonificação) caiu
**-50,57%** no dia — mecânico, mudança de quantidade de ações sem contrapartida em caixa,
descontinuidade real na série bruta. `EJ` (+0,65%) e `EDJ` (-3,53%) ficaram na faixa de
movimento de mercado normal — distribuição em caixa é um preço real, não uma quebra
artificial (o comprador de fato recebe menos valor futuro, o preço reflete isso
genuinamente; diferente de bonificação/grupamento, que só dilui/concentra sem mudar valor
econômico). **Regra: `is_level_break=True` sempre para sufixos com `B` (bonificação) ou
`G` (grupamento)**; desdobramento fica com schema pronto para receber o tipo (`ex_suffix`
aceita qualquer string), mas nenhuma linha é gerada — sem detector confiável, melhor
vazio e registrado do que adivinhado.

#### 5.3.2 `EX`: população inteira medida, não amostra (2026-08-20)

`EX` ficou como item aberto na Seção 5.3.1 — um único caso (BBAS3, -2,25%) não bastava
para decidir. Medidas **todas as 73 ocorrências reais de `EX` no universo de ações,
2010–2026** (não uma amostra): baixados os 17 anos de COTAHIST desse intervalo, cada
transição ON→...EX... da população inteira contabilizada.

**Resultado**: min=-80,96%, max=+4,86%, mediana=-2,37%. Distribuição nem uniformemente
ruído nem limpamente bimodal — 67,1% (49/73) dentro de ±5%, consistente com
ruído/distribuição em caixa normal; 20 casos entre 5% e 33%, zona ambígua; **4 casos
(5,5%) cruzam -33%**: `CEBR6`/`CEBR3`/`CEBR5` (as três classes da mesma empresa, mesmo
dia, 2021-10-18, -80,96%/-80,35%/-80,12%) e `VIVT3` (2025-04-15, -50,08%). Há um vão real
na cauda entre -22,54% (`CGAS5`, 2019-12-10) e -50,08% (`VIVT3`) — nenhum caso no meio.

**Decisão, o tratamento conservador para rótulo ambíguo**: `is_level_break` de `EX` **não
é fixo pelo sufixo** (diferente de `B`/`G`, estrutural) — é decidido **caso a caso pelo
retorno do próprio dia**, limiar `|retorno| ≥ 0,33`, escolhido dentro do vão real da
distribuição (entre -22,54% e -50,08%), não por conveniência. Implementado em
`_is_level_break(ex_suffix, pct_change)`; testado contra os dois extremos reais — BBAS3
2024-02-22 (-2,25%, não é quebra) e VIVT3 2025-04-15 (-50,08%, é quebra).

O que fica registrado, não presumido: `EX` continua com tipo não documentado no layout
oficial (não sabemos *o quê* ele marca), mas o comportamento de preço em N=73 casos reais
está medido, e a regra de classificação decorre da medição, não de uma suposição sobre o
rótulo.

**Regra de consistência (price-only vs. total-return): nunca misturar.** Ter provento dos
sobreviventes e não dos deslistados faria o retorno total ser medido de formas diferentes
em dois subgrupos do mesmo universo — erro concentrado exatamente na população que existe
para corrigir survivorship, pior que um erro uniforme. Enquanto não houver fonte de
proventos com a mesma cobertura do COTAHIST (todo ticker que já negociou, não só líquidos
atuais), o backtest roda **price-only para todo o universo**. Total-return só é permitido
quando houver provento coberto para 100% dos nomes elegíveis naquela data de decisão —
nunca parcial.

**Escopo do gap de magnitude, refinado — não é "ajuste pendente" genérico.** Dois tamanhos
diferentes, dependendo do fator (Seção 7):

- **Fatores de nível de fundamento sobre preço** (P/L, P/VP, dividend yield calculado do
  fundamento) comparam o preço de hoje com o fundamento de hoje — não atravessam a série,
  sobrevivem sem ajuste. **Não bloqueados.**
- **Fatores de série de retorno** (momentum 6-12 meses) atravessam eventos e exigem ajuste
  correto, logo exigem magnitude que a COTAHIST não tem. **Momentum especificamente fica
  bloqueado** até a fonte de magnitude existir — não "ajuste genérico pendente", um fator
  nomeado.
- A regra price-only acima e o universo elegível (Seção 6, que usa `VOLTOT`, imune a
  ajuste) **não são bloqueados** por nenhum dos dois achados desta seção.

**Fontes de magnitude candidatas, não verificadas — registradas para quando a Fase 3
(fatores) chegar em momentum**: B3 publica proventos/eventos corporativos com magnitude em
arquivos próprios (não os mesmos da COTAHIST); a CVM tem dado de proventos em alguns
formulários; desdobramento às vezes aparece no FRE (Formulário de Referência, Seção 4.1,
ainda não verificado). Nenhuma testada. **Deliberadamente não cogitada**: casar contra
fonte de terceiro não-oficial só para preencher magnitude — reintroduziria no eixo de
preço a mesma fragilidade que a propagação por CNPJ eliminou do eixo de identidade
(Seção 5.6) ao abandonar o casamento por nome.

**Implementado** (`backend/src/tradingbot/acoes/cotahist_ingestion.py`,
`price_sanity.py`): `CotahistPrice` (preço bruto normalizado por `FATCOT`) e
`CorporateEventFlag` (tipo + data + `is_level_break`, detectado por transição de
`ESPECI`) — 7 testes contra um extrato real do `COTAHIST_A2024.ZIP` (transições reais
`EB`/`EDJ` do BBAS3), incluindo o teste de sanidade de retorno implausível sugerido no
lugar do teste de desdobramento (que não é certificável só com a COTAHIST): limiar de
plausibilidade configurável (padrão 60%), retorno diário que excede o limiar sem
`CorporateEventFlag(is_level_break=True)` correspondente é sinalizado explicitamente em
vez de seguir como dado de mercado normal.

### 5.4 `cnpj_ticker_map` — fonte real encontrada, schema derivado do que ela realmente oferece (2026-08-19)

Mesma disciplina: baixar candidatos reais em vez de assumir. Verificados dois arquivos de
`dados.cvm.gov.br` além do já conhecido `cad_cia_aberta.csv` (que só tem CNPJ + nome, sem
ticker) — o Formulário Cadastral (FCA) tem um sub-arquivo dedicado a valores mobiliários:

```
https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_AAAA.zip
  → fca_cia_aberta_valor_mobiliario_AAAA.csv
```

**A ponte existe**: colunas `CNPJ_Companhia` e `Codigo_Negociacao` (ticker) na mesma
linha, mais `Data_Inicio_Negociacao`/`Data_Fim_Negociacao` — parecia resolver vigência de
graça. Baixados os arquivos de 2018 a 2022 e 2024 para testar contra casos reais
conhecidos.

**Três testes de aceite, rodados contra dado real:**

1. **Multi-classe — confirmado.** CNPJ `33.000.167/0001-01` (Petrobras) resolve para
   `PETR3` (Ações Ordinárias) e `PETR4` (Ações Preferenciais) na mesma linha de filing
   (`fca_cia_aberta_valor_mobiliario_2024.csv`).
2. **Troca de ticker por evento societário — confirmado, mas não pela fonte que se
   esperava.** CNPJ `02.800.026/0001-40`: FCA mostra `Nome_Empresarial`=KROTON
   EDUCACIONAL S.A. no filing de 2018 (`Data_Referencia=2018-01-01`) com
   `Codigo_Negociacao` **vazio**, e COGNA EDUCAÇÃO S.A. com `Codigo_Negociacao=COGN3` a
   partir do filing de 2019. A data exata da troca **não veio do FCA** — veio de baixar
   `COTAHIST_A2019.ZIP` e medir direto: `KROT3` negociou até `2019-10-10`, `COGN3` estreou
   em `2019-10-11`, mesmo CNPJ nos dois lados. `Data_Inicio_Negociacao` do FCA para esta
   linha é `2012-11-30` — a data de admissão da **classe de ação** à negociação, não a
   data de início do **código atual**. Usar esse campo como vigência do ticker teria
   atribuído `COGN3` a datas em que o código real ainda era `KROT3` — o mesmo tipo de erro
   silencioso que o `VERSAO`/`ORDEM_EXERC` da CVM (Seção 5.1) já tinha ensinado a evitar,
   só que numa fonte diferente.
3. **Reatribuição de ticker — não encontrada, registrada como risco não coberto.**
   Varridos tickers de ação regular (lote padrão, mercado à vista) nos 10 anos de COTAHIST
   já baixados (2010–2025, amostra bienal + 2019), procurando um código ausente por um
   ano amostrado e depois reaparecendo sob empresa claramente distinta. Nenhum caso
   encontrado — consistente com a prática observável da B3 de não reciclar código de
   empresa deslistada, mas **não é prova de que nunca acontece**, só que não apareceu na
   amostra. Registrado como risco não coberto pelo teste de aceite, não como "testado e
   aprovado".

**Achado adicional, não previsto: taxa de `Codigo_Negociacao` vazio no FCA tem um corte
temporal duro, não é ruído distribuído.** Medido contra o universo elegível real (filtro
de liquidez da Seção 6, todos os anos com COTAHIST já baixado):

| Ano | Universo elegível | Resolvido via FCA | % |
|---|---|---|---|
| 2010 | 159 | 0 | 0,0% |
| 2012 | 154 | 0 | 0,0% |
| 2014 | 142 | 0 | 0,0% |
| 2016 | 129 | 0 | 0,0% |
| 2018 | 151 | 117 | 77,5% |
| 2020 | 198 | 182 | 91,9% |
| 2022 | 230 | 212 | 92,2% |
| 2024 | 204 | 194 | 95,1% |
| 2025 | 198 | 186 | 93,9% |

`Codigo_Negociacao` é **zero populado em todo filing FCA até 2017 inclusive** — nem a
Petrobras (o nome mais líquido do mercado) tem o campo preenchido nesses anos, apesar do
CNPJ e da linha de "Ações Ordinárias"/"Ações Preferenciais" existirem no arquivo. Salta
para a faixa de 78–95% a partir de 2018 (CVM aparentemente passou a exigir/capturar o
campo de forma consistente naquele ano) e sobe gradualmente daí. Isso muda o significado
da lacuna: **não é 9-19% de casos difíceis espalhados pela amostra — são os primeiros 8
anos inteiros do histórico (2010-2017, metade da janela CVM confirmada na Seção 5.1) em
que a reconciliação por nome deixa de ser fallback e vira o caminho único.** Abaixo do
limiar de 95% que tornaria o gap tolerável sem mais rigor (2010-2022 inteiro fica abaixo
disso) — reconciliação por nome nesses anos precisa de auditoria manual, não só
automática, exatamente como antecipado antes de medir.

**Veredito, schema corrigido pelo que a fonte realmente permite** — não é uma fonte única
derivável, é duas fontes combinadas, cada uma no que faz bem, com uma dependência entre
elas que a primeira versão deste schema não deixava explícita:

- **Identidade (quem é o CNPJ de um ticker) vem do FCA quando disponível (a partir de
  ~2018, ~78-95% de cobertura crescente) ou de reconciliação por nome quando não (todo o
  período 2010-2017, e o resto da lacuna depois de 2018)** — mesma ressalva de viés já
  registrada: falha mais em empresa pequena/renomeada/incorporada, exatamente o perfil que
  mais precisa do mapa. Entradas marcadas `fonte='FCA'` ou `fonte='reconciliacao_nome'`.
- **Vigência (datas de início/fim de um código específico) vem do COTAHIST — mas só como
  fonte das *bordas*, nunca da *costura*.** Primeira e última data de pregão de um ticker
  no arquivo anual dão o intervalo em que aquele código negociou; **quem garante que dois
  intervalos consecutivos (ex. `KROT3` até 10/10/2019, `COGN3` a partir de 11/10/2019)
  pertencem ao mesmo CNPJ é o FCA (ou a reconciliação por nome), nunca a COTAHIST
  sozinha.** A COTAHIST não sabe se um código mudou de dono — dois códigos com pregão
  contíguo parecem idênticos do ponto de vista dela, tenham trocado de dono ou não. Se o
  desenho derivasse tudo da COTAHIST, reintroduziria exatamente o risco de reatribuição
  que o teste 3 não conseguiu descartar (só não encontrou evidência, o que é diferente de
  provar ausência).
- **Tolerância de gap contra falso fim de vigência por iliquidez.** Papel pouco líquido
  pode passar semanas sem pregão sem ter saído da empresa — se `data_fim_vigencia` fosse
  "a última data de pregão" sem tolerância, uma pausa de negociação fecharia a vigência e
  a retomada abriria uma nova, fragmentando a identidade de um ticker que nunca deixou de
  pertencer ao mesmo CNPJ. Morde justamente os papéis pequenos, a mesma população do vale
  setorial de 2016 (Seção 7). Regra: só fecha vigência após ausência de pregão por mais de
  180 dias corridos (mesma ordem de grandeza da janela de liquidez de 63 pregões ≈ 3 meses
  da Seção 6, com margem). **Fechamento de vigência "de verdade" é cruzado com um evento
  de deslistagem/cancelamento da CVM quando possível** (`cad_cia_aberta.csv`, campos `SIT`,
  `DT_INI_SIT`, `MOTIVO_CANCEL` — já usados na Seção 5.1) — silêncio de pregão sozinho é
  evidência fraca de fim de vigência, cancelamento registrado na CVM é evidência forte.

```
cnpj_ticker_map:
  cnpj                    -- FCA.CNPJ_Companhia (ou reconciliação por nome)
  ticker                  -- FCA.Codigo_Negociacao (ou reconciliação por nome)
  tipo                    -- ON/PN/UNIT, de FCA.Valor_Mobiliario/Sigla_Classe_Acao_Preferencial
  data_inicio_vigencia    -- COTAHIST: primeira data de pregão deste ticker (borda)
  data_fim_vigencia       -- COTAHIST: última data de pregão + tolerância de 180 dias sem
                              pregão, cruzado com cad_cia_aberta.SIT/DT_INI_SIT quando
                              houver cancelamento CVM correspondente (NULL = ainda vigente)
  fonte                   -- 'FCA' | 'reconciliacao_nome'  (identidade, não vigência)
  data_coleta
```

Consulta as-of (inalterada da proposta original): `ticker = X AND data_inicio_vigencia <=
data_decisao AND (data_fim_vigencia IS NULL OR data_fim_vigencia > data_decisao)` — devolve
o CNPJ dono do ticker naquela data. Append-only: reatribuição ou troca de código fecha a
vigência antiga (`UPDATE` só em `data_fim_vigencia`, nunca substitui a linha) e abre uma
nova.

**Decisão de saída, declarada**: ticker que passa o filtro de liquidez da Seção 6 mas não
resolve para nenhum CNPJ (nem via FCA nem via reconciliação por nome) **não entra no
universo elegível daquela data** — e essa exclusão é **contada explicitamente** (quantos
tickers, quais, em qual data), nunca subtraída em silêncio do denominador. Mesmo
tratamento já usado para histórico insuficiente (Seção 6), dado faltante de fator (Seção
7) e perda de liquidez (Seção 8, segundo canal de survivorship): omitido e registrado,
nunca descartado sem rastro.

### 5.5 Auditoria da reconciliação por nome (2010–2017): pior do que a cobertura sozinha sugeria

A Seção 5.4 tratou a reconciliação por nome como fallback com viés conhecido mas direção
desconhecida. Auditoria manual contra o universo elegível de `2016-12-29` (129 tickers,
94 "casados" = 72,9%) respondeu as duas perguntas em aberto — e a resposta piora o
quadro, não melhora.

**Os 27% não casados não são cauda ilíquida — incluem os nomes mais líquidos do
universo.** `ITUB4` (Itaú Unibanco, 2º mais líquido de todo o universo, R$450
milhões/dia), `BBAS3` (Banco do Brasil, 3º mais líquido, R$225 milhões/dia) e `BVMF3`
(a própria bolsa) ficaram sem match. Mediana de liquidez dos não casados (R$13,1
milhões/dia) ficou próxima da mediana dos casados (R$15,2 milhões/dia) — nenhuma
separação por porte. Causa identificada, não misteriosa: o normalizador usado stripa
"BRASIL" como palavra genérica de nome social (correto para a maioria dos casos), mas
`BBAS3` tem `NOMRES="BRASIL"` — a própria abreviação da B3 para o ticker é a palavra que
o normalizador descarta, matando o único token útil. `ITUB4` tem `NOMRES="ITAUUNIBANCO"`
(sem espaço, truncado no campo de 12 caracteres da COTAHIST) contra tokens separados
"ITAÚ"/"UNIBANCO" no cadastro CVM — nunca bate por token inteiro. **Um heurístico mais
cuidadoso resolveria esses casos específicos trivialmente** — mas isso é exatamente o
ponto: a heurística simples usada para medir a cobertura não é segura para produção sem
revisão manual, e não há evidência de que os casos remanescentes sejam todos assim
simples de corrigir.

**Pior: uma fração real dos 73% "casados" está errada, não só incompleta.** Auditados os
19 matches de confiança baixa (score 0,5 — um único token genérico bateu, não o nome
inteiro): **10 de 19 (53%) apontam para a empresa errada**, incluindo seis colisões
diferentes na mesma palavra genérica "PART" (de "Participações") que empurraram
`ESTC3` (Estácio, educação), `TIMP3` (TIM Participações, telecom), `RAPT4` (Randon,
autopeças), `QGEP3` (petróleo), `JHSF3` e `TPIS3` (Triunfo) todos para o CNPJ de
`CYRELA BRAZIL REALTY` (construção civil) — nenhuma relação real entre as empresas.
`GOAU4` (Gerdau Metalúrgica) foi atribuído ao CNPJ de `GERDAU S.A.` — holding e
subsidiária são entidades e CNPJs diferentes. Contando as 84 identificações corretas
(75 de alta confiança + 9 de baixa confiança auditadas como certas) sobre os 129
elegíveis: **precisão real ≈ 65%, não 73%** — e o erro fica **invisível** no schema atual
(`fonte='reconciliacao_nome'` não distingue match certo de errado), diferente do
não-match, que pelo menos é visível e contado pela decisão de saída da Seção 5.4.

**Conclusão da primeira rodada**: a era 2010–2017 não tem, com reconciliação por nome,
identidade confiável o suficiente para contar como evidência de promoção — a decisão
inicial foi cortar o histórico avaliável em 2018. A Seção 5.6 revisita essa decisão com
um método melhor e um critério de dois pisos, e a conclusão muda de forma para alguns anos.

### 5.6 Propagação por CNPJ (era confiável → era antiga) e o critério de dois pisos

A reconciliação por nome não é o único jeito de resolver identidade pré-2018. A partir de
2018 o FCA já resolve CNPJ↔ticker diretamente (Seção 5.4); boa parte das empresas que
negociavam antes de 2018 continuou negociando depois, sob o **mesmo código de ticker** —
então dá para propagar essa identidade **para trás no tempo pelo próprio CNPJ**, sem
reconciliar nome nenhum. Zero adivinhação: é dado já verificado da era confiável aplicado
a um ticker que não mudou.

**Método**: dicionário `ticker → CNPJ` construído a partir de `Codigo_Negociacao` em
qualquer ano FCA 2018–2025 (763 tickers distintos). Aplicado diretamente aos tickers
elegíveis de 2010–2016 (Seção 6). Estendido com propagação por **raiz de 4 letras** do
ticker (mesma raiz = mesma empresa, classes de ação diferentes — ex. `VALE5`/`VALE3`,
`SUZB5`/`SUZB3` — sem misturar empresas distintas: `GOAU4`/`GGBR4`, raízes diferentes,
seguem separadas corretamente).

Tentativa adicional considerada e descartada por não agregar nada: usar um "código
interno" que o próprio FCA às vezes reporta em vez do ticker real (ex. CSN aparece como
`Codigo_Negociacao="4030"` em **todo** ano 2018–2025, nunca como `CSNA3`) como segunda
chave de junção, derivando o de-para de dentro do próprio FCA quando o mesmo CNPJ mostra
as duas formas em anos diferentes. Achado: os únicos 5 pares assim derivados
(`9989→RPMG3`, `90212→MLAS3`, `0000→MTRE3`, `21130→TRIS3`, `23574→MEAL3`) já eram
resolvidos pela propagação direta — resultado nulo, não um bug. Para CSN e outros casos
onde o código interno é persistente (nunca coexiste com o ticker real em nenhum ano
observado), não há de-para derivável sem conhecimento externo — ficam de fora, por
desenho (nenhuma adivinhação).

**Resultado da propagação, cobertura por ano:**

| Ano | Cobertura (antes, Seção 5.4) | Cobertura (pós-propagação) |
|---|---|---|
| 2010 | 0,0% | 69,8% |
| 2012 | 0,0% | 79,9% |
| 2014 | 0,0% | 83,1% |
| 2016 | 0,0% | 90,7% |

**Auditoria de precisão (não só cobertura) nos quatro anos — 469 identificações
inspecionadas manualmente, zero erros encontrados em todas.** Diferente da reconciliação
por nome (Seção 5.5, ~65% de precisão real), propagação por identidade verificada não tem
o mecanismo de colisão em token genérico — corrigiu inclusive vários dos falsos positivos
da rodada anterior (`ESTC3→YDUQS`, não mais Cyrela; `QGEP3→Enauta`; `TIMP3→TIM
Participações`).

**O piso original (95% de cobertura, um número só) media a coisa errada.** Ele foi
pré-registrado para proteger contra o risco real — identidade **errada**, que corrompe o
demeaning setorial (Seção 7) em silêncio. A auditoria mostrou que esse risco zerou com
propagação; o que sobra é ausência **contável**, natureza completamente diferente (a
mesma exclusão declarada já usada em toda a spec — Seção 6, 7, 8). Substituído por dois
critérios, cada um controlando o erro certo:

1. **Precisão de identidade ≥ 98%**, auditada manualmente sobre o universo líquido do ano
   — gate rígido, sem negociação, porque é o erro que não deixa rastro.
2. **Cobertura ≥ 85%** sobre o universo líquido do ano — gate de amostra, mais frouxo,
   porque ticker não resolvido vira exclusão contável (Seção 8), não contaminação.

Um ano só é avaliável (conta fold no gate de promoção, Seção 10) se passar **nos dois**.

**Resultado, aplicando o critério aos quatro anos medidos:**

| Ano | Cobertura | Precisão | ≥85% cobertura? | ≥98% precisão? | Avaliável? |
|---|---|---|---|---|---|
| 2010 | 69,8% | 100% (0/111) | Não | Sim | **Não** |
| 2012 | 79,9% | 100% (0/123) | Não | Sim | **Não** |
| 2014 | 83,1% | 100% (0/118) | Não (perto) | Sim | **Não** |
| 2016 | 90,7% | 100% (0/117) | Sim | Sim | **Sim** |

**Segunda rodada: 2015 e 2017 medidos com o mesmo par de métricas, pré-registro
reafirmado sem alteração antes de rodar.**

| Ano | Cobertura | Precisão | ≥85% cobertura? | ≥98% precisão? | Avaliável? |
|---|---|---|---|---|---|
| 2010 | 69,8% | 100% (0/111) | Não | Sim | **Não** |
| 2012 | 79,9% | 100% (0/123) | Não | Sim | **Não** |
| 2014 | 83,1% | 100% (0/118) | Não (perto) | Sim | **Não** |
| 2015 | 85,5% | 100% (0/106) | Sim (caso-limite) | Sim | **Sim** |
| 2016 | 90,7% | 100% (0/117) | Sim | Sim | **Sim** |
| 2017 | 90,1% | 100% (0/137) | Sim | Sim | **Sim** |

2015 caiu exatamente em cima da linha, como previsto antes de medir — e passou sem
precisar de tolerância: 85,5% ≥ 85%, precisão 100% igual aos outros anos. A régua não foi
testada para ceder (o cenário inverso — 84% de cobertura reprovando um ano com precisão
perfeita — não ocorreu, mas o critério estava pronto para aplicá-lo se ocorresse).

**Fronteira fecha em 2015–2026, contígua.** 2010, 2012 e 2014 ficam de fora só por
cobertura (a precisão foi 100% em todos os seis anos medidos — nenhum ano tem problema de
identidade errada, só de ausência). 2011 e 2013 não foram medidos — dado o padrão
crescente e monotônico observado (69,8% → 79,9% → 83,1% → 85,5% → 90,1%/90,7%, com 2014
abaixo do piso e 2015 acima), é improvável que mudem o formato da fronteira, mas não foram
confirmados e não estão incluídos na era avaliável.

**Consequência para a tensão de amostra (Seção 10/13): a era avaliável passa de ~8-9 anos
(só 2018+) para ~11-12 anos (2015-2026)** — folds temporais recuperados sem baixar o
padrão de precisão em nenhum momento. Ainda não é garantia de atingir o piso de 8 folds
dependendo da duração exata de cada fold (Seção 5.1), mas a tensão registrada na Seção 10
e 13 relaxa substancialmente.

### 5.7 `cnpj_ticker_map` como módulo de código (2026-08-20)

As Seções 5.4-5.6 acima descreviam o desenho e a medição. Implementado como código
(`backend/src/tradingbot/acoes/cnpj_ticker_map.py`) pela mesma razão que valeu para
COTAHIST/preço: a Seção 6 (universo elegível) é o primeiro ponto onde as três fundações
point-in-time (identidade, publicação, preço) se encontram, e assumir que o
`cnpj_ticker_map` "existe" sem código sob os pés repete o erro que a lição do FATCOT já
tinha ensinado a evitar.

**Resolução de identidade em três níveis de confiança**, cada um só resolve se o
resultado for inequívoco (mais de um CNPJ candidato = não resolvido, nunca "escolhe o
primeiro"):

1. `fca` — `Codigo_Negociacao` direto de qualquer ano FCA 2018-2025.
2. `raiz_propagacao` — raiz de 4 letras do ticker (Seção 5.6).
3. `reconciliacao_nome` — nome histórico (`Nome_Empresarial`) contra o `nomres` truncado
   da COTAHIST, exigindo que todo token significativo da consulta seja um token exato do
   nome histórico (sem crédito parcial em token genérico).

**Vigência sempre derivada das bordas da COTAHIST** (primeira/última data de pregão do
ticker), nunca do FCA — cujas datas medem admissão da classe de ação, não vigência do
código (achado da Seção 5.6, caso `COGN3`). Tolerância de 180 dias sem pregão antes de
fechar vigência (`data_fim_vigencia = None` = ainda vigente), para não fragmentar
identidade de papel ilíquido por uma pausa comum de negociação.

**Auditoria de precisão sobrevivendo à passagem para código — achado novo desta
rodada.** Rodando `resolve_identity` contra os universos elegíveis EXATOS dos seis anos
já auditados (712 identificações, Seção 5.6), dos 50 matches de `reconciliacao_nome`
encontrados, **4 eram falsos positivos** por colisão de token de nome com empresa não
relacionada — confirmados um a um contra o registro CVM completo (`cad_cia_aberta.csv`):

| Ticker | Token da consulta | CNPJ errado que resolvia | Empresa real (CNPJ diferente) |
|---|---|---|---|
| `BRTO3` (Brasil Telecom) | `TELEC` | Telebrás | Ambas abreviam "telecomunicações" da mesma forma |
| `CCIM3` (CC Desenv. Imob.) | `IMOB` | BRPR56 Securitizadora | Abreviação genérica de "imobiliário" |
| `CZRS4` (Banco Cruzeiro do Sul, falido) | `CRUZEIRO` | Cruzeiro do Sul Educacional | CNPJs diferentes confirmados no registro CVM |
| `RAIA3` (Droga Raia, pré-fusão 2010) | `RAIA` | CNPJ pós-fusão da RaiaDrogasil | Nome consolidado pós-evento vazando para ticker pré-evento |

Os quatro tokens entraram em `_GENERIC_NAME_TOKENS` — não por serem gramaticalmente
genéricos como `PART`/`HOLDING` (a causa raiz original do erro de 53%, Seção 5.5), mas
por colisão empírica comprovada, mesmo tratamento preventivo. Todos os outros 13 casos de
token único (`KROTON`, `CONTAX`, `TEGMA`, `PLASCAR`, `DROGASIL`, `MARISA`, `PACTUAL`,
`PROPERT`, `TIETE`, `TREVISA`, `SMILES`, `AMBEV`, `PPLA`) foram confirmados corretos
individualmente contra o registro CVM ou fonte FCA — incluindo `PPLA11`, que parecia
suspeito por não aparecer em `cad_cia_aberta.csv` (é `PPLA Participations Ltd`, emissor
estrangeiro de BDR, fora do escopo desse registro doméstico, não um erro).

**Teste de regressão**: os matches `fca`+`raiz_propagacao` dos seis anos auditados
(712 originalmente) rodam a 713 no código — a diferença é `DMMO3`/2017, que agora resolve
via `raiz_propagacao` (raiz `DMMO`, CNPJ único da FCA) e não resolvia na auditoria
original por essa não ter carregado exatamente o mesmo conjunto de anos FCA. Não é
regressão (o caminho `raiz_propagacao` carrega sua própria garantia de 100% de precisão,
Seção 5.6) — é uma identificação nova, isolada e explicada no teste, não escondida no
total.

**Teste de aceite fechado**: `KROT3` (vigente até 2019-10-10, resolvido por
`reconciliacao_nome` contra o nome histórico `KROTON`) e `COGN3` (vigente a partir de
2019-10-11) resolvem para o mesmo CNPJ (`02.800.026/0001-40`, Cogna Educação) via
`get_cnpj_as_of`, sem sobreposição e sem vão na fronteira — mesma convenção de fronteira
inclusiva-inclusiva de `get_filing_as_of` (Seção 5.2). Ticker sem CNPJ resolvido
(`UnresolvedTicker`) confirmado contável, não silencioso.

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

**Normalização: percentil no universo inteiro, com neutralização (demeaning) setorial —
não percentil dentro do setor.** Percentil-dentro-do-setor degrada catastroficamente com
bucket pequeno (percentil sobre 4 empresas não é estatística, é ordenação de quatro
pontos) — e o achado da subseção abaixo mostra que bucket pequeno não é caso raro na B3,
é comum. A correção padrão em quant: para cada métrica, calcular o valor **demeaned**
(valor da empresa menos a média do setor de nível 1 B3 na data), depois tomar o percentil
dessa série demeaned sobre o **universo elegível inteiro**, não sobre o setor. A diferença
é o que cada forma precisa estimar — demeaning só precisa da **média** do setor
(razoável com 3–4 nomes), percentil-dentro-do-setor precisa da **distribuição inteira**
(não razoável com poucos nomes). Isso mantém o objetivo original — não comparar P/L de
banco com o de mineradora — sem exigir a população que a B3 não tem. Setor com pelo menos
3 empresas estima a própria média; abaixo disso, a empresa entra num bucket "outros" (sem
neutralização setorial específica) em vez de ser descartada. Setorização via
classificação B3, versionada.

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

**Por que a normalização acima existe: o piso setorial é achado real, não hipotético —
mas dois números distintos, não confundir.** Medido contra dado real
(`changes/2026-08-19-modulo-acoes-b3-secao-8-e-piso-setorial.md`): no vale de 2016 (113
empresas passando o filtro de liquidez da Seção 6), agrupando por setor via `SETOR_ATIV`
da CVM e mesmo depois de colapsar holdings no setor-base (aproximação da classificação
B3), 22 de 27 setores ficaram abaixo de uma população de 6 — só Bancos, Metalurgia,
Energia Elétrica, Construção Civil e Comércio sobreviveram.

- **O que esse número decide:** a direção e a magnitude qualitativa — setor pequeno é
  comum, não exceção, na B3. Isso justifica a mudança de arquitetura acima
  (percentil-no-universo + demeaning em vez de percentil-dentro-do-setor), que degrada
  suavemente com setor pequeno em vez de quebrar.
- **O que esse número NÃO decide:** nenhum piso calibrado. `SETOR_ATIV` da CVM é mais
  granular que a classificação B3 real que a spec assume para produção — o 22/27 usa a
  taxonomia errada. E o casamento por nome (73%, sem `cnpj_ticker_map`) não é uma falha
  aleatória: empresa que trocou de nome, foi incorporada ou é pequena e antiga tem mais
  chance de não casar — exatamente o perfil que preenche setor pequeno. O 22/27 pode estar
  sub ou superestimado, e a direção do viés não é conhecida. O piso de 3 nomes para
  estimar média (acima) é escolha de desenho independente deste número, não calibrada por
  ele — revisar quando a classificação B3 real e o `cnpj_ticker_map` existirem.

**Score composto:** média ponderada dos percentis de fator, com pesos explícitos, versionados e justificados. Pesos não são otimizados livremente sobre o histórico — cada configuração testada é registrada no log de experimentos, porque **cada tentativa é insumo do DSR**, exatamente como no bot.

## 8. Motor consciente da carteira

É o que separa este sistema de um screener. O relatório mensal não responde "quais as melhores ações", e sim:

> *"Dado que minha carteira atual é X e tenho R$ Y para aportar este mês, o que faz mais sentido comprar?"*

**Regra de saída por perda de liquidez (o item mais importante desta seção — trate antes
do resto).** O filtro de liquidez da Seção 6 é um segundo canal de survivorship,
independente da tabela de deslistagem: o universo elegível encolhe **na crise**, porque o
volume seca, não porque a empresa deslistou (medido: o vale de 113 empresas em 2016 é
exatamente esse efeito, `changes/2026-08-19-modulo-acoes-b3-medicao-universo.md`). Se o
backtest simplesmente para de considerar uma posição em carteira no mês em que ela cai
abaixo do limiar de liquidez, a posição desaparece do sample **no momento em que daria o
pior resultado** — viés otimista, silencioso, e não corrigido por nada que já está na
spec (a tabela de survivorship cobre deslistagem, não perda de liquidez).

Regra: quando um ativo em carteira sai do universo elegível, o motor **modela a saída**,
nunca deixa a posição desaparecer —

- **No backtest:** a posição é liquidada na simulação com slippage compatível com a
  iliquidez que causou a exclusão (não o slippage "normal" por faixa de liquidez da Seção
  9 — a saída acontece justamente quando a faixa piorou), no mês em que o ativo cruzou o
  limiar. O retorno dessa liquidação entra no cálculo de performance normalmente.
- **Em produção:** o motor de carteira sinaliza a perda de elegibilidade como um alerta
  de saída ao lado das sugestões de aporte — não uma ordem automática (a Seção 2 já exclui
  execução automática deste módulo), mas informação que hoje nenhuma tela do menu Ações
  cobre.
- **A regra é declarada e idêntica nos dois ambientes** — mesmo princípio já aplicado à
  regra de dado faltante da Seção 7: o backtest só valida um comportamento que a produção
  de fato reproduz se a lógica de saída for a mesma nos dois lugares.

**Entradas**: carteira atual (ticker, quantidade, preço médio), valor do aporte, e
restrições do usuário — exclusões manuais (ticker ou setor que o usuário não quer
aumentar, por razão fora do modelo), teto de peso máximo por ativo e por setor
(configurável, com um default conservador versionado), valor mínimo de posição (evita
sugerir um aporte residual que não compensa o custo de corretagem).

**Mecanismo de sugestão: regra gulosa determinística sobre o ranking da Seção 7, não
otimização de portfólio com função-objetivo própria.** Escolha deliberada — o sistema
**ordena e evidencia** (Seção 1), a decisão é do usuário; um otimizador com função de
utilidade embutida decidiria por trás de uma caixa-preta, o oposto do princípio de
auditabilidade que rege toda a spec. O algoritmo:

1. Percorre o ranking da Seção 7, do maior score para o menor.
2. Para cada candidato, verifica se alocar a ele o quanto falta para não deixar dinheiro
   parado (respeitando o teto por ativo e por setor, considerando a posição já existente
   + o aporte acumulado até aqui) violaria algum teto. Se violar, pula para o próximo
   candidato — não reduz a alocação para caber, porque alocação parcial arbitrária não é
   mais auditável que pular.
3. Repete até o aporte se esgotar ou não sobrar candidato elegível dentro dos tetos.
4. **Sobra não alocável é reportada explicitamente**, nunca forçada em um ativo que
   violaria teto — "R$ X não alocados porque os tetos configurados foram atingidos em
   todos os candidatos restantes" é uma saída válida, não uma falha do algoritmo.
5. **Lote padrão (100 ações) vs. mercado fracionário**: se o valor a alocar num candidato
   não fecha um lote padrão ao preço atual, a sugestão usa o mercado fracionário
   (`TPMERC=020` na tabela da COTAHIST, confirmado no layout oficial — distinto de
   `TPMERC=010`/mercado à vista, que é o que a Seção 6 usa para o filtro de liquidez; a
   sugestão de compra fracionária do mesmo papel não é impedida por isso). Regra
   declarada e idêntica no backtest e em produção, mesmo princípio já aplicado à regra de
   dado faltante (Seção 7) e à regra de saída por liquidez (acima).

Esta é a mesma disciplina de "regra declarada, não implícita" já aplicada em toda a spec
— o algoritmo é determinístico e auditável precisamente para que a decomposição por fator
de cada sugestão (abaixo) seja rastreável até uma regra escrita, não até um comportamento
emergente de otimização.

**Restrição estrutural, não apenas de UI**: este motor nunca envia ordem — Seção 2 já
exclui execução automática deste módulo por completo, e este mecanismo produz apenas a
lista de sugestões descrita abaixo, nunca uma ação executada.

Saídas:

- Ranking do universo elegível com score e **decomposição por fator** (por que subiu, por que caiu).
- Exposição setorial atual vs. resultante de cada sugestão.
- Concentração: peso do maior ativo, dos cinco maiores, índice de concentração.
- Alerta quando o candidato melhor ranqueado aumenta concentração já elevada — evidência de tensão, não bloqueio.
- **Alerta de perda de liquidez** para posições em carteira que caíram do universo elegível (ver regra de saída acima).
- Sugestão de aporte (mecanismo acima), com o valor não alocado explícito quando os tetos esgotam os candidatos elegíveis antes do aporte.
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

**Métricas:** retorno total, volatilidade, drawdown máximo, retorno/volatilidade, retorno/drawdown, turnover (proxy direto de custo), exposição setorial média. **Cada fold reporta também o tamanho do universo elegível (N transversal, mínimo/mediano/máximo no período do fold)** — sem isso não dá para o gate (Seção 10) distinguir um fold com poder estatístico real de um fold num vale de liquidez.

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
   robustez, não como régua de unanimidade. **Folds contam apenas se o N transversal
   mediano do período (Seção 9) atingir o mínimo definido (mesmo piso do critério 2)** —
   fold inteiro num vale de liquidez não entra na contagem de 70%, em vez de contar como
   evidência equivalente a um fold de pico. Fecha a lacuna registrada na Seção 13
   (folds de períodos diferentes não têm o mesmo poder estatístico) com um critério
   verificável em vez de ponderação nova. **Folds contam apenas se caírem inteiramente num
   ano avaliável — precisão de identidade ≥98% e cobertura ≥85%, auditado por ano (Seção
   5.6), não um corte único em 2018.** Medido até aqui: **2015 a 2026, contíguo**
   (Seção 5.6 — 2015/2016/2017 auditados a 100% de precisão, cobertura 85,5%/90,7%/90,1%;
   2018+ já confirmado na Seção 5.4). 2010, 2012 e 2014 ficam de fora por cobertura
   insuficiente (precisão foi 100% nos seis anos medidos — não é problema de identidade
   errada, é ausência contável). 2011 e 2013 não foram medidos, improvável que mudem a
   fronteira dado o padrão monotônico observado. Folds fora da era avaliável podem ser
   computados e exibidos como contexto, nunca contados no numerador ou denominador dos
   70%. **Isso pode reduzir os folds contáveis abaixo do piso de 8** — tensão que relaxa conforme mais anos
   (2015, 2017 candidatos) forem medidos e passarem nos dois pisos (ver Seção 5.6 e Seção 13).
2. Universo elegível com mínimo de **N = 100 empresas** em toda data de decisão, e margem
   exigida sobre o equal-weight escalada inversamente ao tamanho do corte transversal
   naquela data — quanto menor o universo elegível, maior a margem necessária para
   passar. Este é o critério que opera o eixo de amostra transversal da Seção 13.
   **N=100 é guarda contra degradação futura, não filtro calibrado para reprovar o
   histórico atual** — o mínimo observado ao rodar o filtro de liquidez da Seção 6 contra
   COTAHIST real (9 anos amostrados, 2010–2025) foi ~113 (2016, ano de recessão), acima de
   100 em todos os anos testados; por construção este critério nunca reprova nada no
   histórico medido até aqui, e isso é esperado, não um sinal de que o critério é
   desnecessário — ele existe para pegar uma degradação que ainda não aconteceu. **O
   critério que de fato morde é o 5** (piso de amostra mínima por segmento): a mesma
   medição, desagregada por setor no vale de 2016, achou 22 de 27 setores abaixo do
   mínimo de população da Seção 7 — o total de 113 escondia essa fragmentação inteira.
   Ver `changes/2026-08-19-modulo-acoes-b3-medicao-universo.md` e
   `changes/2026-08-19-modulo-acoes-b3-secao-8-e-piso-setorial.md`.
3. Fica fora da nuvem nula com p < 0,05.
4. Tem DSR positivo, contabilizando **todas** as configurações de peso testadas.
5. Não concentra a vantagem inteira em um único setor ou em um único período — segmentação com piso de amostra mínima. Ver nota do critério 2: este é o critério com poder real de reprovação nesta frente, não o 2.
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
| 1 | Ingestão CVM + cotações, com camada point-in-time | consulta histórica em qualquer data retorna só o que era público naquela data, com teste automatizado provando — **índice mestre CVM + consulta as-of + preço bruto COTAHIST normalizado + eventos societários tipo/data + `cnpj_ticker_map` (identidade CNPJ↔ticker com vigência e consulta as-of) implementados e testados contra dado real, 2026-08-20** (`backend/src/tradingbot/acoes/`); ingestão de itens financeiros genéricos (todos os tipos de demonstração, todas as empresas) e magnitude de eventos societários (bloqueia só momentum, Seção 5.3.1) seguem pendentes — as três fundações point-in-time (identidade, publicação, preço) têm chão de código sob os pés para a Seção 6 (Fase 2) |
| 2 | Universo elegível + eventos corporativos + survivorship | universo reconstruído corretamente para datas passadas |
| 3 | Cálculo de fatores + percentis setoriais | ficha do ativo funcional; camada de evidência já entrega valor |
| 4 | Backtest + benchmarks + teste de nulidade | régua honesta operando |
| 5 | Score composto + gate de promoção | primeiro conjunto submetido ao gate (pode reprovar) |
| 6 | Motor de carteira + painel do aporte | relatório mensal completo |

As fases 1–3 entregam valor mesmo que nenhum score jamais passe no gate. Isso é intencional.

## 13. Riscos e armadilhas conhecidas

- **Vazamento por data de publicação** — mitigado pela seção 5; é o risco número um.
- **Survivorship bias tem dois canais, não um.** O universo com data de saída (COTAHIST,
  Seção 5.3) mitiga deslistagem. Mas o filtro de liquidez da Seção 6 é um **segundo canal
  independente**: um ativo em carteira pode cair abaixo do limiar de liquidez sem
  deslistar, e simplesmente desaparecer do sample no mês de pior resultado se o motor não
  modelar a saída explicitamente. Mitigado pela regra de saída da Seção 8 (backtest
  liquida a posição com slippage compatível com a iliquidez, nunca a remove do sample sem
  registrar o resultado).
- **Amostra pequena** — a B3 tem poucas centenas de empresas líquidas, contra milhares nos EUA. O corte transversal é estreito e a significância estatística é mais difícil. Consequência: exigir margem maior na comparação transversal (Seção 10, critério 2), não no número de folds temporais — os dois eixos de amostra são independentes e não devem ser confundidos. No eixo temporal, o histórico CVM confirmado (Seção 5.1: DFP desde 2010, ITR desde 2011, ~16 anos/~60 trimestres) sustentava o piso de 8 folds que o gate assume — **mas isso pressupunha os 16 anos inteiros como igualmente utilizáveis, o que o achado de duas eras abaixo corrige.**
- **Qualidade de identidade varia por ano, não é um corte único em 2018.** Reconciliação
  por nome (Seção 5.5) tinha precisão real ≈65% (27% sem match, incluindo os nomes mais
  líquidos do universo — Itaú Unibanco, Banco do Brasil, a própria bolsa — e 53% dos
  matches de baixa confiança errados). Propagação por CNPJ da era confiável (Seção 5.6)
  resolveu esse risco — **100% de precisão auditada em 712 identificações, 2010 a 2017,
  zero erros em qualquer ano** — restando só um problema de cobertura, não de identidade
  errada. Aplicando os dois pisos declarados (precisão ≥98%, cobertura ≥85%, por ano):
  **a era avaliável fecha em 2015–2026, contígua** — 2015 (85,5%, caso-limite avaliado
  pela regra sem ceder), 2016 (90,7%) e 2017 (90,1%) entram, junto com 2018 em diante;
  2010, 2012 e 2014 ficam de fora só por cobertura (69,8%/79,9%/83,1%, todos com 100% de
  precisão). 2011 e 2013 não medidos, improvável que mudem a fronteira dado o padrão
  monotônico. A amostra de folds temporais do gate de promoção (Seção 10, critério 1)
  passa de ~8-9 anos (só 2018+) para ~11-12 anos — recuperada sem ceder o piso de
  precisão em nenhum momento, inclusive no caso-limite de 2015. Dimensionamento final
  (se ~11-12 anos bastam para o piso de 8 folds, dependendo da duração exata de cada
  fold) segue pendente para o desenho detalhado da Fase 3.
- **Universo elegível não cresce de forma monotônica — é cíclico, sensível a recessão.**
  Medição direta contra COTAHIST (9 anos amostrados, 2010–2025, ver Seção 10 critério 2 e
  `changes/2026-08-19-modulo-acoes-b3-medicao-universo.md`) mostrou o universo elegível
  oscilando entre ~113 (2016, ano da recessão) e ~235 (2022) — não a trajetória de
  crescimento suave que se poderia supor a partir só do crescimento do mercado ao longo
  de 16 anos. Consequência: folds temporais em anos de recessão têm corte transversal mais
  estreito que a média, não só os anos mais antigos — o piso de N=100 empresas (critério 2)
  precisa sobreviver ao pior ano observado, não ao ano médio.
- **Setor pequeno é comum na B3, não exceção — por isso a normalização da Seção 7 não usa
  percentil-dentro-do-setor.** Desagregando o vale de 2016 por setor
  (`changes/2026-08-19-modulo-acoes-b3-secao-8-e-piso-setorial.md`), 22 de 27 setores
  ficaram abaixo de uma população de 6 usando a taxonomia CVM como proxy — o total de 113
  escondia essa fragmentação por completo. Esse número (taxonomia errada, casamento por
  nome enviesado) não calibra nenhum parâmetro, mas a direção decidiu a arquitetura: a
  Seção 7 normaliza por percentil-no-universo com demeaning setorial, que só precisa da
  média do setor (razoável com poucos nomes) em vez da distribuição inteira — degrada
  suavemente em vez de quebrar. O gate (Seção 10, critério 5) continua sendo quem
  verifica que a vantagem não vem de um único setor — o critério 2 (N=100 total) nunca
  vai reprovar nada por construção.
- **Folds de períodos diferentes não têm o mesmo poder estatístico.** O corte transversal
  variou de ~113 a ~235 ao longo do histórico medido — uma vitória num fold de vale de
  liquidez (2016) e uma vitória num fold de pico (2022) não são evidências equivalentes.
  Fechado com critério verificável, não ponderação nova: Seção 9 passou a reportar o N
  transversal de cada fold, e o critério 1 do gate (Seção 10) só conta um fold na régua de
  70% se o N transversal mediano do período atingir o piso — fold inteiro num vale de
  liquidez não pesa como um fold de pico.
- **Concentração do mercado** — o índice brasileiro é pesado em commodities e bancos. Um fator pode parecer funcionar quando na verdade está apostando em um setor.
- **Regimes longos** — fatores passam anos sem funcionar. Um resultado ruim em 12 meses não invalida, e um bom não valida.
- **Mudança regulatória e tributária** — regras de tributação de proventos e ganho de capital mudam. O sistema informa, não calcula obrigação fiscal.
- **Overfitting de pesos** — o risco mais provável nesta frente. Mitigado pelo log de experimentos e pelo DSR.

## 14. Expectativa calibrada

Registrado na spec de propósito, para não se perder com o tempo:

Uma carteira de fatores bem construída historicamente entrega **alguns pontos percentuais ao ano acima do índice**, com longos períodos de underperformance e sem qualquer garantia de repetição. Não é um seletor de "ações que vão subir". O ganho mais confiável deste projeto é **decisão melhor informada e menos sujeita a impulso**, não retorno excepcional.

## 15. Critérios de aceite

- [x] Toda consulta histórica respeita `data_publicacao`, com teste automatizado — provado para o índice mestre de filings CVM (`get_filing_as_of`/`get_line_items_as_of`, 6 testes contra dado real do Banco do Brasil e do BRB, 2026-08-20); mesma disciplina a estender para cotação (COTAHIST) e itens financeiros genéricos quando ingeridos
- [ ] Universo histórico inclui empresas deslistadas
- [ ] Preços ajustados por todos os eventos corporativos
- [ ] Backtest com janela fixa e reprodutível entre execuções
- [ ] Quatro classes de benchmark implementadas
- [ ] Teste de nulidade com N ≥ 100
- [ ] Log de experimentos contabilizando toda configuração testada
- [ ] Camada de evidência funcional independentemente de qualquer score
- [ ] Nenhum número exibido sem fonte e data
- [ ] `changes/` documentando cada decisão de desenho
