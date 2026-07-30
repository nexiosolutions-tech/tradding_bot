# 03 — Motor de Features

## Objetivo

Transformar o stream de eventos normalizados em vetores de features consumíveis
pelo modelo, de forma incremental (sem recalcular séries inteiras a cada tick) e
determinística (reproduzível em backtesting).

## Requisitos funcionais

1. Indicadores calculados de forma **incremental/rolling**, não recalculados do
   zero a cada novo dado — usar estruturas como `collections.deque` de tamanho
   fixo ou acumuladores incrementais (ex.: EMA já é naturalmente incremental;
   RSI/MACD precisam de implementação incremental própria).
2. Cada feature tem timestamp de "fechamento de conhecimento" igual ao timestamp
   do último evento usado para calculá-la — nunca usa dado futuro relativo ao
   momento da decisão (prevenção de data leakage).
3. O mesmo código de cálculo de features é usado em backtesting e em produção
   (não pode haver duas implementações divergentes — essa é uma das causas mais
   comuns de resultado de backtest não se repetir em produção).

## Features iniciais (MVP)

Indicadores técnicos clássicos como features de entrada do modelo, não como
regras de decisão isoladas:

- Médias móveis (SMA/EMA) em múltiplas janelas
- RSI
- MACD
- Bandas de Bollinger (posição do preço relativa à banda)
- Volume relativo (volume atual vs. média)
- Spread bid-ask e profundidade (quando order book estiver disponível)
- Volatilidade realizada em janela curta

Novas features entram via `changes/` após o motor de aprendizado identificar
sinal de que agregam valor — não são adicionadas ad-hoc sem justificativa
registrada.

## Feature store

- Toda feature calculada em produção é persistida junto com o timestamp e o
  símbolo, para permitir:
  - Auditoria: reconstruir exatamente o que o modelo "viu" em qualquer decisão
    passada.
  - Retreino: gerar datasets de treino a partir de dados de produção real, não
    só de backfill histórico.

## Invariantes

- Cálculo determinístico: dado o mesmo histórico de eventos, o motor sempre
  produz o mesmo vetor de features (requisito para backtesting confiável).
- Nenhuma feature pode depender de informação com timestamp posterior ao
  timestamp da decisão que a consome.

## Fora de escopo no MVP

- Features de dados alternativos (notícias, redes sociais).
- Feature store distribuído/dedicado (ex.: Feast) — MVP usa a mesma
  persistência do restante do sistema (`10-stack-tecnica-e-dependencias.md`).
