import { useEffect, useState } from "react";
import { acoesApi } from "../api/client";
import type { EmpresaDetalhe, EmpresaRanking } from "../api/types";
import { FatorCell } from "../components/FatorCell";
import { IdentityBadge } from "../components/IdentityBadge";
import { formatDataBr, formatMultiplo, formatPct } from "../format";

export function EmpresasView() {
  const [lista, setLista] = useState<EmpresaRanking[] | null>(null);
  const [busca, setBusca] = useState("");
  const [selecionado, setSelecionado] = useState<string | null>(null);

  useEffect(() => {
    acoesApi
      .mesAtual()
      .then((dado) => {
        setLista(dado.ranking);
        if (dado.ranking.length > 0) setSelecionado((atual) => atual ?? dado.ranking[0].ticker);
      })
      .catch(() => setLista([]));
  }, []);

  const filtrada = (lista ?? []).filter(
    (e) => e.ticker.toLowerCase().includes(busca.toLowerCase()) || (e.setor_b3 ?? "").toLowerCase().includes(busca.toLowerCase())
  );

  return (
    <>
      <div className="acoes-page-header">
        <h1>Empresas</h1>
      </div>

      {lista === null && (
        <div className="acoes-panel">
          <div className="acoes-skeleton" />
        </div>
      )}

      {lista !== null && (
        <div className="acoes-split">
          <div className="acoes-panel acoes-split-list">
            <input
              className="acoes-search"
              placeholder="Buscar ticker ou setor…"
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
            />
            {filtrada.map((e) => (
              <button
                key={e.ticker}
                className={
                  e.ticker === selecionado ? "acoes-split-list__item acoes-split-list__item--active" : "acoes-split-list__item"
                }
                onClick={() => setSelecionado(e.ticker)}
              >
                <span className="acoes-num">{e.ticker}</span>
                <IdentityBadge selo={e.selo_identidade} />
                <span className="acoes-split-list__setor">{e.setor_b3 ?? "Sem classificação B3"}</span>
              </button>
            ))}
            {filtrada.length === 0 && <div className="acoes-empty-state">Nenhuma empresa encontrada.</div>}
          </div>

          {selecionado && <FichaEmpresa ticker={selecionado} />}
        </div>
      )}
    </>
  );
}

