import { useEffect, useState } from "react";
import { acoesApi } from "../api/client";
import type { HistoricoDetalhe } from "../api/types";
import { IdentityBadge } from "../components/IdentityBadge";
import { formatDataBr, formatPct, formatScore } from "../format";

export function HistoricoView() {
  const [datas, setDatas] = useState<string[] | null>(null);
  const [selecionada, setSelecionada] = useState<string | null>(null);

  useEffect(() => {
    acoesApi
      .historicoLista()
      .then((r) => {
        setDatas(r.datas_decisao);
        if (r.datas_decisao.length > 0) setSelecionada(r.datas_decisao[r.datas_decisao.length - 1]);
      })
      .catch(() => setDatas([]));
  }, []);

  return (
    <>
      <div className="acoes-page-header">
        <h1>Histórico</h1>
      </div>

      {datas === null && (
        <div className="acoes-panel">
          <div className="acoes-skeleton" />
        </div>
      )}

      {datas !== null && (
        <div className="acoes-split">
          <div className="acoes-panel acoes-split-list">
            {datas.map((d) => (
              <button
                key={d}
                className={d === selecionada ? "acoes-split-list__item acoes-split-list__item--active" : "acoes-split-list__item"}
                onClick={() => setSelecionada(d)}
              >
                {formatDataBr(d)}
              </button>
            ))}
          </div>

          {selecionada && <DetalheData data={selecionada} />}
        </div>
      )}
    </>
  );
}

function DetalheData({ data }: { data: string }) {
  const [detalhe, setDetalhe] = useState<HistoricoDetalhe | null>(null);
  const [erro, setErro] = useState(false);

  useEffect(() => {
    setDetalhe(null);
    setErro(false);
    acoesApi
      .historicoDetalhe(data)
      .then(setDetalhe)
      .catch(() => setErro(true));
  }, [data]);

  if (erro) return <div className="acoes-panel">Não foi possível reconstruir o painel desta data.</div>;
  if (!detalhe) {
    return (
      <div className="acoes-panel">
        <div className="acoes-skeleton" style={{ marginBottom: 10 }} />
        <div className="acoes-skeleton" style={{ width: "60%" }} />
      </div>
    );
  }

  const topo10 = detalhe.ranking.filter((e) => e.score_composto !== null).slice(0, 10);
  const base10 = detalhe.ranking.filter((e) => e.score_composto !== null).slice(-10);

  return (
    <div>
      <div className="acoes-panel">
        <h3>Painel reconstruído — {formatDataBr(detalhe.data_decisao)}</h3>
        <p style={{ fontSize: 12.5, color: "var(--acoes-tinta-2)", marginBottom: 10 }}>
          Mesmo universo, mesmos fatores, mesmos carimbos de então — {detalhe.elegiveis}{" "}
          empresas elegíveis, {detalhe.com_score} com pelo menos um fator real.
        </p>
      </div>

      <div className="acoes-grid-2">
        <div className="acoes-panel">
          <h3>Retorno subsequente — topo do ranking (10 maiores score)</h3>
          <TabelaRetorno retornos={detalhe.retorno_subsequente_topo_10} />
        </div>
        <div className="acoes-panel">
          <h3>Retorno subsequente — base do ranking (10 menores score)</h3>
          <TabelaRetorno retornos={detalhe.retorno_subsequente_base_10} />
        </div>
      </div>

      <div className="acoes-panel">
        <h3>Topo do ranking naquela data</h3>
        <table className="acoes-table">
          <thead>
            <tr>
              <th>Empresa</th>
              <th className="acoes-num">Score</th>
            </tr>
          </thead>
          <tbody>
            {topo10.map((e) => (
              <tr key={e.ticker}>
                <td>
                  {e.ticker}
                  <IdentityBadge selo={e.selo_identidade} />
                </td>
                <td className="acoes-num">{formatScore(e.score_composto)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="acoes-panel">
        <h3>Base do ranking naquela data</h3>
        <table className="acoes-table">
          <thead>
            <tr>
              <th>Empresa</th>
              <th className="acoes-num">Score</th>
            </tr>
          </thead>
          <tbody>
            {base10.map((e) => (
              <tr key={e.ticker}>
                <td>
                  {e.ticker}
                  <IdentityBadge selo={e.selo_identidade} />
                </td>
                <td className="acoes-num">{formatScore(e.score_composto)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TabelaRetorno({ retornos }: { retornos: Record<string, number | null> }) {
  return (
    <table className="acoes-table">
      <thead>
        <tr>
          <th>Horizonte</th>
          <th className="acoes-num">Retorno médio</th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(retornos).map(([horizonte, valor]) => (
          <tr key={horizonte}>
            <td>{horizonte}</td>
            <td className="acoes-num">{valor !== null ? formatPct(valor, 1) : "s/d"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
