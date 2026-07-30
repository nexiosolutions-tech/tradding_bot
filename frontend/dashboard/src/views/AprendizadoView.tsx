import { useEffect, useState } from "react";
import { api } from "../api/client";
import { IconBook } from "../components/Icons";
import type { ChangeSummary, DocDetail } from "../api/types";

export function AprendizadoView() {
  const [learnings, setLearnings] = useState<string[]>([]);
  const [changes, setChanges] = useState<ChangeSummary[]>([]);
  const [doc, setDoc] = useState<DocDetail | null>(null);
  const [activeList, setActiveList] = useState<"learnings" | "changes">("learnings");

  useEffect(() => {
    api.learnings().then(setLearnings);
    api.changes().then(setChanges);
  }, []);

  const openLearning = (filename: string) => api.learningDetail(filename).then(setDoc);
  const openChange = (filename: string) => api.changeDetail(filename).then(setDoc);

  return (
    <div className="split-view">
      <div className="panel list-panel">
        <div className="tabs">
          <button
            className={activeList === "learnings" ? "tab tab--active" : "tab"}
            onClick={() => setActiveList("learnings")}
          >
            Learnings
          </button>
          <button
            className={activeList === "changes" ? "tab tab--active" : "tab"}
            onClick={() => setActiveList("changes")}
          >
            Changes
          </button>
        </div>

        {activeList === "learnings" ? (
          <ul className="item-list">
            {learnings.map((filename) => (
              <li key={filename}>
                <button className="item-row" onClick={() => openLearning(filename)}>
                  <span className="item-row__label">{filename}</span>
                </button>
              </li>
            ))}
            {learnings.length === 0 && <li className="muted" style={{ padding: "9px 11px", fontSize: 13 }}>Nenhum relatório ainda.</li>}
          </ul>
        ) : (
          <ul className="item-list">
            {changes.map((change) => (
              <li key={change.filename}>
                <button className="item-row" onClick={() => openChange(change.filename)}>
                  <span className="item-row__label">{change.filename}</span>
                  {change.status && <span className="tag">{change.status}</span>}
                </button>
              </li>
            ))}
            {changes.length === 0 && <li className="muted" style={{ padding: "9px 11px", fontSize: 13 }}>Nenhuma proposta ainda.</li>}
          </ul>
        )}
      </div>

      <div className="panel">
        {doc ? (
          <pre className="markdown-doc">{doc.content}</pre>
        ) : (
          <div className="empty-state">
            <div className="empty-state__icon">
              <IconBook />
            </div>
            <div className="empty-state__title">Selecione um documento</div>
            <p className="muted">Escolha um item na lista ao lado para visualizar o conteúdo.</p>
          </div>
        )}
      </div>
    </div>
  );
}
