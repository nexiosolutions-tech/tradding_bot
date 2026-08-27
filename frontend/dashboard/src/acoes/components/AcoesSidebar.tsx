import { ModuleSwitch, type ModuleKey } from "../../components/ModuleSwitch";
import type { SaudeDoDado } from "../api/types";
import { formatDataBr } from "../format";

export type AcoesViewKey = "mes-atual" | "empresas" | "carteira" | "saude-do-dado" | "historico";

const NAV_ITEMS: { key: AcoesViewKey; label: string }[] = [
  { key: "mes-atual", label: "Mês atual" },
  { key: "empresas", label: "Empresas" },
  { key: "carteira", label: "Minha carteira" },
  { key: "saude-do-dado", label: "Saúde do dado" },
  { key: "historico", label: "Histórico" },
];

// Rodapé com frescor do dado (Seção 11.2) — sempre visível, âmbar quando alguma fonte
// atrasa. `saude` pode estar carregando ainda (primeira tela aberta) — o rodapé não
// bloqueia nesse caso, só omite o detalhe até o dado chegar.
export function AcoesSidebar({
  active,
  onSelect,
  onSelectModule,
  saude,
}: {
  active: AcoesViewKey;
  onSelect: (view: AcoesViewKey) => void;
  onSelectModule: (module: ModuleKey) => void;
  saude: SaudeDoDado | null;
}) {
  const fontesOk = saude ? Object.values(saude.fontes).filter((f) => f.status === "ok").length : null;
  const totalFontes = saude ? Object.keys(saude.fontes).length : null;

  return (
    <aside className="acoes-sidebar">
      <ModuleSwitch active="acoes" onSelect={onSelectModule} variant="light" />

      <div className="acoes-sidebar__brand">Ações · B3</div>

      <nav className="acoes-sidebar__nav">
        {NAV_ITEMS.map(({ key, label }) => (
          <button
            key={key}
            className={key === active ? "acoes-sidebar__item acoes-sidebar__item--active" : "acoes-sidebar__item"}
            onClick={() => onSelect(key)}
          >
            {label}
          </button>
        ))}
      </nav>

      <div className="acoes-sidebar__spacer" />

      <div className="acoes-sidebar__footer">
        <span>Dado até</span>
        <div className="acoes-sidebar__footer-dado acoes-num">
          {saude ? formatDataBr(saude.data_decisao) : "—"}
        </div>
        {saude && (
          <span className="acoes-sidebar__footer-status">
            <span className={`acoes-dot${saude.todas_fontes_ok ? "" : " acoes-dot--atencao"}`} />
            {fontesOk}/{totalFontes} fontes ok
          </span>
        )}
      </div>
    </aside>
  );
}
