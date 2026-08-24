# 2026-08-24 — Módulo de Ações: Seção 7, primeiro fator ponta a ponta (earnings yield)

## Contexto

Usuário nomeou a mudança de natureza da Seção 7: até aqui, fundação de dado (bate com a
fonte?); a partir daqui, decisão de modelagem (tem justificativa econômica ou é
mineração?). Pediu, na ordem: (0) ligar `b3_setor` ao universo, prerequisito para o
demeaning ter setor para agrupar; (1) um fator só, ponta a ponta, com winsorização e
fallback hierárquico de bucket; matriz de aplicabilidade e demais fatores ficam para
depois.

## Passo 0: `b3_setor` ligado a `build_universo_elegivel`

`UniversoElegivel` ganhou três colunas (`setor_b3`, `subsetor_b3`, `segmento_b3`),
preenchidas via `get_latest_b3_classification` (nova consulta em `b3_setor.py`) no
momento da materialização. Lado a lado com `setor_ativ` (CVM) — a Seção 7 decide qual
usar e como cair de um para o outro, a Seção 6 só materializa o que é conhecido de cada
fonte, nunca escolhe por ela. Testado com o mesmo universo de 2016-07-15 já fechado
(`ITUB4`/`BBAS3` → `Financeiro`/`Bancos`, `PETR4` → `Petróleo. Gás e Biocombustíveis`) e
com um caso de fallback declarado (sessão sem snapshot B3 ingerido → `None`, nunca
adivinhado).

## Passo 1: earnings yield ponta a ponta

**Fonte do lucro por ação verificada antes de escrever a fórmula** — o receio inicial era
precisar de ações em circulação (fonte nova, não verificada) para earnings yield = lucro
por ação / preço. Achado real: a DRE consolidada da CVM já reporta `CD_CONTA`
`"3.99.01.01"`/`"3.99.01.02"` = Lucro Básico por Ação, direto, separado por classe
(ON/PN) — não precisa derivar nada. Confirmado contra o arquivo real
`dfp_cia_aberta_DRE_con_2015.csv`, três empresas: Itaú (ON=PN=R$4,30), Banco do Brasil
(ON=R$5,03, só tem classe ON) e **Petrobras (ON=PN=-R$2,67, prejuízo real do exercício
2015)** — o caso que earnings yield existe para tratar sem inverter sinal.

`backend/src/tradingbot/acoes/fatores.py`:

- `get_eps_as_of(session, cnpj, ticker, data_decisao)` — usa `get_latest_filing_as_of`
  (Seção 6.1) para achar o balanço visível na data, busca o `CD_CONTA` da classe do
  ticker pelo sufixo numérico.
- `earnings_yield_raw(eps, preco)` — `eps/preco`, direto.
- `winsorize(values, lower_pct, upper_pct)` — corta caudas antes de qualquer média
  setorial.
- `compute_demeaned_percentiles(items, min_bucket_size=3)` — winsoriza, demeans pelo
  bucket mais fino com população mínima subindo `segmento` → `subsetor` → `setor` →
  universo inteiro, percentil da série demeaned sobre o universo inteiro. Dado faltante
  (`raw_value=None`) imputado pela mediana do universo, nunca excluído — regra declarada
  e implementada, cada resultado registra `imputado` e `bucket_usado` para auditoria.

## Bug achado e corrigido antes de chegar a produção

`winsorize` usava índice de percentil por truncamento (`int`). Para `n=3` (o tamanho real
do universo de teste) e `upper_pct=0,99`: `int(0,99*2)=1`, o índice do valor do **meio**,
não do máximo (`round(0,99*2)=2`) — cortando incorretamente o maior valor de uma amostra
pequena antes mesmo de rodar qualquer teste real. Corrigido para arredondamento
(`round`). Consequência correta do fix: amostra pequena (o caso comum medido na Seção
6.2) não perde nada aos percentis 1/99 por construção — só corta cauda quando a amostra é
grande o suficiente para o percentil não colapsar no extremo. Teste de regressão
explícito (`test_winsorize_amostra_pequena_nao_corta_extremos`) trava o caso `n=3`.

