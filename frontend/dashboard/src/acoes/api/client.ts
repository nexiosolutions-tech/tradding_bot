import type {
  EmpresaDetalhe,
  HistoricoDetalhe,
  HistoricoLista,
  MesAtual,
  SaudeDoDado,
} from "./types";

// Mesma base do módulo cripto (../../api/client.ts) — um backend FastAPI só, paths
// `/api/acoes/*` diferentes (Seção 11: "não é uma aplicação separada").
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error(`${path} -> ${response.status}`);
  }
  return response.json() as Promise<T>;
}

// `mes-atual` recomputa o universo elegível inteiro no backend (~15-30s por data) e
// nunca cacheia lá o mês corrente (correção: o resultado pode mudar dentro do mesmo dia
// conforme novo dado chega, `api.py::_build_decisao_cacheada`). Sem um cache aqui
// também, cada tela que abre a mesma consulta (Mês atual, Empresas) pagaria o custo
// inteiro de novo — TTL curto o bastante para nunca esconder um dado realmente novo
// dentro da mesma sessão de uso.
const MES_ATUAL_TTL_MS = 60_000;
const cacheMesAtual = new Map<string, { promessa: Promise<MesAtual>; expiraEm: number }>();

function mesAtualCacheado(ano?: number, mes?: number): Promise<MesAtual> {
  const params = new URLSearchParams();
  if (ano) params.set("ano", String(ano));
  if (mes) params.set("mes", String(mes));
  const qs = params.toString();
  const chave = qs || "atual";

  const existente = cacheMesAtual.get(chave);
  if (existente && existente.expiraEm > Date.now()) {
    return existente.promessa;
  }

  const promessa = getJSON<MesAtual>(`/api/acoes/mes-atual${qs ? `?${qs}` : ""}`);
  cacheMesAtual.set(chave, { promessa, expiraEm: Date.now() + MES_ATUAL_TTL_MS });
  promessa.catch(() => cacheMesAtual.delete(chave)); // erro nunca fica preso em cache
  return promessa;
}

export const acoesApi = {
  mesAtual: mesAtualCacheado,
  empresa: (ticker: string, ano?: number, mes?: number) => {
    const params = new URLSearchParams();
    if (ano) params.set("ano", String(ano));
    if (mes) params.set("mes", String(mes));
    const qs = params.toString();
    return getJSON<EmpresaDetalhe>(`/api/acoes/empresas/${encodeURIComponent(ticker)}${qs ? `?${qs}` : ""}`);
  },
  saudeDoDado: () => getJSON<SaudeDoDado>("/api/acoes/saude-do-dado"),
  precos: (tickers: string[]) =>
    getJSON<Record<string, number | null>>(`/api/acoes/precos?tickers=${encodeURIComponent(tickers.join(","))}`),
  historicoLista: () => getJSON<HistoricoLista>("/api/acoes/historico"),
  historicoDetalhe: (dataDecisao: string) =>
    getJSON<HistoricoDetalhe>(`/api/acoes/historico/${dataDecisao}`),
};
