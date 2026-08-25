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

### 6.1 `universo_elegivel` como módulo — primeira junção real das três camadas (2026-08-20)

Implementado (`backend/src/tradingbot/acoes/universo_elegivel.py`) sobre as tabelas já
persistidas pelos três módulos anteriores — nunca re-parseia COTAHIST/FCA/CVM aqui, opera
por cima da camada point-in-time já ingerida. **Mesmo relógio nas três consultas as-of**:
fronteira inclusiva em `data_decisao` nas três (`trade_date <= data_decisao` para preço,
`data_inicio_vigencia <= data_decisao <= data_fim_vigencia` para identidade via
`get_cnpj_as_of`, `dt_receb <= data_decisao` para publicação via `get_latest_filing_as_of`
— nova consulta, generaliza `get_filing_as_of` para quando o exercício de referência não
é conhecido de antemão) — testado com dado real de junção de fronteira (`BBAS3`/Banco do
Brasil, mesma data servindo de borda em duas camadas diferentes: último pregão real do
fixture e `dt_receb` real de um filing).

**Precedência de exclusão explícita e sequencial** (nunca ambígua: um ticker só chega a um
motivo posterior se sobreviveu a todos os anteriores):

1. `iliquido` — mediana de `VOLTOT` na janela móvel abaixo do piso.
2. `classe_secundaria` — mesma raiz de 4 letras que uma classe mais líquida já escolhida.
3. `identidade_nao_resolvida` — `get_cnpj_as_of` devolve `None` na data de decisão.
4. `recuperacao_judicial` — fonte real ainda pendente (Seção 13); lista vazia por padrão
   não exclui ninguém por este motivo nesta rodada.
5. `historico_insuficiente` — menos de `min_pregoes_historico` pregões do próprio ticker
   até a data de decisão; proxy independente de fator específico da Seção 7 (que ainda não
   existe como código), número exato pode precisar de revisão quando os fatores forem
   implementados.

Materializado em duas tabelas append-only: `UniversoElegivel` (quem entrou — ticker,
CNPJ, setor `SETOR_ATIV`, classe escolhida, volume mediano) e `UniversoExclusao` (quem
ficou de fora e por quê) — a segunda tão parte do artefato quanto a primeira, mesmo
mecanismo de exclusão contável já usado em `UnresolvedTicker`.

**Teste de aceite**: materialização real em 2016-07-15 (era avaliável, Seção 5.6) com
`ITUB3`/`ITUB4`/`BBAS3`/`PETR3`/`PETR4` (dado real de COTAHIST) e o índice mestre DFP real
da CVM para o exercício 2015 (publicado em 2016, incluindo as 3 retificações reais do
Banco do Brasil). Resultado: `ITUB4` (não `ITUB3`) e `PETR4` (não `PETR3`) escolhidos como
classe mais líquida, os três com CNPJ correto, e `get_latest_filing_as_of` devolvendo a
versão 3 do balanço do BB (a retificação mais recente já pública em 2016-07-15,
`dt_receb=2016-06-02`), não a versão 1 nem a 2 — prova que a junção respeita retificação
E fronteira de data ao mesmo tempo.

**Medição definitiva do piso setorial (2016-02-29, mesma data da medição original de
Seção 8/13), agora sobre código real, não proxy**: N=115 (vs. 113 original), 36 de 40
setores da taxonomia CVM abaixo de população 6 (vs. 22/27 original, cobertura de 73%) —
detalhe completo, incluindo a verificação de integridade da ingestão (contagem de linhas
byte a byte contra o arquivo bruto antes de confiar no resultado — pedido explícito do
usuário depois de dois processos em background serem interrompidos na fronteira de
sessão), em `changes/2026-08-20-modulo-acoes-b3-secao-6-universo-elegivel.md`.

### 6.2 De-para para a taxonomia setorial real da B3 (`b3_setor.py`, 2026-08-21)

A medição acima ficou na taxonomia CVM granular (`SETOR_ATIV`), não a classificação B3 de
nível 1 que a produção assume — fechado nesta rodada. Fonte verificada contra chamada
real, não presumida do nome da página: o endpoint documentado
(`b3.com.br/.../classificacao-setorial/`) não expõe nenhum arquivo de download, os dados
vêm de uma API JS por trás dela (`sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/
CompanyCall/GetDetail`), achada inspecionando o bundle carregado pela página — não
documentada publicamente. `industryClassification` é `"Setor / Subsetor / Segmento"`,
três níveis separados por `" / "`, confirmado com Petrobras (`"Petróleo. Gás e
Biocombustíveis / Petróleo. Gás e Biocombustíveis / Exploração. Refino e Distribuição"` —
setor e subsetor idênticos quando só há um subsetor dentro do setor) e Itaú
(`"Financeiro / Intermediários Financeiros / Bancos"`). Chave é o **CNPJ direto** no
payload — junção sem precisar de `cnpj_ticker_map` para este caso específico.

**Cobertura só de empresa listada hoje, confirmado empiricamente, não presumido**:
`codeCVM` antigo do Itaú (registro pré-reestruturação, cancelado) e Banco Cruzeiro do Sul
(falido, deslistado) devolvem payload vazio contra o `codeCVM` atual do Itaú, que devolve
classificação completa. Sobre as 115 empresas do universo real de 2016: 85% (98/115) têm
cobertura hoje — os 17 sem cobertura majoritariamente por fusão/incorporação/falência/
troca de ticker na década seguinte, não bug de junção (detalhe em
`changes/2026-08-21-modulo-acoes-b3-b3-setor-de-para.md`).