## Teste de aceite: earnings yield real, mesma data e universo da Seção 6

Fixture nova: `tests/fixtures/cvm/dre_con_2015_itub_bbas_petr_eps_real_extract.csv` (5
linhas reais, `CD_CONTA` `3.99.01.01`/`.02`, exercício 2015). Preço real reusado da
fixture já comitada da Seção 6 (`COTAHIST_A2016_universo_real_extract.ZIP`): fechamento
em 2016-07-15 — `ITUB4`=R$33,46, `BBAS3`=R$19,26, `PETR4`=R$11,02.

Resultado: `ITUB4` e `BBAS3` com earnings yield positivo, **`PETR4` negativo e na ponta
inferior do ranking demeaned/percentil** — o prejuízo real de 2015 não inverte o sinal.
Com só três empresas no universo desta fixture, nenhum nível da hierarquia setorial
atinge a população mínima sozinho — todas caem no bucket `universo`, resultado real e
esperado dado o tamanho do universo aqui, não um bug (o fallback hierárquico em si foi
testado à parte com caso ilustrativo do mecanismo — dois segmentos pequenos dentro do
mesmo setor, provando a subida `segmento`→`subsetor`→`setor` — documentado como
mecanismo, não como fato de mercado).

## Testes novos

`backend/tests/test_acoes_fatores.py`, 8 testes: EPS real das três empresas (inclusive
`None` antes da publicação); earnings yield não inverte sinal negativo; regressão do bug
de winsorização (`n=3`); winsorização corta cauda com amostra grande; ponta a ponta real
2016-07-15 (Petrobras no fundo do ranking); fallback hierárquico isolado; dado faltante
imputado pela mediana, não excluído. Mais 3 testes atualizados em
`test_acoes_universo_elegivel.py`/`test_acoes_b3_setor.py` para o passo 0 (setor B3 ligado
ao universo, terceira empresa real — Banco do Brasil — adicionada ao fixture de
classificação B3). 402 testes passam na suíte completa (394 + 8 novos), zero regressão.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Seção 7 reescrita: normalização com winsorização + fallback hierárquico (substituindo o
bucket "outros" simples anterior), regra de dado faltante marcada como implementada, nota
do piso setorial atualizada para apontar às três medições convergentes da Seção 6.2 em
vez de repetir só o 22/27 direcional antigo. Nova Seção 7.1 documenta a implementação do
earnings yield, o bug do winsorize e o teste de aceite. Seção 12 (Fase 3) atualizada.

## Pendente

- Matriz de aplicabilidade de fator por setor — earnings yield se aplica a todo setor
  (bancos incluídos), não exercita o ramo "inaplicável"; próximo passo, testado com um
  banco e uma industrial.
- Demais famílias de fator (Qualidade, Saúde financeira, Crescimento, Momentum, Tamanho)
  — cada uma com justificativa econômica própria antes de entrar, não implementadas.
- Composição do score — só depois dos fatores individuais saírem certos (instrução
  explícita do usuário: fatiar, não construir tudo de uma vez sobre suposição).
- Universo de teste com só 3 empresas nunca exercita um bucket de `segmento`/`subsetor`
  real com população suficiente — mecanismo provado à parte, não com dado de mercado
  desta escala ainda.

## Decisão

- Aprovado por: Brian — nomeou a mudança de natureza da Seção 7 (fundação de dado →
  decisão de modelagem), pediu winsorização e fallback hierárquico como guardas
  obrigatórias contra bucket pequeno, a distinção formal entre dado faltante e fator
  inaplicável, e a sequência de fatiamento (setor→um fator→matriz→demais fatores→
  composição) "para não construir tudo de uma vez sobre suposição" (2026-08-24).
- Justificativa: earnings yield sobre as três empresas reais que já fecharam a Seção 6
  expôs um bug real (`winsorize` com índice por truncamento) antes de qualquer fator
  entrar em produção — exatamente o valor de "ver o número real sair para uma empresa
  conhecida antes de generalizar" que o usuário pediu; o caso real da Petrobras
  (prejuízo genuíno de 2015) validou o motivo econômico da métrica, não só a mecânica.
