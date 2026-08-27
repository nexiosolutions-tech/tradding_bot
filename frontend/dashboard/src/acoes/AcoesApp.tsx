import { useEffect, useState } from "react";
import type { ModuleKey } from "../components/ModuleSwitch";
import { acoesApi } from "./api/client";
import type { SaudeDoDado } from "./api/types";
import { AcoesSidebar, type AcoesViewKey } from "./components/AcoesSidebar";
import { CarteiraView } from "./views/CarteiraView";
import { EmpresasView } from "./views/EmpresasView";
import { HistoricoView } from "./views/HistoricoView";
import { MesAtualView } from "./views/MesAtualView";
import { SaudeDoDadoView } from "./views/SaudeDoDadoView";
import "./acoes.css";

export function AcoesApp({
  onSelectModule,
  acoesDisponivel,
}: {
  onSelectModule: (module: ModuleKey) => void;
  acoesDisponivel?: boolean;
}) {
  const [active, setActive] = useState<AcoesViewKey>("mes-atual");
  const [saude, setSaude] = useState<SaudeDoDado | null>(null);

  // Frescor global (Seção 11.2) — carregado uma vez, no shell, para o rodapé da
  // sidebar refletir o estado do dado em toda tela, não só na de Saúde do Dado.
  useEffect(() => {
    acoesApi.saudeDoDado().then(setSaude).catch(() => setSaude(null));
  }, []);

  return (
    <div className="acoes-shell" data-module="acoes">
      <AcoesSidebar
        active={active}
        onSelect={setActive}
        onSelectModule={onSelectModule}
        saude={saude}
        acoesDisponivel={acoesDisponivel}
      />
      <main className="acoes-content">
        {active === "mes-atual" && <MesAtualView />}
        {active === "empresas" && <EmpresasView />}
        {active === "carteira" && <CarteiraView />}
        {active === "saude-do-dado" && <SaudeDoDadoView />}
        {active === "historico" && <HistoricoView />}
      </main>
    </div>
  );
}
