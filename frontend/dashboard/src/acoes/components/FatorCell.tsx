import type { DetalheFator } from "../api/types";
import { EmptyCell } from "./EmptyCell";
import { ProvenanceChip } from "./ProvenanceChip";

// Célula de fator reusada em Mês atual / Empresa / Histórico (Seção 11.4): valor
// absoluto e barra de percentil lado a lado — "o absoluto é o que o usuário reconhece,
// o percentil é o que o sistema calcula. Mostrar só um dos dois esconde metade da
// informação." `formatar` decide a unidade (percentual para earnings yield/ROE,
// múltiplo "x" para dívida líquida/EBITDA) — nunca reimplementada aqui, injetada pelo
// chamador.
export function FatorCell({
  detalhe,
  formatar,
}: {
  detalhe: DetalheFator;
  formatar: (valor: number) => string;
}) {
  if (detalhe.valor === null || detalhe.motivo) {
    return <EmptyCell motivo={detalhe.motivo ?? "sem_dado"} />;
  }

  const percentil = detalhe.percentil ?? 0;

  return (
    <div className="acoes-fator-cell">
      <span className="acoes-fator-valor acoes-num">{formatar(detalhe.valor)}</span>
      <div className="acoes-bar-track" title={`Percentil ${percentil.toFixed(0)} no setor`}>
        <div className="acoes-bar-fill" style={{ width: `${Math.max(0, Math.min(100, percentil))}%` }} />
      </div>
      <ProvenanceChip carimbo={detalhe.carimbo} />
    </div>
  );
}
