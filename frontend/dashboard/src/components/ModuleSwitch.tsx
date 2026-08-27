// Seletor de nível acima do `CoinSelector` (spec 08, "Seletor de módulo Cripto/Ações")
// — troca o conjunto de itens da sidebar inteiro, nunca convive com ele como um dropdown
// a mais. Renderizado no topo de cada sidebar (cripto e Ações), por isso aceita
// `variant` para casar com o tema de cada uma sem duplicar lógica.
export type ModuleKey = "cripto" | "acoes";

export function ModuleSwitch({
  active,
  onSelect,
  variant,
}: {
  active: ModuleKey;
  onSelect: (module: ModuleKey) => void;
  variant: "dark" | "light";
}) {
  const prefix = variant === "light" ? "acoes-module-switch" : "sidebar__module-switch";
  return (
    <div className={prefix}>
      <button
        className={active === "cripto" ? `${prefix}__item ${prefix}__item--active` : `${prefix}__item`}
        onClick={() => onSelect("cripto")}
      >
        Cripto
      </button>
      <button
        className={active === "acoes" ? `${prefix}__item ${prefix}__item--active` : `${prefix}__item`}
        onClick={() => onSelect("acoes")}
      >
        Ações
      </button>
    </div>
  );
}
