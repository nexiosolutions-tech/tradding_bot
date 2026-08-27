import { useEffect, useState } from "react";
import { acoesApi } from "../api/client";
import type { MesAtual } from "../api/types";
import { FatorCell } from "../components/FatorCell";
import { IdentityBadge } from "../components/IdentityBadge";
import { MethodBanner } from "../components/MethodBanner";
import { formatMesAno, formatPct, formatScore, formatMultiplo } from "../format";

type Carregamento = { status: "carregando" } | { status: "erro"; mensagem: string } | { status: "ok"; dado: MesAtual };

function proximoMes(ano: number, mes: number, direcao: 1 | -1): { ano: number; mes: number } {
  const m = mes + direcao;
  if (m > 12) return { ano: ano + 1, mes: 1 };
  if (m < 1) return { ano: ano - 1, mes: 12 };
  return { ano, mes: m };
}

export function MesAtualView() {
  const hoje = new Date();
  const [{ ano, mes }, setPeriodo] = useState({ ano: hoje.getFullYear(), mes: hoje.getMonth() + 1 });
  const [estado, setEstado] = useState<Carregamento>({ status: "carregando" });
  const [setorAberto, setSetorAberto] = useState(false);

  useEffect(() => {
    setEstado({ status: "carregando" });
    acoesApi
      .mesAtual(ano, mes)
      .then((dado) => setEstado({ status: "ok", dado }))
      .catch((err) => setEstado({ status: "erro", mensagem: String(err) }));
  }, [ano, mes]);

  return (
    <>
      <div className="acoes-page-header">
        <h1>{formatMesAno(`${ano}-${String(mes).padStart(2, "0")}`)}</h1>
        <div className="acoes-month-nav">
          <button onClick={() => setPeriodo(proximoMes(ano, mes, -1))}>◀ mês</button>
          <button
            onClick={() => setPeriodo(proximoMes(ano, mes, 1))}
            disabled={ano === hoje.getFullYear() && mes === hoje.getMonth() + 1}
          >
            mês ▶
          </button>
        </div>
      </div>

      {estado.status === "carregando" && (
        <div className="acoes-panel">
          <div className="acoes-skeleton" style={{ marginBottom: 10 }} />
          <div className="acoes-skeleton" style={{ marginBottom: 10, width: "70%" }} />
          <div className="acoes-empty-state">
            Recalculando o universo elegível para este mês — a primeira consulta de uma
            data nova pode levar até 30 segundos.
          </div>
        </div>
      )}

      {estado.status === "erro" && (
        <div className="acoes-panel">
          <div className="acoes-empty-state">Não foi possível carregar este mês ({estado.mensagem}).</div>
        </div>
      )}

      {estado.status === "ok" && <ConteudoMes dado={estado.dado} setorAberto={setorAberto} onToggleSetor={() => setSetorAberto((v) => !v)} />}
    </>
  );
}