**Resultado, mesma data (2016-02-29), taxonomia de produção**: 11 setores de nível 1 (perto
do "~10" assumido), **5 de 11 (45%) abaixo de população 6** — o cenário "meio a meio"
pré-especificado antes de medir, nem resolvido nem inalterado, confirmando a decisão de
demeaning setorial por média em vez de percentil-dentro-do-setor com o número real de
produção, não só a taxonomia CVM proxy.

**Decisão declarada sobre o eixo temporal**: classificação B3 tratada como atributo
quase-estático, atribuído pela versão mais recente disponível — reclassificação setorial
histórica é vazamento de baixo impacto, aceito e registrado, não escondido; empresa sem
cobertura (deslistada antes de hoje) cai em exclusão contável ou fallback para `SETOR_ATIV`
da CVM, nunca em adivinhação.

`backend/src/tradingbot/acoes/b3_setor.py`: `parse_industry_classification` (parsing puro,
testado com string real), `fetch_classification` (chamada de rede, thin wrapper, não
exercitada pela suíte), `ingest_classification_snapshot` (persistência append-only por
`(cnpj, data_coleta)`, testada com quatro respostas reais capturadas — duas com
classificação, duas genuinamente vazias). Nova tabela `B3IndustryClassification`.

**Pendências desta rodada**: recuperação judicial sem fonte real (lista vazia, gate 4
nunca dispara); histórico mínimo é proxy de contagem de pregões, não amarrado a nenhum
fator específico da Seção 7 (ainda não implementada); série completa 2015-2026 de N e
distribuição setorial (só 2016-02-29 medido, por custo de ingestão — ver nota de
performance abaixo); `b3_setor` não ligado a `build_universo_elegivel` — persiste separado,
Seção 7 decide como consumir quando for implementada; ingestão via savepoint-por-linha é
lenta (~300-400s por ano completo de COTAHIST) — funcionalmente correta e verificada
(contagem de linhas bate exatamente contra o esperado nos dois anos ingeridos), mas o
padrão certo para produção é lote com um commit por arquivo, não savepoint por linha;
registrado como pendência de performance, não resolvido nesta rodada para não misturar
mudança de mecanismo de escrita com validação de
resultado na mesma passada.

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
(valor da empresa menos a média do bucket setorial), depois tomar o percentil dessa série
demeaned sobre o **universo elegível inteiro**, não sobre o setor. A diferença é o que
cada forma precisa estimar — demeaning só precisa da **média** do setor (razoável com
3–4 nomes), percentil-dentro-do-setor precisa da **distribuição inteira** (não razoável
com poucos nomes). Isso mantém o objetivo original — não comparar P/L de banco com o de
mineradora — sem exigir a população que a B3 não tem.

**Winsorização antes do demeaning — não opcional com bucket pequeno.** A média de um
setor com 3 empresas ainda é instável e sensível a outlier: uma métrica extrema de uma
empresa em situação especial desloca a média e contamina o score das outras duas. Corta
as caudas de cada métrica (percentis 1/99) antes de calcular qualquer média setorial —
rotina em fatores, implementada e testada (`fatores.py`, `winsorize`).

**Piso de bucket com fallback hierárquico declarado — população e média contam só dado
real, nunca imputado (achado da Seção 7.5).** Abaixo de `min_bucket_size` empresas
(padrão 3) **com dado real** no bucket, a média não é confiável. Em vez de cair direto
num bucket "outros" sem neutralização, o fallback sobe a hierarquia real da B3 que a
Seção 6.2 já materializa — `segmento` → `subsetor` → `setor` → universo elegível inteiro
(sem neutralização) — parando no primeiro nível que atinge a população mínima **de
empresas com dado real**, não de empresas total (real + imputada). Achado real que
motivou essa exigência: um setor com alta incidência de dado faltante pode ter a maioria
dos membros imputados pela mediana do universo — contar esses imputados na população do
bucket faria a "média do setor" ser, na prática, a mediana do universo disfarçada de
média setorial, deslocando o demeaned de toda empresa no bucket, inclusive as com dado
real. Implementado e testado (`compute_demeaned_percentiles`): cada empresa registra qual
nível de bucket foi de fato usado (`bucket_usado`), auditável por construção. Regra
idêntica em backtest e produção — mesmo princípio já aplicado à regra de dado faltante
abaixo e à regra de saída por liquidez (Seção 8).

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

**Dado faltante vs. fator inaplicável — dois ramos diferentes, nunca confundidos.**
Inaplicável (banco sem EV/EBITDA, decisão determinística por setor — matriz de
aplicabilidade abaixo, ainda não implementada) é diferente de faltante (empresa que
deveria ter o dado e não tem — não reportou, campo ausente no filing). Faltante tem regra
declarada e **implementada** (`fatores.py`, `_preencher_faltantes`): imputação pela
mediana do universo elegível inteiro, não exclusão (risco de exclusão: viés de seleção,
afasta sistematicamente empresa de reporte mais fraco) — mesma regra em backtest e
produção, idêntica, nunca implícita. Cada resultado registra se o valor foi imputado
(`imputado`), auditável.

**Por que a normalização acima existe: o piso setorial é achado real, medido três vezes,
convergente — fechado na Seção 6.2, não hipotético.** Três medições independentes da
mesma data (2016-02-29), cada uma corrigindo a cobertura da anterior — script solto com
casamento por nome (22/27 setores CVM abaixo de população 6, cobertura 73%), depois
`build_universo_elegivel` com join real por CNPJ (36/40, cobertura 100%, mesma taxonomia
CVM granular), depois `b3_setor` na taxonomia B3 real de produção (**5 de 11, 45%,
cobertura 85%** — o número que efetivamente calibra esta seção). Detalhe completo na
Seção 6.2 e `changes/2026-08-21-modulo-acoes-b3-b3-setor-de-para.md`. O 5/11 é o cenário
"meio a meio" pré-especificado antes de medir — nem o caso que abriria espaço para
percentil-dentro-do-setor, nem o caso "sem mudança" — confirmando com o número de
produção a decisão de demeaning por média tomada a partir do 22/27 direcional.

