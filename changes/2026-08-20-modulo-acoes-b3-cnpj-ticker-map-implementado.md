# 2026-08-20 — Módulo de Ações: `cnpj_ticker_map` implementado como código

## Contexto

Terceira e última das três fundações point-in-time da Fase 1 (identidade, depois de
publicação — CVM, Seção 5.1/5.2 — e preço — COTAHIST, Seção 5.3). Usuário pediu
implementação como módulo primeiro, não deixar a Seção 6 assumir que a peça existe — a
mesma lição da armadilha do FATCOT (não construir contra uma interface presumida sem
verificar). Três exigências explícitas: a precisão já auditada (712 identificações,
zero erros) precisa sobreviver à passagem para código via teste de regressão; as regras
que só existiam na spec (vigência das bordas da COTAHIST, tolerância de 180 dias,
exclusão contável) precisam virar comportamento testado; a consulta as-of do mapa precisa
usar a mesma convenção de fronteira de `get_filing_as_of`.

## O que foi implementado

`backend/src/tradingbot/acoes/cnpj_ticker_map.py`: `load_fca_identity` (lê
`Nome_Empresarial` mesmo em anos onde `Codigo_Negociacao` vem vazio), `resolve_identity`
(três níveis — `fca` → `raiz_propagacao` → `reconciliacao_nome`, qualquer um só resolve
se inequívoco), `compute_vigencia` (bordas da COTAHIST, tolerância de 180 dias usando a
data máxima do próprio dataset, nunca "hoje" real), `build_cnpj_ticker_map` (append-only,
savepoint por linha, grava `UnresolvedTicker` para ticker sem CNPJ), `get_cnpj_as_of`
(mesma convenção `<=`/`>=` inclusiva-inclusiva de `get_filing_as_of`). Dois modelos novos
em `models.py`: `CnpjTickerMap` e `UnresolvedTicker`, ambos com `UniqueConstraint`
estrutural.

## Achado de auditoria: 4 dos 50 matches de `reconciliacao_nome` eram falsos positivos

Rodando o módulo contra os universos elegíveis EXATOS dos seis anos já auditados
(extraídos dos `.pkl` da medição original, não re-derivados — uma tentativa de
reimplementar o filtro de liquidez do zero deu 164 e depois 171 tickers para 2010, dois
números diferentes entre si e do 159 correto, por bugs de um script descartável — usar o
dado congelado eliminou esse risco), 50 tickers resolveram via `reconciliacao_nome`
(caminho nunca coberto pela auditoria de 712, que era só `fca`+`raiz_propagacao`).
Auditoria manual de todos os 50 (todos exceto um eram matches de token único, o cenário
de maior risco) contra `cad_cia_aberta.csv` achou 4 falsos positivos reais:

| Ticker | Token | CNPJ errado | Empresa real |
|---|---|---|---|
| `BRTO3` (Brasil Telecom) | `TELEC` | Telebrás | CNPJs diferentes — mesma abreviação de "telecomunicações" |
| `CCIM3` (CC Desenv. Imob.) | `IMOB` | BRPR56 Securitizadora | Abreviação genérica de "imobiliário" |
| `CZRS4` (Banco Cruzeiro do Sul, falido) | `CRUZEIRO` | Cruzeiro do Sul Educacional | CNPJs diferentes confirmados no registro CVM |
| `RAIA3` (Droga Raia, pré-fusão 2010) | `RAIA` | CNPJ pós-fusão RaiaDrogasil | Nome consolidado pós-fusão vazando para ticker pré-fusão |

Os quatro tokens entraram em `_GENERIC_NAME_TOKENS`. Os outros 13 casos de token único
(`KROTON`, `CONTAX`, `TEGMA`, `PLASCAR`, `DROGASIL`, `MARISA`, `PACTUAL`, `PROPERT`,
`TIETE`, `TREVISA`, `SMILES`, `AMBEV`, `PPLA`) foram confirmados corretos um a um — um
deles (`PPLA11`) parecia suspeito por não aparecer em `cad_cia_aberta.csv`, mas é
`PPLA Participations Ltd`, emissor estrangeiro de BDR, fora do escopo desse registro.

## Teste de regressão: 712 → 713, divergência isolada e explicada

