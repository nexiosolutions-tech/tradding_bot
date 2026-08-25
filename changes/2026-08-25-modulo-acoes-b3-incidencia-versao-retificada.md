# 2026-08-25 — Módulo de Ações: incidência de versão retificada medida, decisão de desenho para o gate

## Contexto

A Seção 7.4 achou que os arquivos de item da CVM só têm a versão mais recente retificada
de cada filing, não a que estava vigente numa data de decisão passada — 10 dos 34 casos
de fator ausente em 2016 vieram daí. Usuário pediu, antes de aceitar como limitação
tolerável: (1) verificar se existe fonte alternativa que dê acesso ao conteúdo da versão
antiga; (2) medir a incidência por ano **e** o perfil de quem cai nesse buraco (tamanho,
setor); (3) reportar `n` efetivo total (não só a incidência do problema específico) contra
o piso de 85% já usado para identidade — porque esse é o número que de fato decide se o
ano sustenta ranking transversal confiável.

## Fonte alternativa: verificada, não presumida indisponível

O índice mestre carrega `ID_DOC`/`LINK_DOC` por versão, apontando para
`rad.cvm.gov.br` — testado contra o caso real do Banco do Brasil (versão 1,
`NumeroSequencialDocumento=53614`). O link antigo (`ENET/frmDownloadDocumento.aspx`)
está morto; o sistema migrou para `ENETWeb` (busca via WebSearch confirmou a migração em
06/07/2026). A página nova carrega (200 OK, ~700KB de HTML) mas é uma aplicação ASP.NET
WebForms orientada a sessão — `__VIEWSTATE`/`__EVENTVALIDATION` presentes, sem endpoint
de download direto por HTTP simples. Recuperar o conteúdo de uma versão antiga exigiria
simular navegação interativa (postback por empresa/documento), uma integração ordens de
magnitude mais cara que o portal de dados abertos usado no resto da spec, com formato de
documento provavelmente diferente (XBRL/PDF) exigindo extração própria.

**Fechado com a mesma disciplina que fechou o código interno da CVM sem par derivável
(Seção 5.6): existe em princípio, testado, não é viável em lote dentro de esforço
razoável — não presumido indisponível sem checar.**

## Reconstrução do ambiente (scratchpad sobreviveu desta vez, mas faltava 2014)

O universo de 2015-02-27 inicialmente veio com **N=0** — todas as 393 empresas excluídas.
Diagnosticado: `historico_insuficiente` (127) e `iliquido` (240) dominavam, porque só
COTAHIST 2015+2016 estava ingerido, e uma data de decisão em fevereiro de 2015 precisa de
histórico anterior (janela de 63/252 pregões) que só existe voltando a 2014. Ingerido
COTAHIST 2014 (72.401 linhas, contagem verificada byte a byte contra o arquivo bruto —
mesma disciplina de sempre). Universo recalculado: **N=125** para 2015-02-27.

## Medição de incidência e perfil — dois anos reais

| | 2015-02-27 | 2016-02-29 |
|---|---|---|
| Universo (N) | 125 | 115 |
| Versão divergente (qualquer fator) | 9 (7,2%) | 10 (8,7%) |
| `n` efetivo — os dois fatores presentes | 88 (70,4%) | 81 (70,4%) |
| `n` efetivo — pelo menos um fator presente | 106 (84,8%) | 97 (84,3%) |

**Incidência estável entre os dois anos, não uma escalada** — os dois estão igualmente
distantes de hoje (2026), consistente com o mecanismo esperado (o efeito cresce com o
tempo decorrido desde a decisão até hoje, não com a "idade" do ano em si).

**Perfil de tamanho: sem viés.** Mediana de `VOLTOT` das empresas com versão divergente
não difere sistematicamente do universo geral (2015: R$11,4M vs. R$11,8M; 2016: R$21,2M
vs. R$12,3M — se algo, mais líquidas). Não é o viés "empresa pequena e obscura" que a
hipótese de trabalho cogitava.

**Perfil de setor: viés real e forte.** Bancos são 5 dos 9 casos (2015) e 5 dos 10
(2016) — mais da metade das ausências por versão divergente, contra ~14% de participação
de bancos no universo total. Não aleatório. Atinge justamente o setor onde ROE se aplica
(diferente de dívida líquida/EBITDA, inaplicável a banco por desenho) — uma fração maior
dos ROEs de banco no bucket setorial da Seção 7.3 vem de imputação pela mediana, não de
dado próprio.

## A decisão de desenho que os números forçam

Exigir os dois fatores presentes trava `n` efetivo em 70,4% nos dois anos — abaixo de
qualquer piso razoável. Permitir score composto parcial (pelo menos um fator, via a
renormalização já implementada em `compute_score_composto`, Seção 7.2) sobe para
84,3-84,8% — na fronteira do piso de 85% já usado para identidade (Seção 5.6), não
folgado, mas muito mais perto de sustentar ranking transversal confiável.

**Recomendação registrada para a Seção 10 (gate de promoção), decisão não tomada
aqui**: aceitar score composto com fatores parciais como caminho padrão da composição,
não como exceção. A alternativa (exigir todos os fatores) descarta ~30% do universo nos
dois anos medidos por um motivo que não é sobre a qualidade da empresa avaliada — é sobre
disponibilidade de versão retificada na fonte.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

Nova Seção 7.5: a verificação da fonte alternativa (negativa, mas testada), a tabela de
incidência/perfil dos dois anos, o achado da concentração setorial em bancos (com a
ressalva correspondente à Seção 7.3), e a recomendação de desenho para a Seção 10.

## Pendente

- Confirmar se 84-85% se sustenta (ou sobe) em anos mais recentes da era avaliável
  (2024-2026) antes de fechar o piso definitivo — não medido nesta rodada, depende da
  ingestão completa 2015-2026 (item 2 da sequência do usuário, precisa do fix de
  performance do savepoint-por-linha primeiro).
- Diagnóstico opcional (ROE/earnings yield com a versão errada, só para comparação,
  nunca para uso) não feito — a concentração setorial já foi sinal suficiente para a
  ressalva sem precisar dele.
- Correlação de três vias incluindo dívida líquida/EBITDA (Seção 7.4, pendência já
  registrada).

## Decisão

- Aprovado por: Brian — pediu a verificação de fonte alternativa antes de aceitar a
  limitação, a medição de incidência **e** perfil (não só o número, porque retificação
  não é aleatória), e o `n` efetivo total contra o piso de 85% como o número que de fato
  decide o desenho, não a incidência isolada (2026-08-25).
- Justificativa: a concentração em bancos (mais da metade das ausências, ~4x a
  participação de bancos no universo) é um achado real que a medição por tamanho sozinha
  teria escondido — confirma por que "perfil de quem cai" era a pergunta certa, não só
  "quantos caem". E o contraste 70,4% (exigindo os dois fatores) vs. 84,3-84,8%
  (aceitando parcial) transforma uma limitação de fonte numa decisão de desenho concreta
  para a Seção 10, com o número que a sustenta, não uma preferência.
