# 2026-08-19 — Fase 1 do módulo de Ações: fonte CVM verificada por acesso direto

## Contexto

Enquanto o teste de nulidade do bot rodava em background (janela fixa, purga + gate de
zero-perda + `total_pnl` aplicados), usuário pediu para desenhar a Fase 1 do módulo de
Ações (B3) em paralelo — trabalho independente, não toca em nada do bot ("é a fundação
que, se sair errada, invalida tudo que vier depois naquela frente").

## Verificação, não suposição

`specs/14-modulo-acoes-b3.md`, Seção 4, marcava CVM Dados Abertos como fonte candidata,
"disponibilidade, formato e ToS a verificar". Em vez de confiar na documentação do portal
(que não expõe colunas — só descreve o dataset em prosa), baixei o arquivo real:

```
curl https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_2024.zip
```

19 CSVs dentro (índice mestre + um por tipo de demonstração — BPA/BPP/DRE/DFC/DMPL/DRA/DVA,
cada um em con/ind — mais composição de capital e parecer). Confirmado o mesmo padrão de
URL para ITR.

## Achado principal: `DT_RECEB` existe, mas só no índice mestre

O campo de data de publicação que a Seção 5 da spec exige existe de verdade, com esse
nome exato, mas só no arquivo-índice (`dfp_cia_aberta_AAAA.csv`) — não nos arquivos de
item financeiro (`dfp_cia_aberta_DRE_con_AAAA.csv` etc.), que só têm `DT_REFER`. Contrato
de ingestão: join por `(CNPJ_CIA, DT_REFER, VERSAO)`.

Confirmado com dado real, dois exemplos do mesmo exercício (2024-12-31): Banco do Brasil
`DT_RECEB=2025-02-19` (lag de ~50 dias), BRB Banco de Brasília `DT_RECEB=2025-04-09`
(lag de ~100 dias) — o atraso varia por empresa, não dá para assumir um número fixo.

## Duas armadilhas de point-in-time que não estavam na spec original

1. **Comparativo `ORDEM_EXERC`**: cada filing traz o exercício atual (`ÚLTIMO`) e o
   anterior (`PENÚLTIMO`) na mesma linha de dado — o mesmo ano-fiscal aparece em dois
   filings diferentes, possivelmente com valor reapresentado, cada um com sua própria
   `data_publicacao`. Regra: só `ÚLTIMO` é fato point-in-time primário.
2. **`VERSAO`**: um filing pode ser retificado depois, com nova `DT_RECEB` posterior.
   Consulta point-in-time correta pega a maior `VERSAO` cujo `DT_RECEB <= data_da_decisão`
   — nunca a versão mais recente publicada até hoje.

Sem essas duas regras explícitas, um "join ingênuo" por `(CNPJ_CIA, DT_REFER)` sem
desambiguar `ORDEM_EXERC`/`VERSAO` produziria linhas duplicadas ou o valor errado de um
exercício, silenciosamente.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Nova Seção 5.1 (fonte CVM confirmada + contrato de ingestão) e 5.2 (contrato de consulta
point-in-time com SQL de exemplo + o teste de aceite exato, usando o dado real do Banco
do Brasil: consulta em 2025-02-18 não deve ver o exercício 2024-12-31, consulta em
2025-02-19 deve ver).

## Pendente, não verificado nesta rodada

- Até quando os arquivos anuais existem retroativamente (só 2024 foi baixado; o portal
  menciona "últimos 5 anos" para a descrição do dataset atual, mas isso pode não refletir
  quantos anos de arquivo `_AAAA.zip` realmente existem).
- Formato do FRE (Formulário de Referência).
- ToS do portal lido linha a linha (dados.gov.br costuma ser aberto, mas não confirmado
  explicitamente).
- Fonte de cotações (`brapi.dev`/`yfinance`) — Seção 4.2, não verificada nesta rodada.

Nenhum código de ingestão foi escrito — isto é desenho de spec, não implementação. Fase 1
segue "proposta inicial, não implementada".

## Decisão

- Aprovado por: Brian — "podemos desenhar a Fase 1 do módulo de ações em paralelo...
  Dispara e me diz — começamos pela Fase 1 enquanto o teste coleta" (2026-08-19).
- Justificativa: trabalho independente do bot, sem custo de esperar o teste de nulidade
  terminar; verificar a fonte por acesso direto (não pela documentação do portal) segue a
  mesma disciplina de "medir antes de declarar" do resto da sessão.
