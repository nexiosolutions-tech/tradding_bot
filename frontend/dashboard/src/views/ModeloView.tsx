import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { IconNode } from "../components/Icons";
import { theme } from "../theme";
import type { ModelMetadata } from "../api/types";

export function ModeloView() {
  const [models, setModels] = useState<ModelMetadata[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    api.models().then((data) => {
      setModels(data);
      if (data.length > 0) setSelected(data[0].version);
    });
  }, []);

  const model = models?.find((m) => m.version === selected);

  if (models === null) {
    return (
      <div className="panel">
        <div className="skeleton" style={{ height: 220 }} />
      </div>
    );
  }

  if (models.length === 0) {
    return (
      <div className="panel">
        <div className="empty-state">
          <div className="empty-state__icon">
            <IconNode />
          </div>
          <div className="empty-state__title">Nenhum modelo promovido ainda</div>
          <p className="muted">
            A estratégia ativa é o placeholder da Fase 1. Ver <code>specs/11-roadmap-e-fases.md</code>.
          </p>
        </div>
      </div>
    );
  }

  const foldData = (model?.validation_summary.fold_profit_factors ?? []).map((pf, i) => ({
    fold: `Fold ${i}`,
    profit_factor: pf,
  }));

  return (
    <div className="split-view">
      <div className="panel list-panel">
        <h3>Modelos</h3>
        <ul className="item-list">
          {models.map((m) => (
            <li key={m.version}>
              <button
                className={m.version === selected ? "item-row item-row--active" : "item-row"}
                onClick={() => setSelected(m.version)}
              >
                <span className="item-row__label">{m.version}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      {model && (
        <div>
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
                <CartesianGrid strokeDasharray="3 3" stroke={theme.border} />
                <XAxis dataKey="fold" stroke={theme.textMuted} fontSize={11} fontFamily="JetBrains Mono" />
                <YAxis stroke={theme.textMuted} fontSize={11} fontFamily="JetBrains Mono" />
                <Tooltip
                  contentStyle={{ background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: theme.textSecondary }}
                />
                <Bar dataKey="profit_factor" fill={theme.accent} radius={[3, 3, 0, 0]} />
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
      <span className="metric__label">{label}</span>
      <span className="metric__value">{value}</span>
    </div>
  );
}