function ConteudoMes({
  dado,
  setorAberto,
  onToggleSetor,
}: {
  dado: MesAtual;
  setorAberto: boolean;
  onToggleSetor: () => void;
}) {
  const setoresPequenos = dado.distribuicao_setorial.filter((s) => s.amostra_pequena);

  return (
    <>
      <div className="acoes-grid-4">
        <div className="acoes-stat">
          <div className="acoes-stat__label">Elegíveis</div>
          <div className="acoes-stat__value">{dado.elegiveis}</div>
        </div>
        <div className="acoes-stat">
          <div className="acoes-stat__label">Com score</div>
          <div className="acoes-stat__value">{dado.com_score}</div>
          <div className="acoes-stat__sub">{formatPct(dado.cobertura_pct, 1)} do universo</div>
        </div>
        <div className="acoes-stat">
          <div className="acoes-stat__label">Excluídas</div>
          <div className="acoes-stat__value">{dado.excluidas}</div>
        </div>
        <div className="acoes-stat">
          <div className="acoes-stat__label">Cobertura</div>
          <div className="acoes-stat__value">{formatPct(dado.cobertura_pct, 1)}</div>
        </div>
      </div>

      <MethodBanner />

      <div className="acoes-panel">
        <h3>Empresas elegíveis</h3>
        <div style={{ overflowX: "auto" }}>
          <table className="acoes-table">
            <thead>
              <tr>
                <th>Empresa</th>
                <th>Setor</th>
                <th className="acoes-num">E. Yield</th>
                <th className="acoes-num">DL/EBITDA</th>
                <th className="acoes-num">ROE</th>
                <th className="acoes-num">Score</th>
              </tr>
            </thead>
            <tbody>
              {dado.ranking.map((empresa) => (
                <tr key={empresa.ticker}>
                  <td>
                    <span className="acoes-empresa-nome">{empresa.ticker}</span>
                    <IdentityBadge selo={empresa.selo_identidade} />
                  </td>
                  <td className="acoes-empresa-setor">{empresa.setor_b3 ?? "Sem classificação B3"}</td>
                  <td className="acoes-num">
                    <FatorCell detalhe={empresa.earnings_yield} formatar={(v) => formatPct(v)} />
                  </td>
                  <td className="acoes-num">
                    <FatorCell detalhe={empresa.divida_liquida_ebitda} formatar={(v) => formatMultiplo(v)} />
                  </td>
                  <td className="acoes-num">
                    <FatorCell detalhe={empresa.roe} formatar={(v) => formatPct(v)} />
                  </td>
                  <td className="acoes-num acoes-fator-valor">{formatScore(empresa.score_composto)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="acoes-grid-2">
        <div className="acoes-panel">
          <h3>Distribuição por setor</h3>
          {dado.distribuicao_setorial.map((s) => (
            <div className="acoes-hbar-row" key={s.setor}>
              <span title={s.setor} style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {s.setor}
              </span>
              <div className="acoes-hbar-track">
                <div
                  className={s.amostra_pequena ? "acoes-hbar-fill acoes-hbar-fill--muted" : "acoes-hbar-fill"}
                  style={{ width: `${Math.min(100, s.pct * 100)}%` }}
                />
              </div>
              <span className="acoes-num">{formatPct(s.pct, 0)}</span>
            </div>
          ))}
          {setoresPequenos.length > 0 && (
            <button className="acoes-stat__sub--clicavel" onClick={onToggleSetor} style={{ marginTop: 10 }}>
              {setoresPequenos.length} setor(es) com menos de 6 empresas
            </button>
          )}
          {setorAberto && (
            <ul style={{ marginTop: 8, paddingLeft: 18, fontSize: 12.5, color: "var(--acoes-tinta-2)" }}>
              {setoresPequenos.map((s) => (
                <li key={s.setor}>
                  {s.setor} ({s.contagem})
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="acoes-panel">
          <h3>Mudanças do mês</h3>
          <div className="acoes-mudancas-list">
            <div className="acoes-mudancas-item">
              <span className="acoes-num">↑ {dado.mudancas_do_mes.entraram}</span>
              <span>entraram no universo</span>
            </div>
            <div className="acoes-mudancas-item">
              <span className="acoes-num">↓ {dado.mudancas_do_mes.sairam}</span>
              <span>saíram do universo</span>
            </div>
            <div className="acoes-mudancas-item">
              <span className="acoes-num">⌗ {dado.mudancas_do_mes.balancos_novos}</span>
              <span>balanços novos publicados</span>
            </div>
            <div className="acoes-mudancas-item">
              <span className="acoes-num" style={{ color: dado.mudancas_do_mes.retificacoes > 0 ? "var(--acoes-atencao)" : undefined }}>
                ⚠ {dado.mudancas_do_mes.retificacoes}
              </span>
              <span>retificação(ões) detectada(s)</span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
