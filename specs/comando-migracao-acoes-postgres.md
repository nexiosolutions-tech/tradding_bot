# Comando — Migração do módulo de Ações: SQLite → Postgres

**Decisão tomada:** o módulo de Ações vai para produção usando Postgres, reusando o serviço gerenciado que o bot de cripto já utiliza no Railway. A alternativa (volume persistente com SQLite) foi descartada por risco de contenção de escrita e de corrupção de arquivo em volume de rede — o mesmo tipo de problema que já apareceu localmente disfarçado de erro de CORS.

**Regra de idioma:** toda a saída desta rodada em português do Brasil — resumo, mensagens de commit, `changes/`, comentários e docstrings.

---

## Fase 0 — Verificações antes de tocar em código

Nenhuma das três pode ser presumida. Se alguma falhar, **pare e reporte** antes de seguir.

**0.1 — Rede de dentro do Railway.** Testar, do container real, se `dados.cvm.gov.br` e o endpoint de classificação setorial da B3 respondem. Precedente: a Binance geobloqueia essa região, e isso só foi descoberto tentando. Se CVM ou B3 estiverem bloqueadas, a ingestão terá que continuar local e só a leitura vai para a nuvem — o que muda o desenho e deve ser decidido antes de migrar.

**0.2 — Isolamento do banco.** Confirmar como o módulo de Ações vai coexistir com o do bot no mesmo Postgres: schema separado, banco separado, ou prefixo de tabela. A separação lógica registrada em `specs/00` e `CLAUDE.md` precisa continuar valendo — as duas frentes compartilham fundação, não estado. Escolher e registrar a decisão.

**0.3 — Capacidade.** Confirmar se o plano atual do Postgres comporta os ~539MB (mais índices, que em Postgres pesam mais que em SQLite). Reportar o número antes de migrar, não durante.

---

## Fase 1 — Portar o schema

Migrar os modelos de `backend/src/tradingbot/acoes/` para Postgres preservando **todas** as garantias existentes. Cada item abaixo pegou um bug real nesta frente e não pode se perder na tradução:

- `CvmFiling` — unicidade `(cnpj_cia, dt_refer, versao, categ_doc)`, comportamento append-only (rejeitar duplicata, nunca fazer update in place)
- `CotahistPrice` — unicidade `(ticker, trade_date)`
- `UniversoElegivel` — append-only; **atenção**: foi essa trava que zerou o universo de 2024 em silêncio ao reprocessar sem limpar. A semântica de reprocessamento precisa ser explícita no Postgres, não herdada por acidente.
- `CvmFinancialLineItem` — o índice composto adicionado após a verificação por `EXPLAIN QUERY PLAN`. Refazer a verificação com `EXPLAIN ANALYZE` no Postgres: o plano de consulta é diferente, e um índice que servia no SQLite pode não ser usado aqui.

Verificar os planos das **três consultas as-of** (identidade, publicação, preço) no Postgres. Elas são chamadas repetidamente durante o backtest; consulta as-of sem índice torna o backtest impraticável.

---

## Fase 2 — Migrar os dados

Transferir os ~539MB do SQLite local para o Postgres.

- Usar carga em lote, não linha a linha — a lição da otimização da COTAHIST (526s → 22s) vale aqui.
- **Asserção de contagem obrigatória**, no mesmo espírito do `IngestionCountMismatchError`: contagem lida do Postgres comparada com a contagem lida do SQLite, por tabela, ao final. Diferença de uma linha aborta e reporta. Sem isso, migração truncada passa silenciosa — já aconteceu duas vezes nesta frente.
- Rodar em primeiro plano, com progresso por tabela. Não usar background: a fronteira de sessão já matou ingestão antes.

---

## Fase 3 — Validação contra resultado conhecido

**Esta fase é o critério de sucesso da migração inteira.** Não basta "os dados foram copiados"; é preciso provar que o sistema produz os mesmos resultados.

Rodar `build_decisao` contra o Postgres para as duas datas-âncora e exigir correspondência exata:

| Ano | Universo | Score computável |
|---|---|---|
| 2015 | 125 | 106 |
| 2016 | 115 | 98 |

Se qualquer um dos quatro números divergir, **pare e investigue antes de prosseguir** — não ajuste o código até bater. Foi essa mesma regressão de dois pontos que pegou o vazamento do GETI4, e é ela que distingue "a migração está correta" de "a migração parece ter funcionado".

Adicionalmente: rodar a suíte completa contra o Postgres. Os 499 testes precisam passar sem que nenhum seja adaptado para acomodar diferença de banco — se algum teste precisar mudar, isso é sinal de que o comportamento mudou, e o motivo tem que ser entendido e registrado.

---

## Fase 4 — Produção

- Ligar as rotas de `acoes/api.py` ao Postgres em produção.
- Reverter o `ModuleSwitch`: a aba Ações deixa de ser desabilitada, já que o módulo passa a estar disponível.
- **Manter o 503 estruturado** — ele continua correto para o caso de o banco estar indisponível, e não deve ser removido junto com a limitação de ambiente.
- Navegar as 5 telas contra o ambiente de produção real, como foi feito localmente.

---

## Fase 5 — Registro

- Atualizar a Seção 11.12 da spec 14: a decisão de hospedagem mudou de "local por escolha" para "Postgres em produção", com o motivo (querer operar em PRD) e a razão de não ter ido de volume (contenção e risco de corrupção).
- `changes/` documentando a migração, as verificações da Fase 0 e o resultado da validação da Fase 3.
- Registrar a decisão de isolamento tomada em 0.2.

---

## O que não fazer nesta rodada

- Não mexer nas pendências do EPS (causa raiz na ingestão, caso PDGR3, bug do `winsorize`) — são investigação própria, e misturar com migração impede saber o que causou o quê.
- Não otimizar consultas além de garantir que os índices as-of são usados. Otimização vem depois de a migração estar correta.
- Não adaptar teste para fazer a Fase 3 passar.
- Não deletar o SQLite local ao final — ele é o fallback e a referência de comparação até a migração estar validada em produção por algum tempo.