**Score composto:** média ponderada dos percentis de fator, com pesos explícitos, versionados e justificados. Pesos não são otimizados livremente sobre o histórico — cada configuração testada é registrada no log de experimentos, porque **cada tentativa é insumo do DSR**, exatamente como no bot.

### 7.1 Primeiro fator ponta a ponta: earnings yield (`fatores.py`, 2026-08-24)

Camada de decisão de modelagem, não de fundação de dado — o rigor muda de "bate com a
fonte?" para "tem justificativa econômica ou é mineração?". Earnings yield escolhido para
implementar primeiro (família Valor, já justificado acima) porque expõe o encanamento
inteiro (fallback de bucket, dado faltante, winsorização) num caso pequeno e auditável
antes de multiplicar por sete fatores.

**Fonte do lucro por ação verificada, não presumida.** A DRE consolidada da CVM já
reporta `CD_CONTA` `"3.99.01.01"`/`"3.99.01.02"` = Lucro Básico por Ação, separado por
classe (ON/PN) — não precisa derivar via ações em circulação (que exigiria uma fonte de
capital social não verificada nesta rodada). `get_eps_as_of` usa `get_latest_filing_as_of`
(Seção 6.1) para achar o balanço visível na data de decisão, depois busca o `CD_CONTA` da
classe do ticker pelo sufixo numérico (`3`=ON, `4`=PN).

**Teste de aceite, dado real, mesma data e universo que fecharam a Seção 6
(2016-07-15)**: Itaú (`ITUB4`, EPS real R$4,30) e Banco do Brasil (`BBAS3`, EPS real
R$5,03) com earnings yield positivo; **Petrobras (`PETR4`, EPS real **-R$2,67**, prejuízo
real do exercício 2015 — queda do petróleo + baixas contábeis)** com earnings yield
negativo, corretamente na ponta inferior do ranking demeaned/percentil, sem inversão de
sinal. Com só três empresas no universo desta fixture, nenhum nível da hierarquia
setorial atinge a população mínima sozinho — todas caem no bucket `universo`, resultado
real esperado dado o tamanho do universo aqui (o fallback hierárquico foi testado à parte
com caso ilustrativo do mecanismo, não dado de mercado, para provar a subida
`segmento`→`subsetor`→`setor` isoladamente).

**Bug achado e corrigido nesta rodada, antes de chegar a produção**: `winsorize` usava
índice de percentil por truncamento (`int`), que para `n=3` mapeava o percentil 99 para o
valor do meio em vez do máximo, cortando incorretamente o maior valor de uma amostra
pequena. Corrigido para arredondamento (`round`) — amostra pequena (o caso comum na B3,
Seção 6.2) não perde nada aos percentis 1/99 por construção, só corta cauda quando a
amostra é grande o suficiente para o percentil não colapsar no extremo. Testado com
regressão explícita do caso `n=3`.

**Pendente**: matriz de aplicabilidade por setor (earnings yield se aplica a todo setor,
não exercita o ramo "inaplicável" — próximo passo, testado com um banco e uma
industrial); demais fatores das famílias Qualidade/Saúde financeira/Crescimento/Momentum/
Tamanho, cada um com justificativa econômica própria antes de entrar; composição do score
só depois dos fatores individuais saírem certos.

### 7.2 Segundo fator, primeiro a exercitar a matriz: dívida líquida/EBITDA (`fatores.py`, 2026-08-24)

Ao contrário do EPS, a CVM não entrega EBITDA pronto — é derivado, e a derivação
escondia duas armadilhas reais, achadas verificando a DRE/DFC/BP de uma industrial
conhecida (Petrobras) antes de escrever qualquer fórmula, não presumindo o schema.

**D&A não está na DRE.** Confirmado contra as 86 linhas reais da DRE da Petrobras
(todos `DT_REFER`/`ORDEM_EXERC`): zero menções a depreciação/amortização. Só aparece na
**DFC método indireto** (`dfp_cia_aberta_DFC_MI_con_AAAA.csv`), grupo de reconciliação do
lucro líquido `CD_CONTA "6.01.01.*"` — para a Petrobras, `"6.01.01.04"` = "Depreciação,
Depleção e Amortização", real R$38.574 milhões. **O código exato não é fixo**
(`ST_CONTA_FIXA='N'`, confirmado) — `get_depreciacao_amortizacao_as_of` busca por
conteúdo de `DS_CONTA` dentro do prefixo, não por código literal; das 12 linhas reais do
grupo de reconciliação da Petrobras, só uma casa com as palavras-chave, resolvendo sem
ambiguidade.

**`ST_CONTA_FIXA='S'` não garante o mesmo significado entre planos de contas
diferentes — o achado mais perigoso desta rodada.** `CD_CONTA "3.05"` (DRE) é
`ST_CONTA_FIXA='S'` tanto para Petrobras quanto para Itaú, mas: Petrobras =
`"Resultado Antes do Resultado Financeiro e dos Tributos"` (EBIT real, **-R$13.188
milhões — a Petrobras teve prejuízo operacional em 2015**, não só líquido); Itaú =
`"Resultado Antes dos Tributos sobre o Lucro"` (lucro pré-imposto, conta inteiramente
diferente — instituição financeira usa um plano de contas de DRE próprio, fixo *dentro*
da variante, não *entre* variantes). Sem verificar `DS_CONTA`, `get_ebit_as_of` teria
devolvido o lucro pré-imposto do banco com cara de EBIT — erro silencioso, não uma
exceção. `get_ebit_as_of` verifica `DS_CONTA` antes de aceitar qualquer valor; devolve
`None` para Itaú e Banco do Brasil, corretamente.

