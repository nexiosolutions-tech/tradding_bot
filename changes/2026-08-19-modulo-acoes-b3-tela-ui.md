# 2026-08-19 — Módulo de Ações: tela do dashboard detalhada

## Contexto

Enquanto o teste de nulidade do bot ainda rodava em background, usuário pediu para
avançar a spec da interface do módulo de Ações (Seção 11 de `14-modulo-acoes-b3.md`),
que até então era só uma lista de 5 telas em uma linha cada.

## Achado antes de escrever: `CoinSelector` não serve para isto

Lendo `08-dashboard-e-visualizacao.md` para não desenhar a UI no vácuo: o dashboard já
tem um `CoinSelector` (introduzido no redesign de 2026-08-18), mas ele escolhe um **par
dentro do módulo cripto** (BTC/USDT vs. ETH/USDT) — não serve para alternar entre o
módulo cripto inteiro e o módulo de Ações, que são dois conjuntos de telas totalmente
diferentes, sobre dado independente (disclaimer de `specs/00`). Precisa de um seletor de
nível acima do `CoinSelector`, que troca o conteúdo inteiro da sidebar. Registrado como
nova seção em `08-dashboard-e-visualizacao.md` ("Seletor de módulo"), com o mesmo
princípio já usado para o `CoinSelector` quando foi introduzido: placeholder estrutural
primeiro, sem lógica de troca real até o módulo de Ações ter dado pra mostrar.

## As 5 telas, detalhadas

Cada uma ganhou uma subseção em `14-modulo-acoes-b3.md`, no mesmo nível de detalhe que
`08-dashboard-e-visualizacao.md` já usa para as views do bot (o que aparece, de onde vem
o dado, qual seção da spec 14 cada elemento implementa) — não mockup de UI, contrato de
conteúdo:

- **Painel do aporte do mês**: ranking + decomposição por fator + exposição
  antes/depois + alerta de concentração + sugestão de aporte + nota fiscal — com destaque
  visual próprio para o disclaimer de não-recomendação, por ser a tela mais
  decision-facing das cinco.
- **Ficha do ativo**: fundamentos com `data_publicacao` visível ao lado de cada número
  (não só o valor — a garantia point-in-time da Seção 5 precisa ser legível pelo usuário,
  não só correta internamente), proventos, posição em cada fator ao longo do tempo, preço
  ajustado (reusa o componente de chart do módulo cripto — infraestrutura de UI
  compartilhada, dado não).
- **Minha carteira**: composição de entrada manual (não há corretora integrada),
  exposição setorial, concentração, evolução vs. os 4 benchmarks obrigatórios da Seção 9.
- **Transparência**: fontes, frescor, falhas de coleta — equivalente funcional da view
  "Aprendizado" do bot, mas sobre proveniência de dado.
- **Histórico de decisões**: snapshot congelado do ranking de cada mês (precisa ser
  persistido no momento da geração, não recalculável depois) + retorno realizado —
  o que torna a Seção 14 ("expectativa calibrada") verificável, não só uma afirmação.

## Pendente

Ainda é desenho de spec — nenhum componente de frontend ou endpoint foi criado. Depende
das Fases 1-3 de `14-modulo-acoes-b3.md` (ingestão point-in-time, universo elegível,
fatores) antes de qualquer tela ficar funcional.

## Decisão

- Aprovado por: Brian — "gostaria de dar andamento à spec relacionada à tela de ações que
  iremos trabalhar dentro do projeto concomitantemente ao bot" (2026-08-19), enquanto o
  teste de nulidade do bot rodava em paralelo.
- Justificativa: trabalho de spec, independente do bot; ler a arquitetura real do
  dashboard existente antes de desenhar a extensão evita propor algo que não encaixa no
  app real (achado do `CoinSelector` só apareceu por causa disso).
