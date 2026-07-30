import { useEffect, useState } from "react";
import { api } from "../api/client";
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
    <div className="performance-view">
      <div className="panel performance-view__list">
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
          <ul className="run-list">
            {learnings.map((filename) => (
              <li key={filename}>
                <button className="run-list__item" onClick={() => openLearning(filename)}>
                  {filename}
                </button>
              </li>
            ))}
            {learnings.length === 0 && <li className="muted">Nenhum relatório ainda.</li>}
          </ul>
        ) : (
          <ul className="run-list">
            {changes.map((change) => (
              <li key={change.filename}>
                <button className="run-list__item" onClick={() => openChange(change.filename)}>
                  <span>{change.filename}</span>
                  {change.status && <span className="tag">{change.status}</span>}
                </button>
              </li>
            ))}
            {changes.length === 0 && <li className="muted">Nenhuma proposta ainda.</li>}
          </ul>
        )}
      </div>

      <div className="panel performance-view__detail">
        {doc ? (
          <pre className="markdown-doc">{doc.content}</pre>
        ) : (
          <p className="muted">Selecione um documento para visualizar.</p>
        )}
      </div>
    </div>
  );
}