**Consolidado vs. individual: convenção fixa, estrutural, não por confiança.**
`CvmFinancialLineItem` ganhou o campo `base` (`"con"`/`"ind"`, padrão `"con"`) — cada
consulta de fator filtra pela mesma base sempre, por construção, para que EBIT
consolidado nunca se combine com D&A individual (ou vice-versa) num EBITDA sem sentido
econômico.

**EBITDA real da Petrobras é positivo apesar do EBIT real negativo** — R$25.386 milhões
(EBIT -R$13.188M + D&A R$38.574M) — o comportamento esperado numa empresa intensiva em
ativo fixo, e a prova de que a soma está certa, não só a mecânica.

**Dívida líquida** (BP): caixa e equivalentes (BPA `"1.01.01"`) menos empréstimos e
financiamentos circulante (BPP `"2.01.04"`) + não circulante (BPP `"2.02.01"`) — real da
Petrobras: R$395.004 milhões. Dívida líquida/EBITDA real ≈ **15,56x** — alavancagem real e
severa, consistente com o rebaixamento de rating da Petrobras por agências
internacionais em 2015.

**Três categorias de ausência, nunca confundidas, cada uma um ramo de código
diferente**:

1. **Inaplicável** — matriz por subsetor B3 (`fator_divida_liquida_ebitda_aplicavel`),
   não "financeiro sim/não" binário. Escopo desta rodada: só `"Intermediários
   Financeiros"` (bancos), verificado estruturalmente (o próprio plano de contas de DRE
   de banco não tem conta equivalente a EBIT). Justificativa econômica registrada:
   alavancagem é o próprio negócio do banco (insumo de intermediação financeira), não um
   risco a medir — dívida líquida não significa o mesmo que numa industrial.
   Seguradoras, bolsa (`BVMF3`/B3) e holdings financeiras são casos-limite distintos,
   **não verificados nesta rodada** — ficam de fora da matriz até serem confirmados
   contra dado real, não assumidos.
2. **Faltante** — `get_ebitda_as_of`/`get_divida_liquida_as_of` devolvem `None` por linha
   ausente ou ambígua (D&A sem candidato único). Imputado pela mediana do universo pela
   mesma `compute_demeaned_percentiles` do earnings yield.
3. **Indefinido** — `divida_liquida_ebitda_raw` devolve `None` quando `EBITDA ≤ 0`: o
   dado existe, mas o múltiplo não tem significado econômico (EBITDA perto de zero faz o
   múltiplo explodir; negativo inverteria o sinal — mesmo problema do P/L com lucro
   negativo, do lado do denominador). Mecanicamente tratado como faltante na
   normalização, mas semanticamente distinto, registrado para auditoria.

**Score composto renormaliza pesos sobre fatores aplicáveis** (`compute_score_composto`)
— sem isso, a matriz criaria um viés setorial escondido na aritmética: banco com um fator
a menos (inaplicável) teria o score puxado para baixo só por contar menos parcelas, não
por desempenho pior. Teste de aceite: `ITUB4` (só earnings yield aplicável) e `PETR4`
(os dois fatores aplicáveis), ambos no percentil 80 nos fatores que se aplicam a cada um,
chegam ao **mesmo score composto** — a prova de que a matriz não penaliza estrutura
setorial. Isso resolve, para este par de fatores, a pergunta em aberto sobre a Seção 8:
como Seção 8 ainda não tem código (só spec), a renormalização foi implementada aqui como
semente mínima, não como o motor de carteira completo — quando a Seção 8 for
implementada, precisa herdar esta regra, não redecidir.

**Point-in-time de três demonstrações, testado**: EBITDA (DRE+DFC) e dívida líquida (BP)
resolvidos pelo mesmo `get_latest_filing_as_of` — antes da publicação real da Petrobras
(`dt_receb=2016-03-21`), os dois são `None`; depois, os valores reais aparecem, do mesmo
exercício. O teste mais exigente de point-in-time até agora, porque combina três
consultas datadas num número só.

**Pendente**: EV/EBITDA (precisa de valor de mercado = ações em circulação × preço —
fonte não encontrada em FCA nem DFP, provável quinta demonstração, Formulário de
Referência, não aberta nesta rodada); seguradoras/bolsa/holdings financeiras na matriz;
demais famílias de fator; Seção 8 (motor de carteira) ainda sem código — a renormalização
de pesos existe só como função isolada em `fatores.py`, precisa ser adotada quando a
Seção 8 for implementada de verdade.

### 7.3 Terceiro fator, primeiro a cruzar duas demonstrações num quociente: ROE (`fatores.py`, 2026-08-24)

Família Qualidade. ROE = lucro líquido (DRE) / patrimônio líquido (BP) — o primeiro fator
onde o numerador e o denominador vêm de demonstrações diferentes no mesmo quociente, não
só somados (EBITDA) ou usados lado a lado (dívida líquida/EBITDA).

**O princípio do `"3.05"` (Seção 7.2) se confirma de novo, preventivamente verificado
antes de calcular.** `DS_CONTA "Atribuído a Sócios da Empresa Controladora"` (lucro dos
controladores) e `DS_CONTA "Patrimônio Líquido Consolidado"` são idênticos nas duas
variantes de plano de contas (banco e industrial) — mas o `CD_CONTA` numérico muda por
empresa (`"3.09.01"`/`"2.08"` para banco, `"3.11.01"`/`"2.03"` para a Petrobras),
dependendo de quantas linhas precedem na demonstração de cada uma. Toda consulta busca
por `DS_CONTA`, nunca por código — a lição do "3.05" aplicada preventivamente desta vez,
não descoberta durante a implementação.

