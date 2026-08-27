import type { Carimbo } from "../api/types";
import { formatDataBr } from "../format";

// Elemento assinatura da interface (Seção 11.3). Regra estrutural, não só visual:
// número de balanço sem carimbo nunca é renderizado — os chamadores desta tela sempre
// verificam `detalhe.valor !== null` antes de montar este componente, então `carimbo`
// aqui nunca deveria ser `null` na prática; o `if` abaixo é o último freio, não o
// primeiro (nenhum número aparece sem data de publicação ao lado).
export function ProvenanceChip({ carimbo }: { carimbo: Carimbo | null }) {
  if (!carimbo) return null;
  return (
    <span className="acoes-carimbo" title={`Publicado em ${formatDataBr(carimbo.data_publicacao)}, versão ${carimbo.versao}`}>
      ⌗ {formatDataBr(carimbo.data_publicacao)} · v{carimbo.versao}
    </span>
  );
}
