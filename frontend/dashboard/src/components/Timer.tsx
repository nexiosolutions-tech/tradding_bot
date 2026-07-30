import { useEffect, useState } from "react";

function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return [hours, minutes, seconds].map((v) => String(v).padStart(2, "0")).join(":");
}

/** A ticking clock is something the operator glances at constantly — per the animation
 * skill guidance, it should never pulse or transition, just update the digits in place. */
export function Timer({
  sinceTs,
  label,
  inline = false,
}: {
  sinceTs: number | null | undefined;
  label: string;
  inline?: boolean;
}) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!sinceTs) return;
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [sinceTs]);

  const value = sinceTs ? formatElapsed(now - sinceTs) : "—";

  if (inline) {
    return <span className="num">{value}</span>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span className="muted" style={{ fontSize: 12 }}>
        {label}
      </span>
      <span className="num" style={{ fontSize: 22 }}>
        {value}
      </span>
    </div>
  );
}