**Lucro dos controladores, não o consolidado com minoritários** — mesma disciplina de
consistência já usada em `base` (con/ind, Seção 7.2): patrimônio líquido também precisou
ser líquido de minoritários (`"Patrimônio Líquido Consolidado"` menos `"Participação dos
Acionistas Não Controladores"`, achado real: a linha de minoritários existe separada no
BP, subtraída para consistência com o numerador) — usar o patrimônio total sobre o lucro
dos controladores infla o ROE.

**Patrimônio líquido ≤ 0 → indefinido — a armadilha mais traiçoeira do módulo até
aqui.** Prejuízo dividido por patrimônio negativo dá ROE **positivo** — empresa em
situação terminal aparecendo no topo do ranking de qualidade. `roe_raw` devolve `None`
nesse caso, confirmando que a categoria "indefinido" (introduzida para `EBITDA ≤ 0`,
Seção 7.2) generaliza para um segundo gatilho totalmente independente, sem acoplamento
entre as duas funções — testado explicitamente.

**ROE real, 2015**: Petrobras -13,68% (prejuízo real, mas patrimônio ainda positivo —
não é o caso indefinido, é prejuízo genuíno corretamente refletido), Itaú +22,93%, Banco
do Brasil +17,04%.

**ROE não precisa da matriz — testa o demeaning setorial de verdade.** Diferente de
dívida líquida/EBITDA, banco tem lucro e patrimônio, ROE de banco é métrica central, não
inaplicável. Mas ROE de banco é estruturalmente mais alto que o de industrial
(alavancagem), então comparação em nível absoluto seria injusta — o demeaning setorial
já construído (Seção 7) resolve isso sem precisar de matriz nova. Testado com os dois
bancos reais (`ITUB4`/`BBAS3`, mesmo segmento `Bancos`), demeaned contra a própria média
de par (`min_bucket_size=2` — a fixture desta rodada só tem 3 empresas ao todo, piso de
produção nunca formaria bucket de segmento com só 2 nomes), e com um mecanismo isolado
(dado ilustrativo, não real — seis nomes divididos em bucket "bancos" ~20% de ROE e
bucket "industriais" ~5%): depois do demeaning, o banco e a industrial "típicos" do
próprio setor ficam com percentil parecido, não um sistematicamente acima do outro só
pela estrutura de capital do setor.

**Ortogonalidade medida, não presumida — com a ressalva estatística que o tamanho da
amostra exige.** Correlação de Pearson entre earnings yield e ROE sobre as três empresas
desta fixture: **≈0,92**. Alta — mas `n=3` não é amostra suficiente para aplicar o
limiar de 0,7 pré-especificado com qualquer confiança: três pontos quase sempre produzem
correlação alta por acaso, não porque os fatores meçam a mesma coisa de verdade. O número
é calculado e registrado honestamente (não escondido por ser inconveniente), mas a
decisão sobre ortogonalidade real fica **pendente até medir sobre o universo de 2016
inteiro** (115 empresas, já materializado na Seção 6.1) — o próximo passo explícito, não
fabricado aqui só para fechar a pergunta.

**Pendente**: correlação real sobre o universo de 115 empresas (a medição que decide se
ROE adiciona informação genuína); demais famílias de fator; Seção 8 ainda sem código.

### 7.4 Correlação real sobre as 115 empresas — a medição que fecha (ou não) a Seção 7 com três fatores (2026-08-25)

Medição completa, não a amostra de `n=3` da Seção 7.3: as 115 empresas do universo de
2016-02-29 (Seção 6.1), earnings yield e ROE calculados ponta a ponta para cada uma —
mesmo `get_latest_filing_as_of`, mesma disciplina point-in-time, nenhum atalho.

**Achado que confirma por que a rigor do point-in-time importa aqui, não só nos casos já
conhecidos**: 62 das 114 empresas com algum filing visível em 2016-02-29 resolveram para
o balanço do exercício **2014** (publicado 2015), não 2015 — a maioria das DFPs de 2015
só foi publicada entre março e junho de 2016, depois da data de decisão. Confirma
exatamente o que seria esperado de uma consulta point-in-time honesta: a maior parte do
universo, numa data no início do ano, ainda está reportando o exercício anterior.

**Achado novo de fonte, descoberto medindo, não hipotético**: os arquivos de item
financeiro da CVM (`DRE_con_AAAA.csv`, `BPP_con_AAAA.csv` etc.) **só contêm a versão mais
recente já retificada de cada filing — não as versões antigas que estavam vigentes numa
data de decisão passada.** Confirmado contra o caso real do Banco do Brasil: o índice
mestre mostra 3 versões do balanço de 2015 (`dt_receb` 2016-02-25/2016-03-28/2016-06-02);
em 2016-02-29, só a versão 1 estava publicamente visível — mas o arquivo `DRE_con_2015.csv`
baixável hoje só tem a versão 3. O módulo recusa corretamente usar a versão errada (isso
seria vazamento de point-in-time disfarçado de dado disponível) — o resultado é `None`
(faltante), não um número calculado com a versão errada. Distinto de "empresa não
reportou": é "a CVM não disponibiliza mais o conteúdo da versão que estava vigente".
Afeta qualquer consulta de fator (não só EPS/ROE) numa janela entre a publicação inicial
e a retificação final de uma empresa — registrado como limitação de fonte, não bug.

**Composição do `n` faltante** (34 de 115 empresas com pelo menos um dos dois fatores
ausente): 10 por versão indisponível (achado acima), 6 sem nenhuma linha no arquivo de
item para o `(CNPJ, dt_refer)` resolvido, 1 sem filing algum visível na data, e os ~17
restantes por estrutura de conta (`DS_CONTA`) não encontrada apesar da versão certa
estar disponível — a cauda que já era esperada de reporte heterogêneo.

