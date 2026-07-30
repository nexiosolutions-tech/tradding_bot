import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { EngineControls } from "../components/EngineControls";
import { StateBadge } from "../components/StateBadge";
import { Timer } from "../components/Timer";
import { useEngineState } from "../hooks/useEngineState";
import type { EngineEvent } from "../api/types";

export function LiveView() {
  const state = useEngineState();
  const [events, setEvents] = useState<EngineEvent[]>([]);

  const refreshEvents = useCallback(() => {
    api.engineEvents(20).then(setEvents).catch(() => undefined);
  }, []);

  useEffect(() => {
    refreshEvents();
    const interval = setInterval(refreshEvents, 5000);
    return () => clearInterval(interval);
  }, [refreshEvents]);

  if (!state) {
    return <div className="panel">Carregando estado do engine…</div>;
  }

  if (!state.configured) {
    return (
      <div className="panel panel--warning">
        <h2>Engine não configurado</h2>
        <p>{state.error}</p>
        <p className="muted">
          Configure BINANCE_API_KEY / BINANCE_API_SECRET (testnet) no serviço do backend para
          ligar a execução ao vivo. Até lá, as views Performance e Modelo continuam
          funcionando com os dados já existentes em <code>results/</code>.
        </p>
      </div>
    );
  }

  return (
    <div className="live-view">
      <div className="panel live-view__summary">
        <div className="live-view__headline">
          <h2>{state.symbol}</h2>
          <StateBadge state={state.state} />
        </div>
        <div className="live-view__timers">
          <Timer sinceTs={state.started_at ?? null} label="Sistema ligado há" />
          <Timer sinceTs={state.position?.entry_ts ?? null} label="Operação aberta há" />
        </div>
        <div className="live-view__metrics">
          <div>
            <span className="muted">Capital</span>
            <strong>{state.equity?.toFixed(2)}</strong>
          </div>
          <div>
            <span className="muted">Estratégia</span>
            <strong>{state.strategy_version}</strong>
          </div>
        </div>
        <EngineControls state={state.state} onChanged={refreshEvents} />
      </div>

      {state.position && (
        <div className="panel">
          <h3>Posição aberta</h3>
          <dl className="kv-grid">
            <dt>Preço de entrada</dt>
            <dd>{state.position.entry_price.toFixed(2)}</dd>
            <dt>Tamanho</dt>
            <dd>{state.position.size}</dd>
            <dt>Stop-loss</dt>
            <dd>{state.position.stop_loss_price.toFixed(2)}</dd>
          </dl>
        </div>
      )}

      <div className="panel">
        <h3>Eventos recentes</h3>
        <ul className="event-log">
          {events.map((event, i) => (
            <li key={i}>
              <span className="muted">{new Date(event.ts).toLocaleString()}</span>
              <span>
                {event.from_state} → {event.to_state}
              </span>
              <span className="muted">{event.reason}</span>
              {event.triggered_by_human && <span className="tag">manual</span>}
            </li>
          ))}
          {events.length === 0 && <li className="muted">Nenhum evento ainda.</li>}
        </ul>
      </div>
    </div>
  );
}
