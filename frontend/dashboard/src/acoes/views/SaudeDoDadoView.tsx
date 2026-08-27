import { useEffect, useState } from "react";
import { acoesApi } from "../api/client";
import type { SaudeDoDado } from "../api/types";
import { formatDataBr, formatMultiplo, formatPct } from "../format";

const RÓTULO_FONTE: Record<string, string> = {
  cvm_dfp_itr: "CVM (DFP/ITR)",
  cotahist: "COTAHIST (preço)",
  cdi: "BCB — CDI",
  ipca: "BCB — IPCA",
};

const RÓTULO_MOTIVO: Record<string, string> = {
  iliquido: "Ilíquido",
  classe_secundaria: "Classe secundária",
  identidade_nao_resolvida: "Identidade não resolvida",
  recuperacao_judicial: "Recuperação judicial",
  historico_insuficiente: "Histórico insuficiente",
  versao_indisponivel: "Versão indisponível",
};

export function SaudeDoDadoView() {
  const [dado, setDado] = useState<SaudeDoDado | null>(null);
  const [erro, setErro] = useState(false);

  useEffect(() => {
    acoesApi
      .saudeDoDado()
      .then(setDado)
      .catch(() => setErro(true));
  }, []);

  return (
    <>
      <div className="acoes-page-header">
        <h1>Saúde do dado</h1>
      </div>

      {erro && <div className="acoes-panel">Não foi possível carregar a saúde do dado.</div>}

      {!dado && !erro && (
        <div className="acoes-panel">
          <div className="acoes-skeleton" style={{ marginBottom: 10 }} />
          <div className="acoes-skeleton" style={{ width: "70%" }} />
        </div>
      )}

      {dado && (
        <>
          <div className="acoes-panel">
            <h3>Fontes</h3>
            <table className="acoes-table">
              <thead>
                <tr>
                  <th>Fonte</th>
                  <th>Última coleta</th>
                  <th className="acoes-num">Idade</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(dado.fontes).map(([chave, status]) => (
                  <tr key={chave}>
                    <td>{RÓTULO_FONTE[chave] ?? chave}</td>
                    <td className="acoes-num">{status.ultima_coleta ? formatDataBr(status.ultima_coleta) : "—"}</td>
                    <td className="acoes-num">{status.idade_dias !== undefined ? `${status.idade_dias}d` : "—"}</td>
                    <td>
                      <span className={`acoes-badge acoes-badge--${status.status === "ok" ? "ok" : "atencao"}`}>
                        {status.status === "ok" ? "Em dia" : "Atrasado"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="acoes-panel">
            <h3>Cobertura por era</h3>
            {dado.cobertura_por_ano.map((c) => (
              <div className="acoes-hbar-row" key={c.ano}>
                <span>
                  {c.ano}
                  <span
                    className={`acoes-badge acoes-badge--${c.era === "confiavel" ? "ok" : "atencao"}`}
                    style={{ marginLeft: 8 }}
                  >
                    {c.era === "confiavel" ? "confiável" : "reconciliada"}
                  </span>
                </span>
                <div className="acoes-hbar-track">
                  <div className="acoes-hbar-fill" style={{ width: `${Math.min(100, c.cobertura_pct * 100)}%` }} />
                </div>
                <span className="acoes-num">{formatPct(c.cobertura_pct, 0)}</span>
              </div>
            ))}
            <p style={{ fontSize: 12, color: "var(--acoes-tinta-2)", marginTop: 10 }}>
              Fronteira em 2018 — antes disso a identidade foi resolvida por propagação de
              CNPJ ou reconciliação de nome, não pelo FCA.
            </p>
          </div>

          <div className="acoes-panel">
            <h3>Exclusões deste mês ({dado.exclusoes_do_mes.total})</h3>
            {Object.keys(dado.exclusoes_do_mes.por_motivo).length === 0 && (
              <div className="acoes-empty-state">Nenhuma exclusão registrada nesta data.</div>
            )}
            {Object.entries(dado.exclusoes_do_mes.por_motivo)
              .sort((a, b) => b[1] - a[1])
              .map(([motivo, contagem]) => (
                <div className="acoes-hbar-row" key={motivo}>
                  <span>{RÓTULO_MOTIVO[motivo] ?? motivo}</span>
                  <div className="acoes-hbar-track">
                    <div
                      className="acoes-hbar-fill acoes-hbar-fill--muted"
                      style={{ width: `${Math.min(100, (contagem / dado.exclusoes_do_mes.total) * 100)}%` }}
                    />
                  </div>
                  <span className="acoes-num">{contagem}</span>
                </div>
              ))}
          </div>

          <div className="acoes-panel">
            <h3>Resultado do backtest</h3>
            {!dado.backtest && <div className="acoes-empty-state">Nenhum resultado de backtest publicado.</div>}
            {dado.backtest && <ResultadoBacktest backtest={dado.backtest} />}
          </div>
        </>
      )}
    </>
  );
}

function ResultadoBacktest({ backtest }: { backtest: NonNullable<SaudeDoDado["backtest"]> }) {
  return (
    <div>
      <p style={{ fontSize: 13.5, marginBottom: 14 }}>
        Os três fatores <strong>não se distinguiram do acaso</strong> na janela testada
        ({backtest.periodo.inicio.slice(0, 4)}-{backtest.periodo.fim.slice(0, 4)},
        p={backtest.nulidade.p_valor.toFixed(2).replace(".", ",")}) — o CDI superou as
        três carteiras simuladas.
      </p>
      <table className="acoes-table">
        <thead>
          <tr>
            <th></th>
            <th className="acoes-num">Retorno total</th>
            <th className="acoes-num">Retorno/Volatilidade</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Candidato (top-20, peso igual)</td>
            <td className="acoes-num">{formatPct(backtest.candidato_top20.total_return_pct, 1)}</td>
            <td className="acoes-num">{formatMultiplo(backtest.candidato_top20.return_over_volatility)}</td>
          </tr>
          <tr>
            <td>Equal-weight do universo</td>
            <td className="acoes-num">{formatPct(backtest.equal_weight_universo.total_return_pct, 1)}</td>
            <td className="acoes-num">{formatMultiplo(backtest.equal_weight_universo.return_over_volatility)}</td>
          </tr>
          <tr>
            <td>Ponderada por liquidez</td>
            <td className="acoes-num">{formatPct(backtest.ponderada_liquidez_universo.total_return_pct, 1)}</td>
            <td className="acoes-num">{formatMultiplo(backtest.ponderada_liquidez_universo.return_over_volatility)}</td>
          </tr>
          <tr>
            <td>CDI</td>
            <td className="acoes-num">{formatPct(backtest.cdi.total_return_pct, 1)}</td>
            <td className="acoes-num">—</td>
          </tr>
        </tbody>
      </table>
      <p style={{ fontSize: 12, color: "var(--acoes-tinta-2)", marginTop: 12 }}>
        Resultado computado em {formatDataBr(backtest.data_computado)} · teste de
        nulidade com {backtest.nulidade.n_permutacoes} permutações · metodologia em{" "}
        <code>specs/14-modulo-acoes-b3.md</code>, Seção 9.6.
      </p>
    </div>
  );
}