**`n` efetivo = 81 de 115 (70%)** — as empresas com earnings yield **e** ROE definidos ao
mesmo tempo (nem faltante, nem indefinido, nem imputado), a única base sobre a qual a
correlação tem significado.

| | Bruta (valor cru) | **Demeaned (o que o score usa)** |
|---|---|---|
| Correlação (Pearson, `n=81`) | 0,28 | **0,40** |

**A correlação demeaned veio mais alta que a bruta — direção oposta à hipótese de
trabalho, e vale entender por quê em vez de forçar a leitura esperada.** A hipótese
registrada na Seção 7.3 era que o demeaning poderia reduzir a correlação (qualidade e
valor divergindo dentro do setor). O resultado real sugere o oposto: parte da correlação
bruta pode estar sendo **amortecida** por efeito de setor — banco tem ROE
estruturalmente alto mas também earnings yield próprio (mercado já precifica o setor
diferente), um efeito de nível que empurra na direção contrária dentro do bruto. Depois
do demeaning (comparação dentro do próprio setor), sobra mais puramente o efeito
mecânico esperado — os dois fatores compartilham lucro no numerador, então alguma
correlação positiva é estrutural, não evidência de que medem o mesmo conceito (Seção
7.3). **0,40 é moderado**: acima de zero (não são estatisticamente independentes, nem
deveriam ser), mas bem abaixo do limiar de 0,7 que sinalizaria redundância.

**Decisão de escopo da Seção 7, conforme o critério pré-especificado**: correlação
demeaned moderada (0,40, não baixa nem alta) — dentro da faixa que o usuário definiu como
suficiente para fechar a Seção 7 com os três fatores implementados (earnings yield,
dívida líquida/EBITDA, ROE — três famílias distintas: valor, alavancagem, qualidade) e
seguir para o backtest (Seção 9), em vez de implementar as famílias restantes
(Crescimento, Momentum — bloqueado por magnitude de evento, Dividendos — bloqueado por
cobertura de proventos, Tamanho) antes de saber se a abordagem tem qualquer poder. É o
backtest e o teste de nulidade (Seção 9/10) que decidem isso, não mais fatores.

**Pendente**: correlação de três vias incluindo dívida líquida/EBITDA (parcialmente
inaplicável a banco, precisa de tratamento diferente na matriz de correlação — não
medido nesta rodada); demais famílias de fator, retomadas só se o backtest com os três
fatores atuais não tiver poder suficiente.

### 7.5 A limitação de versão retificada, medida — incidência, perfil, e a decisão de desenho que ela força (2026-08-25)

O achado da Seção 7.4 (arquivos de item da CVM só têm a versão mais recente retificada,
não a vigente numa data de decisão passada) foi medido em incidência, perfil de quem cai,
e comparado com uma fonte alternativa antes de aceitar a limitação como estrutural.

**Fonte alternativa verificada, não presumida indisponível.** O índice mestre tem
`ID_DOC`/`LINK_DOC` por versão, apontando para `rad.cvm.gov.br` — em princípio, o
documento específico de cada versão existe e é endereçável. Testado contra dado real
(Banco do Brasil, versão 1, `NumeroSequencialDocumento=53614`): o sistema migrou para
`ENETWeb`, uma aplicação ASP.NET WebForms orientada a sessão (`__VIEWSTATE`/
`__EVENTVALIDATION` presentes, sem endpoint de download direto acessível por HTTP
simples) — recuperar o conteúdo de uma versão antiga exigiria simular navegação
interativa por empresa/documento, uma integração ordens de magnitude mais cara que o
portal de dados abertos usado no resto da spec, e possivelmente um formato de documento
diferente (XBRL/PDF) exigindo extração própria. **Não descartado por suposição — testado,
e fechado com a mesma postura que fechou o código interno da CVM sem par derivável
(Seção 5.6): existe em princípio, não é viável em lote dentro de esforço razoável.**

**Medição de incidência, dois anos reais (2015-02-27 e 2016-02-29, universos já
materializados na Seção 6.1/6.2)**:

| | 2015 | 2016 |
|---|---|---|
| Universo (N) | 125 | 115 |
| Versão divergente (qualquer fator) | 9 (7,2%) | 10 (8,7%) |
| `n` efetivo — **os dois fatores** presentes | 88 (70,4%) | 81 (70,4%) |
| `n` efetivo — **pelo menos um** fator presente | 106 (84,8%) | 97 (84,3%) |

Incidência estável entre os dois anos adjacentes, não uma escalada — consistente com o
mecanismo (o efeito cresce com o tempo decorrido *desde a data de decisão até hoje*, e
os dois anos medidos estão igualmente distantes de 2026). Série completa 2015-2026 seria
necessária para confirmar se anos mais recentes (2024-2026, menos tempo decorrido) têm
incidência menor — não medida nesta rodada (depende da ingestão completa, Seção
12/pendências).

**Perfil de quem cai — o achado que importa mais que o número.** Tamanho (mediana de
`VOLTOT`) das empresas com versão divergente **não** difere sistematicamente do universo
geral (2015: R$11,4M vs. R$11,8M da mediana geral; 2016: R$21,2M vs. R$12,3M — se algo,
mais líquidas, não menos) — não é o viés "empresa pequena e obscura" que a hipótese de
trabalho cogitava. **Mas setor concentra fortemente: bancos são 5 dos 9 casos (2015) e 5
dos 10 (2016) — mais da metade das ausências por este motivo, contra ~14% de
participação de bancos no universo total.** Não aleatório.

