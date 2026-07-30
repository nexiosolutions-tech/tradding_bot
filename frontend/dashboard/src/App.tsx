import { useState } from "react";
import { LiveView } from "./views/LiveView";
import { PerformanceView } from "./views/PerformanceView";
import { ModeloView } from "./views/ModeloView";
import { AprendizadoView } from "./views/AprendizadoView";

const VIEWS = [
  { key: "live", label: "Live", render: () => <LiveView /> },
  { key: "performance", label: "Performance", render: () => <PerformanceView /> },
  { key: "modelo", label: "Modelo", render: () => <ModeloView /> },
  { key: "aprendizado", label: "Aprendizado", render: () => <AprendizadoView /> },
] as const;

type ViewKey = (typeof VIEWS)[number]["key"];

function App() {
  const [active, setActive] = useState<ViewKey>("live");
  const view = VIEWS.find((v) => v.key === active)!;

  return (
    <div className="app">
      <header className="app__header">
        <span className="app__title">Trading Bot</span>
        <nav className="app__nav">
          {VIEWS.map((v) => (
            <button
              key={v.key}
              className={v.key === active ? "app__nav-item app__nav-item--active" : "app__nav-item"}
              onClick={() => setActive(v.key)}
            >
              {v.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="app__content">{view.render()}</main>
    </div>
  );
}

export default App;
