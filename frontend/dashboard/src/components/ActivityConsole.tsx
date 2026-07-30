import { useEffect, useRef } from "react";
import type { ActivityEntry } from "../api/types";

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString("pt-BR", { hour12: false });
}

export function ActivityConsole({ entries }: { entries: ActivityEntry[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const wasAtBottom = useRef(true);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && wasAtBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [entries]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    wasAtBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };

  if (entries.length === 0) {
    return (
      <div className="console">
        <div className="console__empty">Aguardando o próximo candle fechar…</div>
      </div>
    );
  }

  return (
    <div className="console" ref={scrollRef} onScroll={handleScroll}>
      {entries.map((entry, i) => (
        <div key={`${entry.ts}-${i}`} className={`console__line console__line--${entry.level}`}>
          <span className="console__ts">{formatTime(entry.ts)}</span>
          <span className="console__msg">{entry.message}</span>
        </div>
      ))}
    </div>
  );
}
