# 2026-09-04 — equity_curve: o gap do 2d0dc45 era real, mas persistir tudo quebraria o loop

## Contexto

Passo 3 do plano do Brian pós-inventário: `FoldSummary.equity_curve`/`total_pnl`/
`gross_profit`/`gross_loss` são computados desde 2026-08-19 (`model/evaluation.py`) mas
`learning_engine/tools.py::_evaluate_strategy_config` — o único caminho que escreve em
`experiments.jsonl` — nunca os repassava. O commit `2d0dc45` deu esse item como
resolvido; não estava. **Segunda vez que um item aparece fechado no histórico sem
estar** — vale desconfiar de "resolvido" sem reconferir o código, não só desta vez.

---

## O que a correção ingênua ia quebrar

`result_summary` (o dict retornado pela tool) não é write-only para o `.jsonl` — é o
mesmo dict que:

1. Vai direto para o modelo de raciocínio a cada chamada de ferramenta
   (`agentic_loop.py::report_tool_result`);
2. Vira contexto textual bruto no início de cada ciclo futuro (`_build_context`,
   últimos 5 experimentos).

`equity_curve` é indexado por barra (`backtesting/engine.py::_on_snapshot`, um ponto
por snapshot, não por trade) — ~13.000 tuplas por fold numa janela de teste de ~9 dias
em barras de 1min, ~65.000 num único `evaluate_strategy_config` de 5 folds. Multiplicado
pelos últimos 5 experimentos que `_build_context` injeta no início de cada ciclo, seriam
milhões de tokens de prompt. **O loop agentic pararia de funcionar**, e a causa seria
difícil de rastrear até uma mudança que parecia trivial — exatamente o tipo de correção
que soa pequena e não é.

---

## Decisão: persistir os escalares agora, `equity_curve` fica de fora

`_evaluate_strategy_config` passou a incluir:

- Top-level: `total_pnl` e `aggregate_profit_factor` (properties já existentes em
  `ConfigEvaluation`, agregados corretos — soma pooled de gross profit/loss, não média
  de razões por fold; ver os próprios docstrings em `model/evaluation.py`).
- Por fold: `total_pnl`, `gross_profit`, `gross_loss`.
- `equity_curve` **não** entra — nem top-level nem por fold.

Justificativa, além do risco de quebra acima:

- **Os escalares já cobrem quase tudo que PBO e DSR precisam.** PBO/CSCV precisa da
  matriz configuração × sub-período — escalar por fold, e `ConfigEvaluation.folds` já é
  isso. DSR precisa do número de tentativas, da variância dos Sharpes entre tentativas
  (escalar por trial) e de skew/kurtose dos retornos **da estratégia selecionada** — uma
  série só, não todas. Nenhum dos dois exige guardar a curva de todo trial testado.
- **A granularidade certa provavelmente não é por barra.** O que falta nos escalares é a
  série de retornos para skew/kurtose — e retorno por trade serve, com algumas centenas
  de números por fold em vez de ~13.000. Guardar por barra pagaria duas ordens de
  grandeza por uma precisão que a estatística não pede.
- **Não existe consumidor.** `specs/11-roadmap-e-fases.md` não menciona DSR nem PBO — o
  comentário no código que cita "specs/11 fila estatística" é prospectivo. Construir
  armazenamento para um consumidor que não existe, com requisito de granularidade
  desconhecido, é como se erra a granularidade e depois se carrega o erro por diante.

Teste novo (`test_learning_tools.py::test_evaluate_strategy_config_tool_exposes_pnl_aggregates_without_equity_curve`)
verifica os dois lados: os escalares aparecem, `equity_curve` não aparece nem no
top-level nem em nenhum fold. Suite completa (exceto Ações e o teste ao vivo): 369
passed (era 368).

---

## Dívida registrada, para não se perder

**Acoplamento de `result_summary`.** `ExperimentRecord.result_summary` hoje serve dois
papéis ao mesmo tempo — o que persiste em disco e o que o modelo de raciocínio vê no
prompt. Essa mistura vai morder de novo no primeiro campo que seja útil guardar e
ruidoso ler (como quase aconteceu aqui). O desenho certo, quando for necessário: separar
um campo write-only em `ExperimentRecord` (só vai para o `.jsonl`) do que alimenta
`report_tool_result`/`_build_context`. Não faz sentido construir essa separação agora,
sem um segundo caso concreto que precise dela — mas fica marcada como a correção
pretendida, não uma ideia descartada.

**Granularidade de DSR/PBO, em aberto.** Quando a spec de DSR/PBO for escrita, ela
decide o que guardar — não o código que a antecipa. A nota que fica: retorno por trade é
o candidato mais provável; curva completa por barra provavelmente é excessiva. Isso
existe para que quem escrever a spec comece da pergunta certa em vez de assumir que "a
curva completa" é o alvo.

---

## Decisão

- Aprovado por: Brian — escolheu a Opção A (persistir só os escalares agora) entre duas
  propostas, com a razão explícita de que a Opção B (separar já o que persiste do que o
  LLM vê) seria estrutura maior que o pedido original, sem um segundo caso concreto
  ainda para justificá-la. Pediu que a dívida do acoplamento e a pergunta de
  granularidade ficassem registradas explicitamente, e que a correção do `2d0dc45`
  entrasse no `changes/` (2026-09-04).
- Justificativa (nas palavras dele): "esse achado evitou uma quebra real, não uma
  ineficiência... a causa seria difícil de rastrear até uma correção que parecia
  trivial" — persistir dado que ninguém consome ainda, na granularidade errada, dentro
  de uma estrutura que já mistura disco com prompt, é o tipo de erro que só aparece
  meses depois. A spec de DSR/PBO decide o que guardar; o código não antecipa.
