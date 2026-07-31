import { IconClock } from "./Icons";
import type { Trade } from "../api/types";

const EXIT_REASON_LABEL: Record<string, string> = {
  stop_loss: "stop-loss",
  signal_exit: "sinal",
  end_of_data: "fim dos dados",
  emergency_close_no_stop_loss: "fechamento emergencial",
};

const EXIT_REASON_TAG_CLASS: Record<string, string> = {
  stop_loss: "tag tag--negative",
  emergency_close_no_stop_loss: "tag tag--negative",
  signal_exit: "tag",
  end_of_data: "tag",
};

function formatTs(ts: number): string {
  return new Date(ts).toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDuration(entryTs: number, exitTs: number): string {
  const minutes = Math.max(0, Math.round((exitTs - entryTs) / 60_000));
  if (minutes < 60) return `${minutes}min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}h${rest}min` : `${hours}h`;
}

export function TradesTable({ trades, limit }: { trades: Trade[]; limit?: number }) {
  const sorted = [...trades].sort((a, b) => b.exit_ts - a.exit_ts);
  const rows = limit ? sorted.slice(0, limit) : sorted;

  if (rows.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state__icon">
          <IconClock />
        </div>
        <div className="empty-state__title">Nenhum trade ainda</div>
        <p className="muted">Trades fechados aparecem aqui assim que o engine executar uma saída.</p>
      </div>
    );
  }

  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Saída em</th>
          <th>Duração</th>
          <th className="num">Entrada</th>
          <th className="num">Saída</th>
          <th className="num">Tamanho</th>
          <th className="num">P&amp;L</th>
          <th className="num">Taxas</th>
          <th>Motivo</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((trade, i) => (
          <tr key={`${trade.entry_ts}-${i}`}>
            <td className="muted" style={{ fontWeight: 400 }}>
              {formatTs(trade.exit_ts)}
            </td>
            <td className="muted num" style={{ fontWeight: 400 }}>
              {formatDuration(trade.entry_ts, trade.exit_ts)}
            </td>
            <td className="num">{trade.entry_price.toFixed(2)}</td>
            <td className="num">{trade.exit_price.toFixed(2)}</td>
            <td className="num">{trade.size.toFixed(6)}</td>
            <td className={`num delta ${trade.pnl >= 0 ? "delta--positive" : "delta--negative"}`}>
              {trade.pnl >= 0 ? "+" : ""}
              {trade.pnl.toFixed(2)}
            </td>
            <td className="num muted" style={{ fontWeight: 400 }}>
              {trade.fees_paid.toFixed(2)}
            </td>
            <td>
              <span className={EXIT_REASON_TAG_CLASS[trade.exit_reason] ?? "tag"}>
                {EXIT_REASON_LABEL[trade.exit_reason] ?? trade.exit_reason}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