O teste de regressão roda `resolve_identity` contra o universo congelado dos seis anos
auditados e compara par a par (não só a contagem total) com o resultado esperado. Total
bate em 713, não 712: `DMMO3`/2017 agora resolve via `raiz_propagacao` (raiz `DMMO`, CNPJ
único da FCA, Dommo Energia) — a auditoria original não tinha essa identificação por não
ter carregado exatamente o mesmo conjunto de anos FCA. Não é regressão de precisão (o
caminho `raiz_propagacao` carrega sua própria garantia de 100%, Seção 5.6) — o teste
isola esse caso num assert próprio em vez de deixá-lo escondido dentro do total.

## Teste de aceite: `KROT3`→`COGN3`

Fixtures reais: linhas de `COTAHIST_A2019.ZIP` cobrindo `KROT3` (04/10 a 10/10/2019) e
`COGN3` (11/10 a 18/10/2019), mais um punhado de linhas de `COGN3` em maio/2020 só para
empurrar a data máxima observada além da tolerância de 180 dias e fechar a vigência de
`KROT3` de verdade (sem esse segundo arquivo, `KROT3` ficaria "ainda vigente" por falta
de dado posterior, não por estar certo). `get_cnpj_as_of("KROT3", 2019-10-10)` e
`get_cnpj_as_of("COGN3", 2019-10-11)` devolvem o mesmo CNPJ (`02.800.026/0001-40`, Cogna);
consultas no lado errado da fronteira (`KROT3` em 10-11, `COGN3` em 10-10) devolvem
`None` — sem sobreposição, sem vão.

## Testes novos

`backend/tests/test_acoes_cnpj_ticker_map.py`, 7 testes: regressão dos 713 matches
fca+raiz_propagacao; `KROT3`→Cogna via `reconciliacao_nome`; os 4 falsos-positivos
confirmados ficam `None`; `compute_vigencia` fecha `KROT3` e mantém `COGN3` vigente;
teste de aceite completo `get_cnpj_as_of`; `UnresolvedTicker` contável; append-only.
383 testes passam na suíte completa (376 + 7 novos), zero regressão.

Fixtures novas: `tests/fixtures/fca/valor_mobiliario_{2018,2019,2020,2021,2022,2024,2025}.csv`
(arquivos completos, reais, ~130-175KB cada); `tests/fixtures/cnpj_ticker_map/
universo_auditado_2010_2017.json` (universos elegíveis congelados dos seis anos + pares
resolvidos, extraídos dos `.pkl` da auditoria original); `tests/fixtures/cotahist/
COTAHIST_A2019_krot_cogn_real_extract.ZIP` + `..._A2020_cogn_real_extract.ZIP`.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Nova Seção 5.7: os três níveis de resolução de identidade implementados, a vigência
sempre da COTAHIST, a tabela dos 4 falsos-positivos com a empresa real confundida, o
teste de regressão (713 vs. 712, divergência explicada) e o teste de aceite fechado.
Seção 12 (Fase 1) atualizada para incluir o `cnpj_ticker_map` entre as peças implementadas
e testadas.

## Pendente

- Seção 6 (universo elegível) — próximo passo, primeiro artefato que junta as três
  fundações point-in-time numa data de decisão, materializado a uma tabela.
- O filtro de liquidez que gera o universo elegível em si (mediana de `VOLTOT` sobre 63
  pregões, uma classe por raiz) ainda não existe como código — só como script descartável
  usado nas medições anteriores. Vira código junto com a Seção 6.
- Cruzamento com cancelamento CVM para fechamento de vigência (mencionado no desenho
  original mas não exigido nesta rodada).
- 2011/2013 seguem não medidos (Seção 5.6).

## Decisão

- Aprovado por: Brian — pediu implementação como módulo antes da Seção 6, com três
  exigências explícitas (regressão da precisão auditada, regras da spec viram teste,
  mesmo relógio de `get_filing_as_of`) e o teste de aceite `KROT3`→`COGN3` como critério
  de fechamento (2026-08-20).
- Justificativa: a auditoria de 712 nunca cobriu `reconciliacao_nome` (só
  `fca`+`raiz_propagacao`) — rodar o módulo contra o universo real expôs isso e achou 4
  falsos positivos reais que a spec sozinha não capturaria; a mesma disciplina de medir
  em vez de presumir que fechou `EX` (Seção 5.3.2) e a fronteira 2015-2026 (Seção 5.6) se
  aplicou aqui, agora sobre código, não só sobre número.
