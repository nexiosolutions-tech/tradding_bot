# Change Proposal — 2026-08-15 — Publicação de learnings/changes via branch dedicada + PR

**Status:** aplicada

## Evidência (origem)
- Ao preparar a ativação do loop agêntico completo (`ANTHROPIC_API_KEY`),
  revisão do que `learning-daily-cron` (ligado horas antes, mesma data)
  realmente entrega encontrou uma lacuna: `write_daily_report`/
  `draft_change_proposals`/`draft_change_proposal` escrevem em
  `learnings/`/`changes/` usando caminho relativo ao pacote instalado —
  correto numa sessão local, mas o cron roda num container efêmero do
  Railway. O arquivo gerado não sobrevive ao próximo ciclo, e nem o
  serviço da API/dashboard o veria (container diferente, filesystem
  diferente). O cron rodava sem erro e não entregava nada a ninguém.
- Pedido do usuário para resolver essa lacuna antes de configurar a
  chave da Anthropic, já que ligar o loop agêntico sem isso gastaria
  custo real de API por uma proposta que nunca chegaria a ser revisada.

## Proposta
- `learning_engine/github_publish.py` (novo) — publica arquivo(s) via
  API REST do GitHub (`httpx`, sem depender de `git`/`gh` CLI nem de
  `.git` presente na imagem buildada): cria branch nova a partir do HEAD
  de `main`, commita o(s) arquivo(s) via Contents API, abre PR.
- **Garantia estrutural, não só de projeto**: o código só conhece o
  endpoint de criar branch nova (`POST .../git/refs`) — nunca monta uma
  chamada contra `heads/main`/`heads/master`, e `publish_files` recusa
  explicitamente (`PublishError`, antes de qualquer request HTTP) se
  pedirem para publicar num desses nomes. Testado explicitamente
  (`test_publish_files_refuses_protected_branch_without_any_http_call`),
  não só documentado — mesma garantia que specs/09 já descrevia para o
  loop agêntico ("nunca escreve em main"), agora reforçada por código e
  teste também no caminho não-agêntico (`run_daily_learning.py`).
- `maybe_publish()` é aditivo: sem `GITHUB_TOKEN` no ambiente, retorna
  `None` e o comportamento fica idêntico ao de antes (só grava local) —
  não quebra quem roda os scripts numa sessão interativa.
- Ligado em `run_daily_learning.py` e `run_agentic_learning.py`, depois
  que cada um termina de escrever seu(s) arquivo(s) local(is).

## Classificação de risco da mudança
- [x] Nova ferramenta do motor de aprendizado (specs/09) — mudança
  aditiva de infraestrutura, não de risco/execução/arquitetura de
  modelo.
- Não altera nenhum comportamento de execução/risco. Não promove nada
  sozinho: o PR aberto ainda exige revisão humana antes de qualquer
  `Status:` mudar de `pendente` (`CLAUDE.md` regra 6).

## Validação
- 7 testes novos (`test_github_publish.py`): fluxo feliz, path relativo
  correto no commit, recusa de branch protegida (main/master) sem
  nenhuma chamada HTTP, lista vazia de arquivos, `maybe_publish` no-op
  sem token e delegando corretamente com token — via `httpx.MockTransport`,
  sem rede real.
- Suíte completa: 240 testes passando.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-15
- Justificativa: "Podemos deixar a chave para depois, vamos resolver essa
  tarefa antes." Pendente do usuário: gerar um fine-grained personal
  access token do GitHub, restrito a este repositório, com permissões
  `Contents: Read and write` e `Pull requests: Read and write` (nada
  além disso), e configurá-lo como `GITHUB_TOKEN` no serviço
  `learning-daily-cron` do Railway para a publicação passar a funcionar
  de fato em produção.
