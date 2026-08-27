# CLAUDE.md — Constituição do Projeto

Este arquivo rege como qualquer agente de IA (Claude Code, dentro do Cursor ou fora
dele) deve operar neste repositório. Regras aqui têm precedência sobre conveniência
ou velocidade de entrega.

## Idioma (Restrição dura)

Todas as respostas devem ser em português do Brasil, sempre. Isso inclui resumos de
rodada, mensagens de commit, conteúdo de `changes/` e comentários de código. Não
alternar para inglês em nenhuma circunstância, mesmo quando o conteúdo for técnico.

## O que este projeto é

Um sistema de day trade algorítmico para cripto (Binance) com quatro capacidades:
análise de mercado em tempo real via ML, execução automática de ordens, um dashboard
de observabilidade, e um ciclo de aprendizado contínuo que revisa a própria
performance diariamente. Ver [`specs/00-visao-geral-e-objetivos.md`](./specs/00-visao-geral-e-objetivos.md)
para o objetivo completo.

Este repositório também abriga um segundo módulo, independente: apoio à decisão de
aporte mensal em ações da B3 (não um bot de execução — ver
[`specs/14-modulo-acoes-b3.md`](./specs/14-modulo-acoes-b3.md)). Os dois módulos
compartilham fundação de engenharia (ingestão, validação, gate de promoção,
`changes/`), **nunca estado, dado, modelo ou runtime**. Nenhuma conclusão, resultado
ou `changes/` de um módulo se aplica ao outro sem verificação própria.

## Modelo de trabalho: SDD (Spec-Driven Development)

1. Nenhuma funcionalidade é implementada sem uma spec correspondente em `specs/`.
2. Se a tarefa pedida não tem spec, o primeiro passo é escrever ou atualizar a spec —
   não o código.
3. Specs descrevem **contratos** (entrada/saída/invariantes de cada módulo), não
   implementação. Detalhes de implementação vivem no código e nos comentários,
   não na spec.
4. Ao terminar uma implementação, verifique se o comportamento real ainda corresponde
   à spec. Se divergiu por uma boa razão, atualize a spec no mesmo commit/PR —
   spec e código não podem ficar dessincronizados.
5. Mudanças de arquitetura ou de lógica de negócio (não bugfixes triviais) passam
   pelo fluxo `learnings/ → changes/ → specs/` descrito em
   [`specs/09-aprendizado-continuo.md`](./specs/09-aprendizado-continuo.md).

## Regras não negociáveis (safety rails)

Estas regras existem porque erros aqui custam dinheiro real diretamente. Não
contorne nenhuma delas para "destravar" uma tarefa — pare e pergunte ao usuário
em vez disso.

1. **Testnet primeiro, sempre.** Nenhuma mudança na camada de execução
   (`specs/06-camada-de-execucao.md`) vai para mainnet sem ter rodado em
   `testnet.binance.vision` antes.
2. **Toda ordem tem stop-loss.** Não existe caminho de código que envie uma ordem
   de entrada sem um stop-loss associado. Isso não é configurável por parâmetro
   de runtime que possa ser esquecido — é estrutural.
3. **Position sizing é sempre percentual de capital**, nunca valor fixo hardcoded
   nem decidido "na hora" por uma branch de exceção.
4. **Circuit breaker é obrigatório e não pode ser desativado silenciosamente.**
   Se o sistema perder X% em Y tempo (definido em `specs/05-gestao-de-risco.md`),
   ele para. Qualquer alteração desse limite é uma mudança de risco — ver regra 6.
5. **Idempotência de ordens.** Reconexão de WebSocket ou retry de rede nunca pode
   resultar em ordem duplicada. Todo envio de ordem usa client order ID idempotente.
6. **Mudanças em parâmetros de risco ou na lógica de execução exigem aprovação
   humana explícita antes de aplicar em ambiente com capital real.** O motor de
   aprendizado contínuo pode *propor* essas mudanças (via `changes/`), nunca
   *aplicá-las* sozinho em produção.
7. **Retreino de modelo (pesos/parâmetros) pode ser mais automatizado**, mas só
   promove uma nova versão se ela bater a anterior em backtest out-of-sample
   segundo os critérios de `specs/07-backtesting-e-validacao.md`. Mudança de
   arquitetura do modelo ou do target de predição não se qualifica como "retreino"
   — é mudança de spec.
8. **Nenhuma spec ou resposta deste projeto deve ser tratada como recomendação
   de investimento.** O escopo é estritamente engenharia de software.

## Convenções de código

- Especificado em detalhe por módulo em cada spec técnica; regras gerais:
- Python para backend/ML (ver `specs/10-stack-tecnica-e-dependencias.md` para versões).
- TypeScript/React para o dashboard.
- Sem comentários explicando *o quê* o código faz — nomes de variáveis/funções
  devem bastar. Comentários só para *por quê* (invariante não-óbvio, workaround
  de bug específico, decisão de trade-off).
- Sem abstrações especulativas. Resolva o problema da spec atual, não hipóteses
  futuras.
- Toda função que envolve dinheiro (sizing, ordens, cálculo de P&L) precisa de
  teste unitário antes de ser considerada pronta.

## Skills de UI a utilizar no dashboard

Ao trabalhar em qualquer código de interface (`specs/08-dashboard-e-visualizacao.md`),
usar as seguintes skills de terceiros instaladas neste projeto:

```bash
npx -y skills add emilkowalski/skills --agent claude-code
npx -y skills add pbakaus/impeccable --agent claude-code
npx -y skills add https://github.com/Leonxlnx/taste-skill --agent claude-code
```

- **emilkowalski/skills** — princípios de animação/polish (não animar elementos
  vistos 100+ vezes/dia, evitar easing artificial, transições sob 300ms).
- **pbakaus/impeccable** — padrões de qualidade de interação e polimento de UI.
- **taste-skill** — heurísticas de bom gosto visual/composição.

**Nota sobre Cursor:** essas skills seguem o formato de skills do Claude Code. Se a
sessão estiver rodando via integração Claude dentro do Cursor (em vez do Claude
Code CLI diretamente), confirmar na prática que o carregamento de skills externas
funciona antes de depender delas no fluxo — o comportamento pode variar entre os
dois modos de integração.

## Como este arquivo deve ser mantido

Se uma regra de segurança nova for aprendida (via `learnings/`) e aprovada como
mudança permanente, ela entra aqui, não só na spec técnica correspondente — este
arquivo é o resumo executivo das invariantes do projeto.

