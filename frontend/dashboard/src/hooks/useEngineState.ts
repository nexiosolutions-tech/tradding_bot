import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { EngineState } from "../api/types";

/** Prefers the WebSocket push; falls back to polling if the socket drops. Either path
 * lands in the same state, so the Live view never has to know which one is active. */
export function useEngineState() {
  const [state, setState] = useState<EngineState | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let cancelled = false;

    const startPolling = () => {
      if (pollRef.current) return;
      pollRef.current = setInterval(() => {
        api.engineState().then(setState).catch(() => undefined);
      }, 3000);
    };

    try {
      socket = new WebSocket(api.wsUrl());
      socket.onmessage = (event) => {
        if (cancelled) return;
        setState(JSON.parse(event.data));
      };
      socket.onerror = startPolling;
      socket.onclose = startPolling;
    } catch {
      startPolling();
    }

    api.engineState().then(setState).catch(() => undefined);

    return () => {
      cancelled = true;
      socket?.close();
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  return state;
}
