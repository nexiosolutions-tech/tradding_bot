# Change Proposal — 2026-08-01 — Motor de aprendizado contínuo vira loop agêntico (investigação autônoma, aplicação continua humana)

**Status:** aplicada

## Evidência (origem)
- Ligada a: discussão do usuário sobre estruturar um agente por continuidade
  (modelo de raciocínio + ferramentas + memória de estado + controlador de
  loop) e o desejo explícito de aplicar esse padrão dentro do próprio
  `tradding_bot`, evoluindo o motor de aprendizado contínuo da Fase 5.
- Estado atual do motor (`learning_engine/daily_report.py`,
  `change_proposals.py`): job único, síncrono, sem nenhum LLM envolvido —
  heurística fixa (`win_rate < 35%` numa hora UTC) e proposta de `changes/`
  rascunhada sem validação embutida. Não é um loop, é um script que roda uma
  vez e para.
- **Pedido inicial do usuário foi além do que o projeto permite**: que o
  motor não só analisasse, mas também *aplicasse* decisões sem intervenção
  humana. Isso colide diretamente com `CLAUDE.md` regra 6 ("O motor de
  aprendizado contínuo pode propor essas mudanças via `changes/`, nunca
  aplicá-las sozinho em produção") e com a instrução do próprio `CLAUDE.md`
  de parar e perguntar em vez de contornar uma regra de segurança. Recusei
  implementar isso e propus a alternativa abaixo, que o usuário aprovou.

## Proposta
- `specs/09-aprendizado-continuo.md` reescrita: a fronteira autônomo/humano
  deixa de ser "análise vs. ação" e passa a ser **"proposta pronta vs.
  aplicada"**. Tudo até gerar uma entrada completa e validada em `changes/`
  (formular hipótese, rodar backtest/sweep/SHAP, validar contra os critérios
  estatísticos de `specs/07`, redigir proposta + rascunho de spec + diff de
  código + testes, abrir PR numa branch dedicada) pode ser autônomo. Marcar
  a proposta como `aprovada`/`aplicada` e fazer merge em `main` continua
  exclusivamente humano.
- Novas invariantes estruturais explícitas na spec (mesmo padrão das regras
  não-negociáveis do `CLAUDE.md`): o loop nunca tem credenciais de execução
  (`BINANCE_API_KEY`/`SECRET`), nunca escreve em `main`, nunca marca sua
  própria proposta como aprovada, e roda com orçamento de iterações finito
  por ciclo.
- Nova peça de memória de estado: índice de experimentos (formato a definir
  na implementação) para o loop nunca repetir uma investigação já feita.
- `changes/README.md` atualizado: quando a proposta vem do loop autônomo, a
  seção "Validação proposta" deve conter o resultado real já rodado, não uma
  promessa de validação futura — a revisão humana julga um resultado pronto.
- **O que este change explicitamente NÃO faz**: não implementa nenhum
  código do loop ainda — é mudança de spec primeiro, por SDD
  (`CLAUDE.md`: "nenhuma funcionalidade é implementada sem uma spec
  correspondente"). O motor atual (`daily_report.py`/`change_proposals.py`)
  continua funcional e será reaproveitado como uma das ferramentas do loop,
  não descartado.

## Classificação de risco da mudança
- [x] Mudança de arquitetura (requer processo SDD completo) — reescreve o
  contrato do motor de aprendizado contínuo.
- Não é mudança de parâmetro de risco/execução em si — mas define a
  arquitetura que vai governar como *futuras* mudanças de risco/execução são
  descobertas e propostas, por isso o cuidado extra na revisão da fronteira
  autônomo/humano.

## Validação proposta
- Nenhuma validação de código nesta entrada — spec-only. A validação real
  acontece quando o loop for implementado: testes unitários para o
  controlador de loop e para as invariantes de isolamento (sem credenciais
  de execução, sem push direto em `main`), e um primeiro ciclo real rodado
  contra dado de produção depois de alguns dias de operação acumulados
  (Fase 4 só começou a gerar dado real em 2026-08-01).

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-01
- Justificativa: aprovação explícita em conversa ("Podemos seguir com o que
  você está propondo. Havendo ainda aprovação humana para aplicação final,
  mas com o loop sendo autônomo de ponta a ponta"), depois de eu recusar o
  pedido original (aplicação sem intervenção humana) por violar `CLAUDE.md`
  regra 6 e propor esta alternativa.
