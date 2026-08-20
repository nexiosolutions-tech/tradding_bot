# 2026-08-19 — Módulo de Ações: normalização por demeaning, prioridade do cnpj_ticker_map, poder de fold fechado

## Contexto

Usuário puxou a consequência completa do achado do piso setorial (22/27 setores abaixo do
mínimo no vale de 2016, `changes/2026-08-19-modulo-acoes-b3-secao-8-e-piso-setorial.md`):
não é só um número para registrar, é um achado que quebra a construção estatística da
normalização da Seção 7. Quatro correções nesta rodada.

## 1. Percentil-dentro-do-setor não sobrevive a bucket pequeno — trocado por demeaning

Percentil sobre 4 empresas não é estatística, é ordenação de quatro pontos. E o achado do
piso setorial mostra que bucket pequeno não é caso raro na B3 — é o normal. Correção
adotada (padrão em quant): **percentil sobre o universo elegível inteiro, com
neutralização (demeaning) setorial** — subtrair a média do setor de cada métrica, depois
tomar percentil da série demeaned no universo inteiro, em vez de tomar percentil dentro do
setor. A diferença estrutural: demeaning só precisa estimar a **média** do setor
(razoável com 3-4 nomes), percentil-dentro-do-setor precisa da **distribuição inteira**
(não razoável com poucos nomes). Mantém o objetivo original (não comparar P/L de banco com
o de mineradora) sem exigir população que a B3 não tem. Piso de 3 nomes para estimar
média; abaixo disso, bucket "outros" sem neutralização específica — nunca descarte.

Isto substitui a versão anterior da Seção 7 (percentil-dentro-do-setor com fallback de
agregação), registrada há poucas horas na mesma sessão — corrigida antes de qualquer
código ser escrito sobre ela.

## 2. Dois números, não um: direção justifica arquitetura, magnitude não calibra parâmetro

Usuário identificado corretamente um problema que a rodada anterior não tinha isolado:
`SETOR_ATIV` da CVM é mais granular que a classificação B3 real que a Seção 7 assume para
produção, e o casamento por nome (73%) não falha aleatoriamente — empresa que trocou de
nome, foi incorporada ou é pequena/antiga tem mais chance de não casar, exatamente o
perfil que preenche setor pequeno. O 22/27 pode estar sub ou superestimado, direção
desconhecida.

Registrado explicitamente na Seção 7: o número **justifica a mudança de arquitetura**
(demeaning em vez de percentil-dentro-do-setor — a direção e a magnitude qualitativa do
achado são fortes o bastante para isso), mas **não calibra nenhum piso** — o piso de 3
nomes é escolha de desenho independente, a revisar quando a classificação B3 real e o
`cnpj_ticker_map` existirem.

## 3. cnpj_ticker_map: de peça do join de preço para pré-requisito do scoring inteiro

O casamento por nome usado nesta medição é o mesmo tipo de aproximação que o
`cnpj_ticker_map` (Seção 5.1, pendência de Fase 2) existe para eliminar — só que agora o
gap não afeta só o join fundamento×preço, afeta a atribuição setorial da qual a
normalização inteira da Seção 7 depende. Registrado na Seção 5.1 como prioridade elevada,
mesmo texto continuando a apontar Fase 2 como o momento de implementação (não subiu de
fase, subiu de "por que importa").

## 4. Lacuna de poder entre folds fechada com critério verificável, não ponderação nova

Em vez de teoria de ponderação por N transversal (mais complexa, mais um parâmetro para
calibrar), fechado com o que já estava disponível: Seção 9 passou a exigir que cada fold
reporte o N transversal do período (mínimo/mediano/máximo); Seção 10 critério 1 passou a
só contar, na régua de 70% dos folds vencidos, folds cujo N transversal mediano atinja o
piso do critério 2. Fold inteiro num vale de liquidez deixa de contar como evidência
equivalente a um fold de pico, sem precisar de mecanismo novo. Seção 13 atualizada de
"lacuna conhecida, não resolvida" para o critério fechado.

## O que ficou registrado em `specs/14-modulo-acoes-b3.md`

- Seção 7: normalização reescrita (demeaning), parágrafo do piso setorial reescrito
  separando achado direcional de número calibrado.
- Seção 5.1: nota de prioridade elevada no `cnpj_ticker_map`.
- Seção 9: N transversal por fold nas métricas reportadas.
- Seção 10: critério 1 só conta folds com N transversal adequado; critério 2 e nota do
  critério 5 ajustadas para a nova normalização.
- Seção 13: bullet do piso setorial reescrito (referência à nova arquitetura, não mais ao
  "fallback de agregação"); bullet de poder de fold marcado como fechado.

## Pendente, não resolvido nesta rodada

- Classificação setorial B3 real (a medição segue usando `SETOR_ATIV` da CVM como proxy).
- `cnpj_ticker_map` — ainda não implementado, só priorizado.
- Nenhum código de produção escrito — desenho de spec.

## Decisão

- Aprovado por: Brian — "22 de 27 setores abaixo do piso é um achado que muda desenho, não
  só um número para registrar. Vale puxar a consequência inteira" (2026-08-19), com as
  quatro correções especificadas: demeaning em vez de percentil-dentro-do-setor, separar
  achado direcional de calibração, subir prioridade do `cnpj_ticker_map`, fechar a lacuna
  de poder entre folds com critério verificável em vez de teoria nova.
- Justificativa: a arquitetura de normalização anterior (percentil-dentro-do-setor) não
  sobreviveria ao dado real da B3 — melhor corrigir agora, em spec, do que depois de
  implementada. A separação de "direção justifica arquitetura" vs. "magnitude calibra
  parâmetro" evita que um número medido contra a taxonomia errada vire piso de produção
  por acidente.
