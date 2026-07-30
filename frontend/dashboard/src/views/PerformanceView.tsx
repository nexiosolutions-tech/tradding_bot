import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { EquityCurveChart } from "../components/EquityCurveChart";
import { IconBars } from "../components/Icons";
import type { BacktestDetail, BacktestSummary } from "../api/types";

export function PerformanceView() {
  const [runs, setRuns] = useState<BacktestSummary[] | null>(null);
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
            Rode <code>python scripts/run_backtest.py</code> no backend para gerar o primeiro relatório.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="split-view">
      <div className="panel list-panel">
        <h3>Backtests</h3>
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
                <CartesianGrid strokeDasharray="3 3" stroke="#29271f" />
                <XAxis dataKey="hour" stroke="#7a7466" fontSize={11} fontFamily="JetBrains Mono" />
                <YAxis stroke="#7a7466" fontSize={11} fontFamily="JetBrains Mono" />
                <Tooltip
                  contentStyle={{ background: "#131210", border: "1px solid #29271f", borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: "#b3ac9e" }}
                />
                <Bar dataKey="pnl" fill="#d99a3d" radius={[3, 3, 0, 0]} />
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
      <span className="metric__label">{label}</span>
      <span className="metric__value">{value}</span>
    </div>
  );
}