function FichaEmpresa({ ticker }: { ticker: string }) {
  const [ficha, setFicha] = useState<EmpresaDetalhe | null>(null);
  const [erro, setErro] = useState(false);

  useEffect(() => {
    setFicha(null);
    setErro(false);
    acoesApi
      .empresa(ticker)
      .then(setFicha)
      .catch(() => setErro(true));
  }, [ticker]);

  if (erro) return <div className="acoes-panel">Não foi possível carregar {ticker}.</div>;
  if (!ficha) {
    return (
      <div className="acoes-panel">
        <div className="acoes-skeleton" style={{ marginBottom: 10 }} />
        <div className="acoes-skeleton" style={{ width: "60%" }} />
      </div>
    );
  }

  const ultimaVigencia = ficha.vigencia_ticker[ficha.vigencia_ticker.length - 1];

  return (
    <div>
      <div className="acoes-panel">
        <div className="acoes-cabecalho-empresa">
          <h2>
            {ficha.ticker}
            <IdentityBadge selo={ficha.selo_identidade} />
          </h2>
          <span className="acoes-cabecalho-empresa__meta acoes-num">{ficha.cnpj}</span>
          <span className="acoes-cabecalho-empresa__meta">
            {ficha.setor_b3 ?? "Sem classificação B3"}
            {ficha.subsetor_b3 ? ` · ${ficha.subsetor_b3}` : ""}
            {ficha.segmento_b3 ? ` · ${ficha.segmento_b3}` : ""}
          </span>
          {ficha.vigencia_ticker.length > 1 && (
            <span className="acoes-cabecalho-empresa__meta">
              {ficha.vigencia_ticker
                .map(
                  (v) =>
                    `${v.ticker} ${v.data_fim_vigencia ? `até ${formatDataBr(v.data_fim_vigencia)}` : `desde ${formatDataBr(v.data_inicio_vigencia)}`}`
                )
                .join(" · ")}
            </span>
          )}
          {ultimaVigencia?.fonte && ultimaVigencia.fonte !== "fca" && (
            <span className="acoes-cabecalho-empresa__meta">Identidade resolvida por {ultimaVigencia.fonte}</span>
          )}
        </div>
      </div>

      <div className="acoes-panel">
        <h3>Fatores hoje</h3>
        <div className="acoes-fatores-hoje-grid">
          <BlocoFator titulo="Earnings yield" detalhe={ficha.fatores_hoje.earnings_yield} formatar={(v) => formatPct(v)} />
          <BlocoFator
            titulo="Dívida líquida / EBITDA"
            detalhe={ficha.fatores_hoje.divida_liquida_ebitda}
            formatar={(v) => formatMultiplo(v)}
          />
          <BlocoFator titulo="ROE" detalhe={ficha.fatores_hoje.roe} formatar={(v) => formatPct(v)} />
        </div>
      </div>

      <div className="acoes-panel">
        <h3>Linha do tempo de conhecimento</h3>
        <p className="acoes-cabecalho-empresa__meta" style={{ marginBottom: 10 }}>
          O valor de cada fator como estava público em cada data de decisão — não o valor
          final conhecido hoje.
        </p>
        <div style={{ overflowX: "auto" }}>
          <table className="acoes-table acoes-timeline-table">
            <thead>
              <tr>
                <th>Data de decisão</th>
                <th className="acoes-num">Earnings yield</th>
                <th className="acoes-num">DL/EBITDA</th>
                <th className="acoes-num">ROE</th>
              </tr>
            </thead>
            <tbody>
              {ficha.linha_do_tempo_conhecimento.map((p) => (
                <tr key={p.data_decisao}>
                  <td className="acoes-num">{formatDataBr(p.data_decisao)}</td>
                  <td className="acoes-num">{p.earnings_yield !== null ? formatPct(p.earnings_yield) : "s/d"}</td>
                  <td className="acoes-num">
                    {p.divida_liquida_ebitda !== null ? formatMultiplo(p.divida_liquida_ebitda) : "n/a"}
                  </td>
                  <td className="acoes-num">{p.roe !== null ? formatPct(p.roe) : "s/d"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="acoes-panel">
        <h3>Histórico de entregas à CVM</h3>
        <p className="acoes-cabecalho-empresa__meta" style={{ marginBottom: 10 }}>
          {ficha.retificacoes_ultimos_5_anos} retificação(ões) nos últimos 5 anos.
        </p>
        <div style={{ overflowX: "auto" }}>
          <table className="acoes-table acoes-timeline-table">
            <thead>
              <tr>
                <th>Exercício</th>
                <th className="acoes-num">Versão</th>
                <th className="acoes-num">Recebido pela CVM</th>
              </tr>
            </thead>
            <tbody>
              {ficha.historico_entregas_cvm.map((f, i) => (
                <tr key={`${f.dt_refer}-${f.versao}-${i}`}>
                  <td className="acoes-num">{formatDataBr(f.dt_refer)}</td>
                  <td className="acoes-num">v{f.versao}</td>
                  <td className="acoes-num">{formatDataBr(f.dt_receb)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function BlocoFator({
  titulo,
  detalhe,
  formatar,
}: {
  titulo: string;
  detalhe: EmpresaDetalhe["fatores_hoje"]["earnings_yield"];
  formatar: (v: number) => string;
}) {
  return (
    <div>
      <div className="acoes-fator-bloco__label">{titulo}</div>
      <FatorCell detalhe={detalhe} formatar={formatar} />
      {detalhe.motivo && (
        <p className="acoes-cabecalho-empresa__meta" style={{ marginTop: 6 }}>
          {detalhe.motivo === "inaplicavel" && "O fator não se aplica ao setor desta empresa."}
          {detalhe.motivo === "indefinido" && "Aplicável, mas indefinido para esta empresa."}
          {detalhe.motivo === "sem_dado" && "A empresa não reportou este campo."}
          {detalhe.motivo === "versao_indisponivel" && "A versão vigente não está no arquivo público da CVM."}
        </p>
      )}
    </div>
  );
}
