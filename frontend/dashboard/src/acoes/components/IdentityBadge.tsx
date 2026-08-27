import type { SeloIdentidade } from "../api/types";

// Três estados (Seção 11.3) — "sem marcador" é simplesmente não renderizar nada, então
// só dois casos viram markup aqui. O terceiro estado (contorno vazado, identidade não
// resolvida) só existe na tela de Saúde do Dado — nunca chega aqui porque uma empresa
// não resolvida está fora do universo elegível.
export function IdentityBadge({ selo }: { selo: SeloIdentidade }) {
  if (selo === "alta_confianca") return null;
  return (
    <span
      className="acoes-selo-identidade"
      title="Identidade resolvida por propagação de CNPJ ou reconciliação de nome (era 2015-2017) — confiança menor que o FCA"
    >
      <span className="acoes-selo-identidade__ponto" aria-label="identidade reconciliada" />
    </span>
  );
}
