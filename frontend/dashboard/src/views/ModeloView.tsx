import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import type { ModelMetadata } from "../api/types";

export function ModeloView() {
  const [models, setModels] = useState<ModelMetadata[]>([]);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    api.models().then((data) => {
      setModels(data);
      if (data.length > 0) setSelected(data[0].version);
    });
  }, []);

  const model = models.find((m) => m.version === selected);

  if (models.length === 0) {
    return (
      <div className="panel">
        Nenhum modelo promovido ainda — a estratégia ativa é o placeholder da Fase 1. Ver{" "}
        <code>specs/11-roadmap-e-fases.md</code>.
      </div>
    );
  }

  const foldData = (model?.validation_summary.fold_profit_factors ?? []).map((pf, i) => ({
    fold: `Fold ${i}`,
    profit_factor: pf,
  }));

  return (
    <div className="performance-view">
      <div className="panel performance-view__list">
        <h3>Modelos</h3>
        <ul className="run-list">
          {models.map((m) => (
            <li key={m.version}>
              <button
                className={m.version === selected ? "run-list__item run-list__item--active" : "run-list__item"}
                onClick={() => setSelected(m.version)}
              >
                {m.version}
              </button>
            </li>
          ))}
        </ul>
      </div>

      {model && (
        <div className="performance-view__detail">
          <div className="panel metrics-grid">
            <Metric label="Entry threshold" value={model.entry_threshold.toFixed(2)} />
            <Metric label="Exit threshold" value={model.exit_threshold.toFixed(2)} />
            <Metric label="Stop-loss" value={`${(model.stop_loss_pct * 100).toFixed(1)}%`} />
            <Metric
              label="Folds vencidos"
              value={`${model.validation_summary.folds_won ?? 0}/${model.validation_summary.folds_total ?? 0}`}
            />
          </div>

          <div className="panel">
            <h3>Profit factor por fold (walk-forward)</h3>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={foldData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2733" />
                <XAxis dataKey="fold" stroke="#a8b3c5" fontSize={12} />
                <YAxis stroke="#a8b3c5" fontSize={12} />
                <Tooltip contentStyle={{ background: "#141a24", border: "1px solid #1f2733" }} />
                <Bar dataKey="profit_factor" fill="#c084fc" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="panel">
            <h3>Features</h3>
            <div className="tag-list">
              {model.feature_names.map((name) => (
                <span key={name} className="tag">
                  {name}
                </span>
              ))}
            </div>
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
