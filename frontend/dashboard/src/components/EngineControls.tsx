import { useState } from "react";
import { api } from "../api/client";
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
    <div className="engine-controls">
      <label className="engine-controls__operator">
        Operador
        <input value={operator} onChange={(e) => persistOperator(e.target.value)} />
      </label>

      <div className="engine-controls__buttons">
        {state === "PAUSADO" && (
          <button className="btn btn--primary" disabled={pending} onClick={() => run(() => api.resume(operator))}>
            Play
          </button>
        )}
        {(state === "ANALISANDO" || state === "POSICAO_ABERTA") && (
          <button className="btn" disabled={pending} onClick={() => run(() => api.pause(operator))}>
            Pause
          </button>
        )}
        {state === "PARADO_CIRCUIT_BREAKER" && (
          <button
            className="btn btn--danger"
            disabled={pending}
            onClick={() => run(() => api.acknowledgeCircuitBreaker(operator))}
          >
            Reconhecer circuit breaker
          </button>
        )}
      </div>

      {error && <p className="engine-controls__error">{error}</p>}
    </div>
  );
}
