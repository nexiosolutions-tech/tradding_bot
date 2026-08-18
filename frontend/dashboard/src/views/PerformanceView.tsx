import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { EquityCurveChart } from "../components/EquityCurveChart";
import { TradesTable } from "../components/TradesTable";
import { IconBars, IconPlay } from "../components/Icons";
import { theme } from "../theme";
import type { BacktestDetail, BacktestSummary } from "../api/types";

// pnl_by_weekday keys follow Python's datetime.weekday() convention: Monday = 0.
const WEEKDAY_LABEL = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];

const DEFAULT_RUN_PARAMS = { symbol: "BTCUSDT", interval: "1m", days: 7 };

export function PerformanceView() {
  const [runs, setRuns] = useState<BacktestSummary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<BacktestDetail | null>(null);
  const [runPending, setRunPending] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const refreshRuns = () =>
    api.backtests().then((data) => {
      setRuns(data);
      return data;
    });

  useEffect(() => {
    refreshRuns().then((data) => {
      if (data.length > 0) setSelected(data[0].run_name);
    });
  }, []);

  useEffect(() => {
    if (!selected) return;
    api.backtestDetail(selected).then(setDetail);
  }, [selected]);

  const handleRunBacktest = async () => {
    setRunPending(true);
    setRunError(null);
    try {
      const result = await api.runBacktest(DEFAULT_RUN_PARAMS);
      await refreshRuns();
      setSelected(result.run_name);
    } catch (err) {
      setRunError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunPending(false);
    }
  };

  const hourlyData = useMemo(() => {
    if (!detail) return [];
    return Object.entries(detail.metrics.pnl_by_hour)
      .map(([hour, pnl]) => ({ hour: `${hour}h`, pnl }))
      .sort((a, b) => Number(a.hour.replace("h", "")) - Number(b.hour.replace("h", "")));
  }, [detail]);

  const weekdayData = useMemo(() => {
    if (!detail) return [];
    return Object.entries(detail.metrics.pnl_by_weekday)
      .map(([day, pnl]) => ({ day: WEEKDAY_LABEL[Number(day)] ?? day, dayIndex: Number(day), pnl }))
      .sort((a, b) => a.dayIndex - b.dayIndex);
  }, [detail]);

  if (runs === null) {
    return (
      <div className="panel">
        <div className="skeleton" style={{ height: 220 }} />
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="panel">
        <div className="empty-state">
          <div className="empty-state__icon">
            <IconBars />
          </div>
          <div className="empty-state__title">Nenhum backtest ainda</div>
          <p className="muted">
            Rode <code>python scripts/run_backtest.py</code> no backend, ou gere o primeiro relatório direto
            por aqui ({DEFAULT_RUN_PARAMS.symbol}, {DEFAULT_RUN_PARAMS.interval}, últimos{" "}
            {DEFAULT_RUN_PARAMS.days} dias).
          </p>
          <button className="icon-btn icon-btn--primary" disabled={runPending} onClick={handleRunBacktest}>
            <IconPlay width={13} height={13} /> {runPending ? "Rodando..." : "Rodar backtest"}
          </button>
          {runError && <p className="form-error">{runError}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="split-view">
      <div className="panel list-panel">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
          <h3>Backtests</h3>
          <button className="icon-btn" disabled={runPending} onClick={handleRunBacktest} title="Rodar novo backtest">
            <IconPlay width={13} height={13} /> {runPending ? "Rodando..." : "Novo"}
          </button>
        </div>
        {runError && <p className="form-error">{runError}</p>}
        <ul className="item-list">
          {runs.map((run) => (
            <li key={run.run_name}>
              <button
                className={run.run_name === selected ? "item-row item-row--active" : "item-row"}
                onClick={() => setSelected(run.run_name)}
              >
                <span className="item-row__label">{run.run_name}</span>
                <span className={`item-row__value delta ${run.metrics.total_pnl >= 0 ? "delta--positive" : "delta--negative"}`}>
                  {run.metrics.total_pnl.toFixed(2)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      {detail && (
        <div>
          <div className="panel metrics-grid">
            <Metric label="Trades" value={detail.metrics.num_trades} />
            <Metric label="Win rate" value={`${(detail.metrics.win_rate * 100).toFixed(1)}%`} />
            <Metric label="Profit factor" value={detail.metrics.profit_factor.toFixed(2)} />
            <Metric label="Drawdown máx." value={`${(detail.metrics.max_drawdown_pct * 100).toFixed(1)}%`} />
            <Metric label="Taxas pagas" value={detail.metrics.total_fees.toFixed(2)} />
            <Metric label="Capital final" value={detail.final_equity.toFixed(2)} />
          </div>

          <div className="panel">
            <h3>Curva de capital</h3>
            <EquityCurveChart points={detail.equity_curve} />
          </div>

          <div className="panel">
            <h3>P&amp;L por horário (UTC)</h3>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={hourlyData}>
                <CartesianGrid strokeDasharray="3 3" stroke={theme.border} />
                <XAxis dataKey="hour" stroke={theme.textMuted} fontSize={11} fontFamily="JetBrains Mono" />
                <YAxis stroke={theme.textMuted} fontSize={11} fontFamily="JetBrains Mono" />
                <Tooltip
                  contentStyle={{ background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: theme.textSecondary }}
                />
                <Bar dataKey="pnl" fill={theme.accent} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="panel">
            <h3>P&amp;L por dia da semana</h3>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={weekdayData}>
                <CartesianGrid strokeDasharray="3 3" stroke={theme.border} />
                <XAxis dataKey="day" stroke={theme.textMuted} fontSize={11} fontFamily="JetBrains Mono" />
                <YAxis stroke={theme.textMuted} fontSize={11} fontFamily="JetBrains Mono" />
                <Tooltip
                  contentStyle={{ background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: theme.textSecondary }}
                />
                <Bar dataKey="pnl" fill={theme.accent} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="panel">
            <h3>Trades ({detail.trades.length})</h3>
            <TradesTable trades={detail.trades} />
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metric">
      <span className="metric__label">{label}</span>
      <span className="metric__value">{value}</span>
    </div>
  );
}
