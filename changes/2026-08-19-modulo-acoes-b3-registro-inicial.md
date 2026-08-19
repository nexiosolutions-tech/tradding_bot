# 2026-08-19 — Registro inicial do módulo de Ações (B3)

## Contexto

Usuário trouxe uma spec pronta para um segundo módulo, independente do bot de cripto:
apoio à decisão de aporte mensal em ações da B3 (evidência e ranking, não execução de
ordens). Pedido: revisar e registrar a spec antes de prosseguir com o resto da fila do
bot.

## Colisão de numeração

Arquivo chegou como `specs/spec-08-modulo-acoes-b3.md`. `08` já é
`specs/08-dashboard-e-visualizacao.md`. Renomeado para `specs/14-modulo-acoes-b3.md`
(próximo número livre) e cabeçalho interno corrigido (`# Spec 08 —` → `# 14 —`) para
bater com a convenção dos demais arquivos.

## Contradição real entre Seção 10 e Seção 13, corrigida

Achado na primeira revisão: Seção 13 pede margem maior no gate por causa de amostra
pequena (poucas centenas de empresas líquidas na B3); Seção 10, critério 1, pedia
vitória em "maioria dos folds" — mais frouxo que o `all(...)` que `promotion.py` exige
no bot, e mais frouxo exatamente onde a Seção 13 pede mais rigor.

Correção do usuário, não a que eu tinha sugerido (trocar "maioria" por "todos"): a
contradição vinha de **confundir dois eixos de amostra diferentes**.

- **Amostra transversal** — quantas empresas líquidas existem em cada data de decisão.
  Pequena na B3 (poucas centenas). É o eixo da Seção 13.
- **Número de folds temporais** — quantos períodos de validação existem. Função de
  quantos anos de histórico CVM estão disponíveis, não do tamanho do universo.
  Potencialmente abundante (15-20 anos de dado).

Exigir vitória em todos os folds temporais faz sentido no bot (folds de 45 dias, mesmo
regime de mercado — teste de consistência razoável) mas não em ações com rebalanceamento
mensal: cada fold atravessa regimes macro completos, e fatores têm secas plurianuais
documentadas (valor perdeu de crescimento por mais de uma década em alguns períodos).
"Todos os folds" reprovaria qualquer conjunto de fatores genuíno — erro tipo II por
desenho, e redundante com o teste de nulidade (p<0,05) e o DSR, que já fazem o trabalho
de significância estatística.

**Correção aplicada em `specs/14-modulo-acoes-b3.md`, Seção 10:**

1. Critério de robustez por fold reformulado: vencer o equal-weight em ≥70% dos folds
   (mínimo 8 folds), nenhum fold com degradação de drawdown além do limite — espelha a
   checagem de degradação de `promotion.py`, mas como teste de robustez, não como régua
   de unanimidade.
2. Critério novo, que opera o eixo certo (transversal): universo elegível com mínimo de
   N empresas em toda data de decisão, margem sobre o equal-weight escalada
   inversamente ao tamanho do corte transversal — quanto menor o universo, maior a
   margem exigida.
3. Seção 13 reescrita: "exigir margem maior no gate" → "exigir margem maior na
   comparação transversal", para não voltar a ser lida como regra de fold.

## Duas correções menores

- **Seção 11** (interface): adicionado cross-link explícito para
  `08-dashboard-e-visualizacao.md` — o "menu Ações" estende o mesmo app do dashboard do
  bot, não é uma aplicação separada; a dependência de UI não estava explícita antes.
- **Seção 3** (princípios herdados): nova linha sobre `learning_engine/experiment_log.py`
  — componente reaproveitado do bot, mas com campo de domínio na entrada e contadores
  separados por módulo. O N do DSR é específico do problema; tentativas de um módulo não
  podem inflar (nem ser infladas por) o viés de seleção de tentativas do outro.

## Registro em specs/00 e CLAUDE.md, com ressalva de independência explícita

A pedido do usuário, para reduzir o risco de uma sessão futura (inclusive minha) cruzar
conclusões entre os dois módulos:

- `specs/00-visao-geral-e-objetivos.md`: nova seção "Segundo módulo: apoio à decisão de
  aporte em ações (B3)", com a frase — "Decisões, resultados e conclusões de um módulo
  não transferem para o outro."
- `CLAUDE.md` ("O que este projeto é"): parágrafo adicional apontando para
  `specs/14-modulo-acoes-b3.md`, com a mesma ressalva: fundação de engenharia
  compartilhada (ingestão, validação, gate, `changes/`), nunca estado, dado, modelo ou
  runtime.

## Pendente

Spec permanece "proposta inicial, não implementada" — nenhum código desta frente foi
escrito nesta rodada. Fase 1 (`specs/14`, Seção 12: ingestão CVM + cotações + camada
point-in-time) seguirá quando o usuário autorizar o início da implementação. Fontes de
dado (CVM Dados Abertos, `brapi.dev`/`yfinance`, BCB SGS, IBGE) seguem candidatas, não
verificadas — primeiro passo real de Fase 1 é confirmar disponibilidade/formato/ToS de
cada uma.

## Decisão

- Aprovado por: Brian (usuário, dono do projeto) — trouxe a spec pronta e pediu revisão
  e registro antes de prosseguir com a fila do bot ("Antes de prosseguirmos, atue na
  nova spec"). Corrigiu minha primeira proposta de correção (trocar "maioria" por
  "todos") explicando os dois eixos de amostra, e especificou o texto exato da ressalva
  de independência para `specs/00`/`CLAUDE.md`.
- Justificativa: registrar a existência do módulo antes de qualquer implementação evita
  que decisões de escopo fiquem só na conversa; a ressalva de independência é
  estrutural — sem ela, um agente futuro (humano ou IA) poderia razoavelmente presumir
  que um achado do bot de cripto (ex.: um bug de purga) se aplica automaticamente ao
  módulo de ações sem verificação própria.
