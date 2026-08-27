// Seletor de nível acima do `CoinSelector` (spec 08, "Seletor de módulo Cripto/Ações")
// — troca o conjunto de itens da sidebar inteiro, nunca convive com ele como um dropdown
// a mais. Renderizado no topo de cada sidebar (cripto e Ações), por isso aceita
// `variant` para casar com o tema de cada uma sem duplicar lógica.
export type ModuleKey = "cripto" | "acoes";

export function ModuleSwitch({
  active,
  onSelect,
  variant,
  acoesDisponivel = true,
}: {
  active: ModuleKey;
  onSelect: (module: ModuleKey) => void;
  variant: "dark" | "light";
  // Seção 11.12: desabilita a aba Ações antes do erro acontecer, quando o banco está
  // vazio/inacessível neste ambiente (produção sem volume/Postgres) — nunca esconde a
  // aba (o usuário ainda precisa entender por que ela sumiria), só impede o clique e
  // explica no título.
  acoesDisponivel?: boolean;
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
        onClick={() => acoesDisponivel && onSelect("acoes")}
        disabled={!acoesDisponivel}
        title={acoesDisponivel ? undefined : "Módulo de Ações disponível apenas localmente neste ambiente"}
        style={acoesDisponivel ? undefined : { opacity: 0.45, cursor: "default" }}
      >
        Ações
      </button>
    </div>
  );
}
