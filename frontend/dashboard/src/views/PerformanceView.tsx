import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { EquityCurveChart } from "../components/EquityCurveChart";
import type { BacktestDetail, BacktestSummary } from "../api/types";

export function PerformanceView() {
  const [runs, setRuns] = useState<BacktestSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<BacktestDetail | null>(null);

  useEffect(() => {
    api.backtests().then((data) => {
      setRuns(data);
      if (data.length > 0) setSelected(data[0].run_name);
    });
  }, []);

  useEffect(() => {
    if (!selected) return;
    api.backtestDetail(selected).then(setDetail);
  }, [selected]);

  const hourlyData = useMemo(() => {
    if (!detail) return [];
    return Object.entries(detail.metrics.pnl_by_hour)
      .map(([hour, pnl]) => ({ hour: `${hour}h`, pnl }))
      .sort((a, b) => Number(a.hour.replace("h", "")) - Number(b.hour.replace("h", "")));
  }, [detail]);

  if (runs.length === 0) {
    return <div className="panel">Nenhum backtest encontrado em results/ ainda.</div>;
  }

  return (
    <div className="performance-view">
      <div className="panel performance-view__list">
        <h3>Backtests</h3>
        <ul className="run-list">
          {runs.map((run) => (
            <li key={run.run_name}>
              <button
                className={run.run_name === selected ? "run-list__item run-list__item--active" : "run-list__item"}
                onClick={() => setSelected(run.run_name)}
              >
                <span>{run.run_name}</span>
                <span className={run.metrics.total_pnl >= 0 ? "pnl pnl--positive" : "pnl pnl--negative"}>
                  {run.metrics.total_pnl.toFixed(2)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      {detail && (
        <div className="performance-view__detail">
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
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2733" />
                <XAxis dataKey="hour" stroke="#a8b3c5" fontSize={12} />
                <YAxis stroke="#a8b3c5" fontSize={12} />
                <Tooltip contentStyle={{ background: "#141a24", border: "1px solid #1f2733" }} />
                <Bar dataKey="pnl" fill="#60a5fa" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metric">
      <span className="muted">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
