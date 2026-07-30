import { IconDot } from "./Icons";
import type { EngineStateValue } from "../api/types";

const LABELS: Record<EngineStateValue, string> = {
  ANALISANDO: "Analisando",
  POSICAO_ABERTA: "Posição aberta",
  PAUSADO: "Pausado",
  PARADO_CIRCUIT_BREAKER: "Circuit breaker",
};

const CLASSES: Record<EngineStateValue, string> = {
  ANALISANDO: "state-badge state-badge--info",
  POSICAO_ABERTA: "state-badge state-badge--active",
  PAUSADO: "state-badge state-badge--muted",
  PARADO_CIRCUIT_BREAKER: "state-badge state-badge--danger",
};

export function StateBadge({ state }: { state?: EngineStateValue }) {
  if (!state) {
    return (
      <span className="state-badge state-badge--muted">
        <IconDot /> não configurado
      </span>
    );
  }
  return (
    <span className={CLASSES[state]}>
      <IconDot /> {LABELS[state]}
    </span>
  );
}
