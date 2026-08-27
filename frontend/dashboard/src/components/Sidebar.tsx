import { IconBars, IconBook, IconNode, IconPulse, IconSpark } from "./Icons";
import { ModuleSwitch, type ModuleKey } from "./ModuleSwitch";
import { StateBadge } from "./StateBadge";
import type { EngineStateValue } from "../api/types";

export type ViewKey = "live" | "performance" | "modelo" | "aprendizado";

const NAV_ITEMS: { key: ViewKey; label: string; icon: typeof IconPulse }[] = [
  { key: "live", label: "Live", icon: IconPulse },
  { key: "performance", label: "Performance", icon: IconBars },
  { key: "modelo", label: "Modelo", icon: IconNode },
  { key: "aprendizado", label: "Aprendizado", icon: IconBook },
];

export function Sidebar({
  active,
  onSelect,
  engineState,
  onSelectModule,
  acoesDisponivel,
}: {
  active: ViewKey;
  onSelect: (view: ViewKey) => void;
  engineState?: EngineStateValue;
  onSelectModule: (module: ModuleKey) => void;
  acoesDisponivel?: boolean;
}) {
  return (
    <aside className="sidebar">
      <ModuleSwitch active="cripto" onSelect={onSelectModule} variant="dark" acoesDisponivel={acoesDisponivel} />

      <div className="sidebar__brand">
        <div className="sidebar__brand-mark">
          <IconSpark width={15} height={15} />
        </div>
        <span className="sidebar__brand-name">Trading Bot</span>
      </div>

      <nav className="sidebar__nav">
        {NAV_ITEMS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            className={key === active ? "sidebar__item sidebar__item--active" : "sidebar__item"}
            onClick={() => onSelect(key)}
          >
            <Icon />
            {label}
          </button>
        ))}
      </nav>

      <div className="sidebar__spacer" />

      <div className="sidebar__footer">
        <span className="sidebar__footer-label">Engine</span>
        <div style={{ padding: "0 8px" }}>
          <StateBadge state={engineState} />
        </div>
      </div>
    </aside>
  );
}
