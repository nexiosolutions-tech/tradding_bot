# changes/

Backlog de mudanças propostas a partir de [`../learnings/`](../learnings/),
pendentes de revisão humana antes de virar spec/código
(ver [`specs/09-aprendizado-continuo.md`](../specs/09-aprendizado-continuo.md)).

## Regras

- Um arquivo por proposta: `AAAA-MM-DD-descricao-curta.md`.
- Toda proposta tem status explícito no topo do arquivo:
  `pendente` | `aprovada` | `rejeitada` | `aplicada`.
- Mudanças de risco, execução ou lógica de negócio **nunca** saem de `pendente`
  sem decisão humana explícita registrada aqui (quem aprovou/rejeitou e
  quando). Ver `CLAUDE.md`, regra 6.
- Ao ser aprovada e implementada, a proposta é marcada `aplicada` e a spec
  correspondente em `../specs/` é atualizada no mesmo commit — o histórico
  aqui não substitui a spec atualizada, é o rastro de por que ela mudou.

## Template

```markdown
# Change Proposal — AAAA-MM-DD — [descrição curta]

**Status:** pendente

## Evidência (origem)
- Ligada a: learnings/AAAA-MM-DD.md, achado N
- Resumo da evidência que motiva esta proposta

## Proposta
- O que muda exatamente (parâmetro, feature, lógica, spec afetada)
- O que **não** muda (escopo explícito, para evitar ambiguidade na revisão)

## Classificação de risco da mudança
- [ ] Retreino de modelo dentro do mesmo espaço de hiperparâmetros/target
      (pode seguir critério de promoção automática de specs/07)
- [ ] Nova feature (requer revisão humana antes de entrar em specs/03)
- [ ] Parâmetro de risco/execução (requer revisão humana obrigatória)
- [ ] Mudança de arquitetura/target do modelo (requer processo SDD completo)

## Validação proposta
- Como será testado antes de produção (referência a specs/07)
- Critério objetivo de sucesso/fracasso
- Se a proposta veio do loop autônomo de aprendizado contínuo (specs/09):
  resultado real do backtest/experimento já rodado, não só uma promessa de
  validação futura — a revisão humana julga um resultado, não uma hipótese

## Decisão
- Aprovado/rejeitado por: [nome]
- Data:
- Justificativa:
```
