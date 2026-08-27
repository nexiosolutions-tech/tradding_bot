import type { MotivoCelulaVazia } from "../api/types";

// Quatro estados, nunca zero, nunca branco (Seção 11.3) — cada um com rótulo curto e
// explicação no hover. O quarto estado (`versao_indisponivel`) é específico deste
// sistema (achado real, Seção 7.5/9.5): a versão vigente na data existe no índice da
// CVM mas o arquivo de item financeiro daquela versão não tem nenhuma linha disponível.
const RÓTULO: Record<MotivoCelulaVazia, string> = {
  inaplicavel: "n/a",
  indefinido: "—",
  sem_dado: "s/d",
  versao_indisponivel: "⌗?",
};

const EXPLICAÇÃO: Record<MotivoCelulaVazia, string> = {
  inaplicavel: "O fator não se aplica ao setor desta empresa",
  indefinido: "Aplicável, mas indefinido para esta empresa (EBITDA ≤ 0 ou patrimônio ≤ 0)",
  sem_dado: "A empresa não reportou este campo",
  versao_indisponivel: "A versão vigente na data não está no arquivo público da CVM",
};

export function EmptyCell({ motivo }: { motivo: MotivoCelulaVazia }) {
  return (
    <span className="acoes-empty-cell" title={EXPLICAÇÃO[motivo]}>
      {RÓTULO[motivo]}
    </span>
  );
}
