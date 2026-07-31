# Change Proposal — 2026-07-30 — Play/Pause/reconhecer circuit breaker sem autenticação

**Status:** aplicada

## Evidência (origem)
- Ligada a: auditoria técnica completa de 30/07/2026.
- `/api/engine/pause`, `/api/engine/resume`, `/api/engine/acknowledge_circuit_breaker`
  e o WebSocket `/ws/engine` não têm nenhuma verificação de credencial — o
  campo `by` do corpo da requisição é texto livre que o cliente escolhe.
  Qualquer pessoa com a URL pública do Railway pode pausar/retomar o engine ou
  reconhecer um circuit breaker que estava protegendo capital, sem senha
  nenhuma.
- Aceitável hoje só porque é testnet e a URL não é divulgada — mas a regra 6
  do CLAUDE.md (aprovação humana explícita para mudanças de risco) não pode
  ser satisfeita por um campo de texto não verificado. É um portão obrigatório
  antes de mainnet.

## Proposta
- Adicionar uma chave de API opcional (`DASHBOARD_API_KEY`, variável de
  ambiente) verificada via header `X-API-Key` nos três endpoints de comando, e
  via query param `?key=` na conexão do WebSocket.
- **Comportamento se `DASHBOARD_API_KEY` não estiver configurada:** os
  endpoints continuam funcionando sem chave (mesmo comportamento de hoje) —
  para não bloquear o acesso do usuário ao próprio dashboard imediatamente
  após este deploy, antes de ele configurar a chave no Railway. Um aviso é
  logado no startup da API quando isso acontece.
- Dashboard (frontend) passa a ler `VITE_DASHBOARD_API_KEY` do ambiente e
  anexar automaticamente nas chamadas.
- **O que não muda:** nenhuma lógica de negócio, sizing ou execução — é
  estritamente uma camada de autorização em cima do que já existe.

## Classificação de risco da mudança
- [x] Parâmetro de risco/execução (requer revisão humana obrigatória) — trata-se
  de controle de acesso a ações que afetam execução real.

## Validação proposta
- Teste confirmando que sem `DASHBOARD_API_KEY` configurada, os endpoints
  seguem abertos (não quebra o uso atual).
- Teste confirmando que com a chave configurada, requisição sem header (ou com
  header errado) recebe 401, e com o header correto passa.
- Documentar `DASHBOARD_API_KEY` / `VITE_DASHBOARD_API_KEY` no
  `.env.example` de backend e frontend.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-07-30
- Justificativa: aprovação explícita em conversa, após revisão do achado da
  auditoria técnica. Nota: o usuário ainda precisa configurar
  `DASHBOARD_API_KEY` no Railway e no frontend para a proteção entrar em
  vigor de fato — a implementação sozinha não força isso, por design (ver
  "Proposta" acima).
