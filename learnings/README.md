# learnings/

Relatórios diários gerados pelo motor de aprendizado contínuo
(ver [`specs/09-aprendizado-continuo.md`](../specs/09-aprendizado-continuo.md)).

## Regras

- Um arquivo por dia: `AAAA-MM-DD.md`.
- Gerado automaticamente pelo job diário, **somente leitura** sobre a
  persistência de produção. Nunca editado manualmente para "corrigir" um
  achado — se o job errou, o bug se corrige no job, não no relatório.
- Contém **dados e observações objetivas**, não decisões. Decisões propostas
  a partir de um achado vão para [`../changes/`](../changes/), nunca direto
  para código.

## Template

```markdown
# Learnings — AAAA-MM-DD

## Resumo do dia
- Trades executados: N
- Win rate do dia: X%
- P&L do dia: X
- Estado do circuit breaker: acionado? quando? por quê?

## Achados

### Achado 1: [título objetivo]
- Observação: [o que os dados mostram, com números]
- Condição em que ocorreu: [horário, volatilidade, setup, versão do modelo]
- Amostra: [quantos trades sustentam essa observação — achados com amostra
  pequena devem ser marcados como preliminares]

### Achado 2: ...

## Divergência backtest vs. produção
- [Se houver: onde o resultado real destoou do esperado pelo backtest, e
  hipótese inicial de causa]

## Sugestões de investigação (não são mudanças aprovadas)
- [Ponteiros para o que vale virar uma entrada em changes/, se pertinente]
```
