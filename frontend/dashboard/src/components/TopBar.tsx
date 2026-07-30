import { useEffect, useState } from "react";
import { IconChevronRight, IconClock } from "./Icons";

function formatUptime(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (days > 0) return `${days}d ${String(hours).padStart(2, "0")}h`;
  return [hours, minutes, seconds].map((v) => String(v).padStart(2, "0")).join(":");
}

export function TopBar({ viewLabel, startedAt }: { viewLabel: string; startedAt?: number | null }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!startedAt) return;
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [startedAt]);

  return (
    <div className="topbar">
      <div className="breadcrumb">
        <span>Trading Bot</span>
        <IconChevronRight width={13} height={13} />
        <strong>{viewLabel}</strong>
      </div>
      <div className="topbar__status">
        {startedAt && (
          <div className="topbar__uptime">
            <IconClock width={14} height={14} />
            <span className="num">{formatUptime(now - startedAt)}</span>
          </div>
        )}
      </div>
    </div>
  );
}