**Diagnóstico de nível, não só de cobertura — o ROE calculado com a versão errada
(nunca usado como valor, só como sonda) mostra os bancos excluídos sistematicamente mais
baixos que os incluídos, nos dois anos**: mediana dos incluídos 18,0% (2015)/17,6% (2016)
contra mediana dos excluídos 14,4%/14,8% — direção consistente nos dois anos, amostra
pequena (2 incluídos vs. 5 excluídos por ano, não robusto para magnitude, mas o
sinal direcional se repete). **Achado mais específico embutido nele**: em ambos os anos,
o setor "Bancos" tinha só 2 dos 7 membros com ROE real — os outros 5 imputados pela
mediana do universo inteiro (bem mais baixa que o nível bancário típico).

**Bug real achado e corrigido a partir desse diagnóstico, antes de chegar ao backtest**:
`compute_demeaned_percentiles` contava população e calculava média de bucket incluindo
os valores **imputados** — com 5 dos 7 bancos imputados, `len(grupo)=7 >= 3` passava o
piso de população, e a média "dos bancos" saía calculada com 5 valores que eram na
verdade a mediana do universo inteiro, não dado bancário — diluindo o demeaned de *toda*
empresa no bucket, inclusive as com ROE real. Corrigido: população e média de bucket
usam só valores reais; um bucket com poucos membros reais sobe a hierarquia mesmo que a
contagem total (real + imputada) pareça suficiente. Testado
(`test_bucket_com_maioria_imputada_sobe_hierarquia_em_vez_de_diluir`).

Com a correção, os dois bancos reais de cada ano (2015: `BBTG11`/`ITUB4`; 2016:
`ITUB4`/`SANB11`) são demeaned contra a média do **universo inteiro** (nenhum nível da
hierarquia bancária tem 3+ membros reais), não contra um bucket "Bancos" fantasma. Isso
enfraquece a comparação banco-contra-banco que a Seção 7.3 demonstrou com dado real (que
usava uma data diferente, 2016-07-15, onde a versão do BB já estava disponível) — a
ressalva correta não é "a Seção 7.3 está errada", é "a comparação banco-contra-banco só
funciona quando o setor tem massa real suficiente, e a versão retificada reduz essa massa
justamente no setor onde ROE mais importa".

**A decisão de desenho que os dois números de `n` efetivo forçam — corrigida após
revisão.** Exigir os dois fatores presentes trava em 70,4% nos dois anos. Permitir score
composto parcial (pelo menos um fator, via `compute_score_composto`, Seção 7.2) sobe para
84,3% (2016) e 84,8% (2015). **Os dois ficam abaixo do piso de 85% de identidade — não
"na fronteira, passando por pouco". Reusar ou afrouxar esse piso para caber seria o
mesmo erro que a Seção 5.6 já corrigiu uma vez (piso de cobertura medindo o risco
errado).** O piso de 85% foi desenhado para cobertura de **identidade**, onde o erro
corrompe em silêncio (empresa errada inteira no ranking). Cobertura de **fator** é outra
natureza — ausência visível, contável, e mitigada pela renormalização — então precisa de
piso próprio, com sua própria justificativa, não o número emprestado.

**Recomendação de desenho para a Seção 10, não decidida aqui**: em vez de inventar um
piso de porcentagem novo para cobertura de fator, generalizar o critério de amostra
transversal que a Seção 10 já usa (**N≥100** do universo elegível total, critério 2) para
o **universo com score computável** — a mesma preocupação (amostra transversal pequena
demais para poder estatístico) já é o motivo por trás do N=100 original; cobertura de
fator só decide quantas empresas *de fato* entram nessa contagem. Aplicando isso aos dois
anos medidos: 2015 tem 106 empresas com score computável (**passa** N≥100); **2016 tem
97, abaixo de 100 — não passaria pelo critério 2 já existente, aplicado ao denominador
certo.** Isso é mais rigoroso que qualquer piso percentual novo, e não precisa de número
inventado — reusa o que já está pré-registrado, só corrige o denominador.

**Requisito novo para o backtest (Seção 9/10): relatório segmentado por setor.** Se o
conjunto de fatores parecer funcionar mas a vantagem estiver concentrada no setor
financeiro — o setor mais afetado pela versão retificada e o único onde ROE tem massa
real reduzida — não há como distinguir sinal genuíno de artefato da limitação de fonte.
Mesmo espírito do critério de degradação por regime (Seção 10, critério 5: não concentrar
a vantagem num único setor ou período) — aqui vira exigência de reportar, não só verificar
no gate: o relatório do backtest precisa de uma linha própria para o desempenho do setor
financeiro, separada do agregado.

**Pendente**: confirmar se o `n` de score computável (não a fração) se sustenta acima de
100 em anos mais recentes da era avaliável (2024-2026, onde a versão retificada deveria
pesar menos); piso de cobertura de fator, se algum diferente do N≥100 generalizado for
necessário, ainda como decisão de desenho separada e justificada, não tomada aqui.

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

   **Atualização (Seção 7.5): N=100 passa a morder de verdade quando aplicado ao
   denominador certo.** O texto acima falava do universo elegível *total* (liquidez +
   identidade). Com os fatores implementados, existe um universo mais estreito — o
   subconjunto com **score composto computável** (pelo menos um fator presente,
   descontando a limitação de versão retificada da CVM, Seção 7.5). Medido nos dois anos
   reais já auditados: 2015 tem 106 empresas com score computável (passa); **2016 tem 97,
   abaixo de 100 — reprovaria pelo critério 2 já existente, se aplicado a este
   denominador em vez do universo bruto.** Recomendação registrada, decisão da Seção 10 a
   confirmar: aplicar N≥100 ao universo com score computável, não ao universo elegível
   bruto — generaliza o critério já pré-registrado em vez de inventar um piso de
   cobertura de fator novo (que teria o risco de ser calibrado para caber, não
   justificado por natureza de risco própria).
