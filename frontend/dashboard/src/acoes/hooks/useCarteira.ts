import { useEffect, useState } from "react";

// Entrada manual — nunca há corretora integrada (Seção 2/11.6). Persistida só no
// navegador do usuário (localStorage), nunca no backend: este módulo não custodia
// posição de ninguém, só ajuda a ler o que o usuário já tem.
export interface Posicao {
  ticker: string;
  quantidade: number;
  precoMedio: number;
}

const CHAVE_STORAGE = "acoes.minha-carteira.v1";

function carregar(): Posicao[] {
  try {
    const bruto = localStorage.getItem(CHAVE_STORAGE);
    return bruto ? (JSON.parse(bruto) as Posicao[]) : [];
  } catch {
    return [];
  }
}

export function useCarteira() {
  const [posicoes, setPosicoes] = useState<Posicao[]>(() => carregar());

  useEffect(() => {
    try {
      localStorage.setItem(CHAVE_STORAGE, JSON.stringify(posicoes));
    } catch {
      // localStorage indisponível (modo privado, storage cheio) — a carteira só não
      // sobrevive a um reload; nunca quebra a tela por isso.
    }
  }, [posicoes]);

  function adicionar(posicao: Posicao) {
    setPosicoes((atual) => [...atual.filter((p) => p.ticker !== posicao.ticker), posicao]);
  }

  function remover(ticker: string) {
    setPosicoes((atual) => atual.filter((p) => p.ticker !== ticker));
  }

  return { posicoes, adicionar, remover };
}
