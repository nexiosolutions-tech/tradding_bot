# 2026-08-27 — Módulo de Ações: fonte real de IBOV/IBrX-100/SMLL encontrada e verificada

## Contexto

Item pendente desde a Seção 9.4 (BCB SGS 7845 descontinuada em ago/2019). Usuário
pediu para resolver antes de partir para a investigação do EPS implausível.

## O que foi feito

Capturada a requisição real feita pela própria página oficial de estatísticas de
índices da B3 (via Playwright, não deduzida do nome do endpoint — que induzia a erro).
`indexStatisticsProxy/IndexCall/GetPortfolioDay/{base64(JSON)}` — mesmo endpoint já
conhecido por servir composição diária de carteira, mas com parâmetros diferentes
(`{"index", "language", "year"}` em vez de `pageNumber`/`pageSize`/`segment`) devolve
uma tabela de evolução diária do **nível** do índice para o ano inteiro.

Verificado com dado real: `IBOVESPA` (2015: 43.199-58.051; 2026: ~160.000-198.000,
ambos plausíveis), `IBXX` = IBrX-100 (2020: 26.895-48.065, cobre a queda/recuperação do
COVID), `SMLL` (2020: 1.480-2.853). Códigos não documentados publicamente, confirmados
por tentativa direta (`IBOV` sozinho não funciona, precisa `IBOVESPA`; `IBRX`/`IBrX100`
não funcionam, precisa `IBXX`).

`yfinance` não precisou ser reconsiderado — a fonte é a própria B3.

## Pendente

- **Price-only vs. total-return** — não verificado se esta série já incorpora
  reinvestimento de proventos na metodologia oficial do índice (memória não conferida,
  não carregada como suposição). Condição de uso já registrada na Seção 9.3: nunca
  comparar um regime contra o outro. Sem essa verificação, os benchmarks 1 continuam
  fora de qualquer leitura de resultado.
- Ingestão real (parsing da tabela de evolução diária, um módulo tipo `ipca.py`/
  `cdi.py`) ainda não escrita — esta rodada só confirma que a fonte existe e é real.

## Decisão

- Aprovado por: Brian — pediu para resolver o fetch antes da investigação do EPS
  (2026-08-27).
- Justificativa: fonte real encontrada fecha um item pendente desde a Seção 9.4; a
  verificação price-only/total-return fica para quando a ingestão for de fato escrita,
  não bloqueia o registro do achado.
