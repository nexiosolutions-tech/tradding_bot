import type {
  BacktestDetail,
  BacktestSummary,
  ChangeSummary,
  DocDetail,
  EngineEvent,
  EngineState,
  ModelMetadata,
  Trade,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error(`${path} -> ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail ?? `${path} -> ${response.status}`);
  }
  return data as T;
}

export const api = {
  engineState: () => getJSON<EngineState>("/api/engine/state"),
  engineEvents: (limit = 50) => getJSON<EngineEvent[]>(`/api/engine/events?limit=${limit}`),
  trades: () => getJSON<Trade[]>("/api/trades"),
  pause: (by: string) => postJSON<{ state: string }>("/api/engine/pause", { by }),
  resume: (by: string) => postJSON<{ state: string }>("/api/engine/resume", { by }),
  acknowledgeCircuitBreaker: (by: string) =>
    postJSON<{ state: string }>("/api/engine/acknowledge_circuit_breaker", { by }),

  backtests: () => getJSON<BacktestSummary[]>("/api/backtests"),
  backtestDetail: (runName: string) => getJSON<BacktestDetail>(`/api/backtests/${runName}`),

  models: () => getJSON<ModelMetadata[]>("/api/models"),
  modelDetail: (version: string) => getJSON<ModelMetadata>(`/api/models/${version}`),

  learnings: () => getJSON<string[]>("/api/learnings"),
  learningDetail: (filename: string) => getJSON<DocDetail>(`/api/learnings/${filename}`),

  changes: () => getJSON<ChangeSummary[]>("/api/changes"),
  changeDetail: (filename: string) => getJSON<DocDetail>(`/api/changes/${filename}`),

  wsUrl: () => `${BASE_URL.replace(/^http/, "ws")}/ws/engine`,
};
