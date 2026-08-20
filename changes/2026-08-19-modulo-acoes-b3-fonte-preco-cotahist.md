# 2026-08-19 — Módulo de Ações: fonte de preço verificada, COTAHIST vira primária

## Contexto

Continuação do desenho da Fase 1: com a CVM confirmada (Seção 5.1/5.2), o próximo bloco
era a Seção 4.2 (cotações) — as Seções 6 (universo elegível, filtra por liquidez) e 7
(fatores, precisam de preço ajustado) dependem diretamente desse contrato, então escrevê-las
antes seria escrever contra um contrato desconhecido.

## Hipótese testada, não assumida: B3 publica preço histórico oficial (`COTAHIST`)

Mesma disciplina da CVM — baixar o arquivo real em vez de confiar em documentação de
terceiro:

```
curl https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A2024.ZIP
```

Mais o layout oficial (`SeriesHistoricas_Layout.pdf`, extraído com `pdftotext`, já que o
fetch inicial não conseguiu ler o PDF).

## Checklist rodado ponto a ponto (a mesma lista sugerida antes de rodar)

1. **Ticker deslistado** — o teste mais decisivo. `OGXP3` (OGX, faliu ~2014) presente no
   arquivo de 2013, ausente em 2024: cada arquivo anual é imutável, snapshot do que foi
   negociado naquele ano. Testado o oposto em `brapi.dev`: `PETR4` responde sem token,
   `OGXP3` e um ticker inválido (`XYZW9`), com os mesmos parâmetros, devolvem
   `"Token de autenticação não fornecido"` — evidência de allowlist no plano gratuito.
2. **Bruto vs. ajustado** — confirmado bruto (layout não tem campo de ajuste; documentação
   do produto declara "sem ajuste para inflação ou distribuições").
3. **Volume** — dois campos separados no layout: `QUATOT` (quantidade) e `VOLTOT`
   (financeiro, R$) — o que o filtro de liquidez da Seção 6 precisa.
4. **Retroatividade** — confirmado até 1986 por sondagem de URL.
5. **Cobertura** — arquivo é dump de tudo que negociou (ações + fundos + opções + etc.),
   não só líquidos; `OGXP3` no item 1 já é evidência disso.
6. **Limites/ToS** — arquivo estático, sem token, sem rate limit encontrado; ToS não lido
   linha a linha (mesma ressalva já registrada para a CVM).
7. **Sanidade contra evento conhecido** — não executado nesta rodada (a confirmação de
   "bruto" pelos itens 2 e a ausência de campo de ajuste no layout oficial já cobrem a
   pergunta que esse teste responderia).

## Achado que fica em aberto

Não existe arquivo bulk oficial e gratuito da B3 para proventos/desdobramentos,
equivalente ao COTAHIST — só produtos de API, pagos ou de terceiro. `brapi.dev` devolve
proventos reais (`dividendsData.cashDividends`, com data de aprovação e de pagamento) para
tickers líquidos atuais, sem token — mas sujeito à mesma limitação de allowlist do item 1
para histórico completo de empresas hoje deslistadas. Registrado como o item mais aberto
da camada de preço, decisão adiada para perto do início real da Fase 1.

## Veredito, registrado em `specs/14-modulo-acoes-b3.md` (Seção 5.3, 4.2)

COTAHIST vira fonte primária de preço (bruto + volume + universo completo, survivorship
resolvido na origem). `brapi.dev` rebaixado a conveniência (proventos recentes de tickers
líquidos). `yfinance` descartado — COTAHIST cobre tudo que ele cobriria, com menos risco
de ToS e sem o problema de série pré-ajustada que o "adjusted close" do Yahoo tem.

Nenhum código de ingestão escrito — desenho de spec. Fase 1 segue não implementada.

## Decisão

- Aprovado por: Brian — pediu a verificação de cotações com a mesma régua da CVM, alertou
  para dois riscos concretos antes de eu rodar (survivorship em API gratuita, e o
  "adjusted close" sendo o mesmo problema do `VERSAO` da CVM em outra forma), e sugeriu o
  candidato `COTAHIST` como teste a rodar junto — "se funcionar, resolve survivorship e
  ajuste de uma vez... o análogo exato do que a CVM é para fundamento" (2026-08-19).
- Justificativa: as duas armadilhas apontadas eram reais e mensuráveis — testadas
  diretamente (não descartadas por suposição), e a hipótese do `COTAHIST` se confirmou em
  todos os itens exceto proventos, que ficou registrado como aberto em vez de assumido
  resolvido.