3. Fica fora da nuvem nula com p < 0,05.
4. Tem DSR positivo, contabilizando **todas** as configurações de peso testadas.
5. Não concentra a vantagem inteira em um único setor ou em um único período — segmentação com piso de amostra mínima. Ver nota do critério 2: este é o critério com poder real de reprovação nesta frente, não o 2. **Setor financeiro exige linha própria no relatório do backtest (Seção 7.5/9)**: é o setor mais afetado pela limitação de versão retificada e o único onde o bucket de ROE tem massa real reduzida — sem reportar separado, não há como distinguir vantagem genuína de artefato da limitação de fonte.
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
| 2 | Universo elegível + eventos corporativos + survivorship | universo reconstruído corretamente para datas passadas — **`universo_elegivel` (junção real de identidade+preço+publicação, precedência de exclusão explícita, materialização append-only) implementado e testado contra dado real, 2026-08-20** (`backend/src/tradingbot/acoes/universo_elegivel.py`); teste de aceite materializando 2016-07-15 (`ITUB4`/`BBAS3`/`PETR4` com CNPJ, classe e filing corretos); **de-para para a taxonomia setorial real da B3 (`b3_setor.py`) fechado 2026-08-21** — 11 setores de nível 1, 5/11 abaixo de população 6 (85% de cobertura sobre o universo de 2016), confirmando com o número de produção a decisão de demeaning por média — série completa 2015-2026 segue pendente |
| 3 | Cálculo de fatores + percentis setoriais | **fechada com três fatores, decisão de escopo tomada em 2026-08-25**: earnings yield, dívida líquida/EBITDA e ROE implementados ponta a ponta contra dado real (`backend/src/tradingbot/acoes/fatores.py`) — winsorização, demeaning hierárquico B3, matriz de aplicabilidade, renormalização de pesos, categoria "indefinido" generalizada. Correlação demeaned real sobre as 115 empresas de 2016 (`n` efetivo 81/115): **0,40, moderada** — dentro da faixa que fecha a Seção 7 com estes três fatores (valor/alavancagem/qualidade) e segue para o backtest (Seção 9), em vez de implementar as famílias restantes antes de medir se a abordagem tem poder. Demais famílias (Crescimento, Momentum, Dividendos, Tamanho) e o motor de carteira completo (Seção 8) ficam pendentes, retomados só se o backtest não tiver poder suficiente com os três atuais |
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
  percentil-dentro-do-setor.** Três medições independentes da mesma data (2016-02-29),
  cada uma corrigindo a cobertura da anterior, convergem na mesma direção:

  | Medição | Taxonomia | Cobertura | N | Setores medidos | Abaixo de população 6 |
  |---|---|---|---|---|---|
  | Original (script solto, casamento por nome) | CVM (`SETOR_ATIV`, granular) | 73% (83/113) | 113 | 27 | 22 (81%) |
  | Código real, join por CNPJ (`build_universo_elegivel`) | CVM (`SETOR_ATIV`, granular) | 100% (115/115) | 115 | 40 | 36 (90%) |
  | **De-para B3 real (`b3_setor.py`, 2026-08-21)** | **B3 nível 1 (produção)** | **85% (98/115)** | 115 | **11** | **5 (45%)** |

  A terceira medição é a que importa para produção: fonte verificada contra chamada real
  (não presumida do nome da página — a página HTML de "Classificação setorial" não expõe
  nenhum arquivo, os dados vêm de uma API JS por trás dela,
  `sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetDetail`, achada
  inspecionando o bundle carregado, não documentada publicamente). Schema confirmado por
  chamada real: `industryClassification` é `"Setor / Subsetor / Segmento"`, três níveis
  separados por `" / "` — 11 setores de nível 1 no universo de 2016, perto do "~10"
  assumido. Chave é o **CNPJ direto** no payload, não precisa de `cnpj_ticker_map` para
  esta junção específica.

  **Cobertura confirmada empiricamente, não presumida — a fonte só cobre empresa listada
  hoje.** Testado direto: `codeCVM` antigo do Itaú (registro pré-reestruturação, cancelado)
  e o Banco Cruzeiro do Sul (falido, deslistado) devolvem payload vazio; o `codeCVM` atual
  do Itaú devolve classificação completa. Sobre as 115 empresas reais do universo de 2016:
  85% (98/115) têm classificação hoje — os 17 sem cobertura são majoritariamente fusão,
  incorporação, falência ou troca de ticker na década seguinte (`LAME4`→Americanas
  pós-recuperação judicial, `FIBR3`→incorporada pela Suzano, `SMLE3`→incorporada pela GOL,
  `QGEP3`→renomeada Enauta, entre outras) — não um bug de junção. **Decisão declarada**
  (não escondida): classificação B3 tratada como atributo quase-estático, atribuído pela
  versão mais recente disponível — reclassificação setorial histórica (setor de hoje
  aplicado a uma decisão de 2016) é vazamento de baixo impacto, aceito; empresa sem
  cobertura cai em exclusão contável ou fallback para `SETOR_ATIV` da CVM, nunca em
  adivinhação.

  **5 de 11 setores (45%) abaixo de população 6 na taxonomia de produção — exatamente o
  cenário "meio a meio" pré-especificado antes de medir**, nem o caso "resolvido"
  (2-3/10, que abriria espaço para percentil-dentro-do-setor) nem o caso "sem mudança"
  (quase todos pequenos). Confirma, com o número real de produção, a decisão de
  arquitetura já tomada: a Seção 7 normaliza por percentil-no-universo com demeaning
  setorial, que só precisa da média do setor (razoável com poucos nomes, inclusive nos
  6 setores acima do piso) em vez da distribuição inteira — degrada suavemente nos
  setores pequenos em vez de quebrar. O gate (Seção 10, critério 5) continua sendo quem
  verifica que a vantagem não vem de um único setor — o critério 2 (N=100 total) nunca vai
  reprovar nada por construção.
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
