import { useEffect, useState } from "react";
import { AcoesApp } from "./acoes/AcoesApp";
import { acoesApi } from "./acoes/api/client";
import { Sidebar, type ViewKey } from "./components/Sidebar";
import type { ModuleKey } from "./components/ModuleSwitch";
import { TopBar } from "./components/TopBar";
import { LiveView } from "./views/LiveView";
import { PerformanceView } from "./views/PerformanceView";
import { ModeloView } from "./views/ModeloView";
import { AprendizadoView } from "./views/AprendizadoView";
import { useEngineState } from "./hooks/useEngineState";

const LABELS: Record<ViewKey, string> = {
  live: "Live",
  performance: "Performance",
  modelo: "Modelo",
  aprendizado: "Aprendizado",
};

function App() {
  const [modulo, setModulo] = useState<ModuleKey>("cripto");
  const [active, setActive] = useState<ViewKey>("live");
  // Otimista (Seção 11.12): começa disponível para não piscar um estado desabilitado
  // no caso comum (local, rápido); só desabilita depois que a checagem confirmar que
  // o banco de Ações está vazio (produção sem volume/Postgres) — aí o ModuleSwitch
  // desabilita a aba antes de o erro acontecer, em vez de deixar cada tela falhar.
  const [acoesDisponivel, setAcoesDisponivel] = useState(true);
  // Single WebSocket for the whole app — the sidebar badge, topbar uptime, and Live view
  // all read from this one connection instead of each opening their own. Mantido mesmo
  // quando o módulo Ações está ativo (troca de módulo não desmonta a conexão, só a UI).
  const engineState = useEngineState();

  useEffect(() => {
    acoesApi
      .disponibilidade()
      .then((r) => setAcoesDisponivel(r.disponivel))
      .catch(() => setAcoesDisponivel(false)); // backend fora do ar tambem conta como indisponivel
  }, []);

  if (modulo === "acoes") {
    return <AcoesApp onSelectModule={setModulo} acoesDisponivel={acoesDisponivel} />;
  }

  return (
    <div className="app">
      <Sidebar
        active={active}
        onSelect={setActive}
        engineState={engineState?.state}
        onSelectModule={setModulo}
        acoesDisponivel={acoesDisponivel}
      />
      <div>
        <TopBar viewLabel={LABELS[active]} startedAt={engineState?.started_at} />
        <main className="content">
          {active === "live" && <LiveView state={engineState} />}
          {active === "performance" && <PerformanceView />}
          {active === "modelo" && <ModeloView />}
          {active === "aprendizado" && <AprendizadoView />}
        </main>
      </div>
    </div>
  );
}

export default App;
