import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { EngineControls } from "../components/EngineControls";
import { ActivityConsole } from "../components/ActivityConsole";
import { TradesTable } from "../components/TradesTable";
import { IconTarget } from "../components/Icons";
import { Timer } from "../components/Timer";
import { MiniEquityChart } from "../components/MiniEquityChart";
import type { EngineEvent, EngineState, Trade } from "../api/types";

const MAX_EQUITY_SAMPLES = 400;

export function LiveView({ state }: { state: EngineState | null }) {
  const [events, setEvents] = useState<EngineEvent[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [equityHistory, setEquityHistory] = useState<[number, number][]>([]);
  const baselineEquity = useRef<number | null>(null);

  const refreshEvents = useCallback(() => {
    api.engineEvents(20).then(setEvents).catch(() => undefined);
  }, []);

  const refreshTrades = useCallback(() => {
    api.trades().then(setTrades).catch(() => undefined);
  }, []);

  useEffect(() => {
    refreshEvents();
    const interval = setInterval(refreshEvents, 5000);
    return () => clearInterval(interval);
  }, [refreshEvents]);

  useEffect(() => {
    refreshTrades();
    const interval = setInterval(refreshTrades, 15000);
    return () => clearInterval(interval);
  }, [refreshTrades]);

  useEffect(() => {
    if (state?.equity == null) return;
    if (baselineEquity.current === null) baselineEquity.current = state.equity;
    setEquityHistory((prev) => {
      const next: [number, number][] = [...prev, [Date.now(), state.equity as number]];
      return next.length > MAX_EQUITY_SAMPLES ? next.slice(-MAX_EQUITY_SAMPLES) : next;
    });
  }, [state?.equity]);

  if (!state) {
    return (
      <div className="panel">
        <div className="skeleton" style={{ height: 160 }} />
      </div>
    );
  }

  if (!state.configured) {
    return (
      <div className="panel panel--warning">
        <h2>Engine não configurado</h2>
        <p style={{ marginTop: 10 }}>{state.error}</p>
        <p className="muted" style={{ marginTop: 10 }}>
          Configure BINANCE_API_KEY / BINANCE_API_SECRET (testnet) no serviço do backend para
          ligar a execução ao vivo. As views Performance e Modelo continuam funcionando
          normalmente com os dados já existentes em <code>results/</code>.
        </p>
      </div>
    );
  }

  const delta = baselineEquity.current != null ? (state.equity ?? 0) - baselineEquity.current : 0;
  const deltaClass = delta > 0 ? "hero__delta--positive" : delta < 0 ? "hero__delta--negative" : "hero__delta--flat";

  return (
    <div>
      <div className="hero">
        <div className="hero__top">
          <div>
            <div className="hero__label">Capital — {state.symbol}</div>
            <div className="hero__equity">
              <span className="hero__equity-value">{state.equity?.toFixed(2)}</span>
              <span className="hero__equity-currency">USDT</span>
            </div>
            <div className={`hero__delta ${deltaClass}`}>
              {delta >= 0 ? "+" : ""}
              {delta.toFixed(2)} nesta sessão
            </div>
          </div>
          <EngineControls state={state.state} onChanged={refreshEvents} />
        </div>

        <div className="hero__chart">
          <MiniEquityChart points={equityHistory} />
        </div>

        <div className="hero__meta">
          <div className="hero__meta-item">
            <span className="hero__meta-label">Estratégia</span>
            <span className="hero__meta-value">{state.strategy_version}</span>
          </div>
          <div className="hero__meta-item">
            <span className="hero__meta-label">Operação aberta há</span>
            <Timer sinceTs={state.position?.entry_ts ?? null} label="" inline />
          </div>
        </div>
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
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <h3 style={{ margin: 0 }}>Atividade do engine</h3>
          <span className="live-pulse">
            <span className="live-pulse__dot" /> ao vivo
          </span>
        </div>
        <ActivityConsole entries={state.activity ?? []} />
      </div>

      <div className="panel">
        <h3>Trades recentes</h3>
        <TradesTable trades={trades} limit={10} />
      </div>

      <div className="panel">
        <h3>
          <IconTarget width={13} height={13} style={{ marginRight: 6, verticalAlign: -2 }} />
          Eventos de estado recentes
        </h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>Quando</th>
              <th>Transição</th>
              <th>Motivo</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {events.map((event, i) => (
              <tr key={i}>
                <td className="muted" style={{ fontWeight: 400 }}>
                  {new Date(event.ts).toLocaleString()}
                </td>
                <td>
                  {event.from_state} → {event.to_state}
                </td>
                <td className="muted" style={{ fontWeight: 400 }}>
                  {event.reason}
                </td>
                <td>{event.triggered_by_human && <span className="tag">manual</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {events.length === 0 && (
          <div className="empty-state">
            <div className="empty-state__title">Nenhum evento ainda</div>
            <p className="muted">Transições de estado aparecem aqui assim que o engine começar a operar.</p>
          </div>
        )}
      </div>
    </div>
  );
}
