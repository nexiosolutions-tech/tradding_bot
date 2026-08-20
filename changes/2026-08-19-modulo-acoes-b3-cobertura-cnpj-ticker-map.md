# 2026-08-19 — Módulo de Ações: cobertura do `cnpj_ticker_map` medida, schema corrigido em três pontos

## Contexto

Usuário aprovou a fonte encontrada na rodada anterior (FCA para identidade, COTAHIST para
vigência) mas apontou que ela trocava a *natureza* da fonte de vigência de um jeito que
abria três questões sem regra: vigência derivada de pregão não é a mesma coisa que
vigência de identidade; iliquidez pode fabricar fim de vigência falso; e o gap de
9-19% do FCA precisava da medição que decide se é tolerável ou crítico — cobertura sobre
o **universo elegível**, não sobre o FCA inteiro.

## Medição decisiva: o gap do FCA tem um corte temporal duro, não é ruído distribuído

Rodado o filtro de liquidez da Seção 6 contra COTAHIST e cruzado com os tickers presentes
no FCA, ano a ano, 2010–2025:

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

Achado: `Codigo_Negociacao` está **zero populado em todo o FCA até 2017 inclusive** — nem
a Petrobras tem o campo preenchido nesses anos (confirmado checando o CNPJ diretamente
nos arquivos de 2015, 2016 e 2017: a linha existe, o CNPJ existe, o campo do ticker vem
vazio nos três). Salta para 78% em 2018 (ano em que a CVM aparentemente passou a
exigir/capturar o campo de forma consistente) e sobe gradualmente daí.

Isso muda o significado do achado anterior de "9-19% precisa de reconciliação por nome
como fallback": **não é uma fração espalhada, são os primeiros 8 anos inteiros do
histórico (2010-2017, metade da janela CVM da Seção 5.1) em que a reconciliação por nome
é o único caminho, não um fallback.** Nenhum ano do período 2010-2022 chega ao piso de
95% que tornaria o gap tolerável sem mais rigor — reconciliação por nome nesse intervalo
inteiro precisa de auditoria manual, per critério definido antes de medir.

## Três correções de desenho no schema

1. **COTAHIST fornece as bordas, FCA fornece a costura — nunca derivar tudo da
   COTAHIST.** Primeira/última data de pregão de um ticker dão o intervalo em que aquele
   código negociou. Mas nada na COTAHIST sozinha garante que dois intervalos consecutivos
   (`KROT3` até 10/10/2019, `COGN3` a partir de 11/10/2019) pertencem ao mesmo CNPJ — do
   ponto de vista da COTAHIST, dois códigos com pregão contíguo são indistinguíveis de uma
   reatribuição de código a empresa diferente. Quem garante a costura é o FCA (ou a
   reconciliação por nome). Corrigido no schema: `fonte` marca a origem da *identidade*,
   nunca da vigência — a vigência sempre vem do COTAHIST, mas só é válida presa a uma
   identidade que veio de outro lugar.
2. **Tolerância de gap contra falso fim de vigência por iliquidez.** Papel pouco líquido
   pode passar semanas sem pregão sem sair da empresa; usar "última data de pregão" sem
   tolerância fecharia a vigência a cada pausa e abriria uma nova na retomada,
   fragmentando a identidade de tickers pequenos — a mesma população do vale setorial de
   2016 (Seção 7). Regra adotada: só fecha vigência após 180 dias corridos sem pregão
   (mesma ordem de grandeza da janela de 63 pregões ≈ 3 meses da Seção 6, com margem), e
   fechamento "de verdade" é cruzado com evento de cancelamento na CVM
   (`cad_cia_aberta.SIT`/`DT_INI_SIT`/`MOTIVO_CANCEL`, já usados na Seção 5.1) quando
   disponível — silêncio de pregão sozinho é evidência fraca, cancelamento CVM é forte.
3. **Decisão de saída declarada**: ticker que passa o filtro de liquidez mas não resolve
   para CNPJ (nem FCA nem reconciliação por nome) não entra no universo elegível daquela
   data — exclusão **contada explicitamente**, nunca subtraída em silêncio do
   denominador. Mesmo padrão já usado para histórico insuficiente (Seção 6), dado
   faltante de fator (Seção 7) e perda de liquidez (Seção 8).

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`, Seção 5.4

- Tabela de cobertura ano a ano.
- Achado do corte temporal (zero até 2017, salto em 2018) substituindo a leitura anterior
  de "9-19% disperso".
- As três correções de schema, com a distinção explícita entre fonte de identidade e
  fonte de vigência.
- Tolerância de gap de 180 dias + cruzamento com evento CVM.
- Decisão de saída declarada, com referência cruzada às três outras seções que já usam o
  mesmo padrão (omitir e registrar, nunca descartar em silêncio).

## Pendente

- Nenhum código de ingestão escrito — desenho de spec.
- Processo de reconciliação por nome para 2010-2017 (100% do período) e para o restante
  não resolvido por FCA depois de 2018 ainda não tem procedimento de auditoria manual
  definido — fica para quando a Fase 2 começar a ser implementada.
- Threshold de 180 dias para tolerância de gap é escolha inicial de desenho, não validada
  empiricamente contra um caso real de pausa de negociação longa — candidato a ajuste
  quando houver caso concreto para testar.

## Decisão

- Aprovado por: Brian — três questões levantadas a partir da correção do schema anterior:
  "vigência derivada de pregão não é vigência de identidade... a regra é: COTAHIST
  fornece as bordas, FCA fornece a costura"; "iliquidez cria falso fim de vigência...
  regra necessária: tolerância de gap"; "os 9-19% sem ticker precisam de rota, não só de
  fallback... a medição que decide isso é: dos tickers que passam o filtro de liquidez da
  Seção 6, quantos têm CNPJ resolvido?" (2026-08-19). Pediu também a decisão de saída
  declarada para ticker líquido sem CNPJ resolvido, "pela mesma razão do segundo canal de
  survivorship da Seção 8".
- Justificativa: a medição de cobertura sobre o universo elegível (não sobre o FCA
  inteiro) revelou um problema mais sério do que uma taxa de falha dispersa — um corte
  temporal duro que torna a reconciliação por nome obrigatória, não opcional, para metade
  do histórico. Descobrir isso agora, em spec, evita implementar um pipeline que assume
  FCA como fonte primária confiável e falha silenciosamente em oito anos de dado.
