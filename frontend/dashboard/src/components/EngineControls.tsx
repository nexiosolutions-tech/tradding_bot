import { useState } from "react";
import { api } from "../api/client";
import { IconAlertTriangle, IconPause, IconPlay } from "./Icons";
import type { EngineStateValue } from "../api/types";

export function EngineControls({ state, onChanged }: { state?: EngineStateValue; onChanged: () => void }) {
  const [operator, setOperator] = useState(() => localStorage.getItem("operatorName") ?? "operador");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const persistOperator = (value: string) => {
    setOperator(value);
    localStorage.setItem("operatorName", value);
  };

  const run = async (action: () => Promise<unknown>) => {
    setPending(true);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
      <div className="controls">
        <label className="operator-field">
          Operador
          <input value={operator} onChange={(e) => persistOperator(e.target.value)} />
        </label>

        {state === "PAUSADO" && (
          <button
            className="icon-btn icon-btn--primary"
            disabled={pending}
            onClick={() => run(() => api.resume(operator))}
          >
            <IconPlay width={13} height={13} /> Play
          </button>
        )}
        {(state === "ANALISANDO" || state === "POSICAO_ABERTA") && (
          <button className="icon-btn" disabled={pending} onClick={() => run(() => api.pause(operator))}>
            <IconPause width={13} height={13} /> Pause
          </button>
        )}
        {state === "PARADO_CIRCUIT_BREAKER" && (
          <button
            className="icon-btn icon-btn--danger"
            disabled={pending}
            onClick={() => run(() => api.acknowledgeCircuitBreaker(operator))}
          >
            <IconAlertTriangle width={13} height={13} /> Reconhecer
          </button>
        )}
      </div>

      {error && <p className="form-error">{error}</p>}
    </div>
  );
}
