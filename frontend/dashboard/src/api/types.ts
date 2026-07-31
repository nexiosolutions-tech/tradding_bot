export type EngineStateValue =
  | "ANALISANDO"
  | "POSICAO_ABERTA"
  | "PAUSADO"
  | "PARADO_CIRCUIT_BREAKER";

export interface OpenPosition {
  entry_price: number;
  size: number;
  stop_loss_price: number;
  entry_ts: number;
}

export type ActivityLevel = "info" | "signal" | "trade" | "warning";

export interface ActivityEntry {
  ts: number;
  level: ActivityLevel;
  message: string;
}

export interface EngineState {
  configured: boolean;
  error?: string;
  symbol?: string;
  state?: EngineStateValue;
  equity?: number;
  strategy_version?: string;
  started_at?: number | null;
  position?: OpenPosition | null;
  activity?: ActivityEntry[];
}

export interface EngineEvent {
  ts: number;
  from_state: string;
  to_state: string;
  reason: string;
  triggered_by_human: boolean;
}

export interface Candle {
  ts: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ema_fast: number | null;
  ema_slow: number | null;
  bollinger_mid: number | null;
  bollinger_upper: number | null;
  bollinger_lower: number | null;
  rsi: number | null;
}

export interface Trade {
  symbol: string;
  entry_ts: number;
  exit_ts: number;
  entry_price: number;
  exit_price: number;
  size: number;
  pnl: number;
  fees_paid: number;
  exit_reason: string;
  strategy_version: string;
}

export interface BacktestMetrics {
  num_trades: number;
  win_rate: number;
  profit_factor: number;
  total_pnl: number;
  total_fees: number;
  max_drawdown_pct: number;
  max_drawdown_duration_ms: number;
  pnl_by_hour: Record<string, number>;
  pnl_by_weekday: Record<string, number>;
}

export interface BacktestSummary {
  run_name: string;
  metrics: BacktestMetrics;
  final_equity: number;
}

export interface BacktestDetail extends BacktestSummary {
  trades: Trade[];
  equity_curve: [number, number][];
  rejected_signals: string[];
  circuit_breaker_triggered: boolean;
}

export interface ModelMetadata {
  version: string;
  feature_names: string[];
  target_config: Record<string, unknown>;
  model_config: Record<string, unknown>;
  entry_threshold: number;
  exit_threshold: number;
  stop_loss_pct: number;
  validation_summary: {
    folds_won?: number;
    folds_total?: number;
    fold_profit_factors?: number[];
  };
}

export interface ChangeSummary {
  filename: string;
  status: string | null;
}

export interface DocDetail {
  filename: string;
  content: string;
  status?: string | null;
}
