import { useEffect, useMemo, useState } from "react";
import { acoesApi, AcoesIndisponivelError } from "../api/client";
import type { EmpresaRanking } from "../api/types";
import { IndisponivelLocal } from "../components/IndisponivelLocal";
import { useCarteira } from "../hooks/useCarteira";
import { formatPct } from "../format";

interface ExposicaoSetor {
  setor: string;
  pctCarteira: number;
  pctUniverso: number;
}

function calcularExposicao(
  pesos: { setor: string; peso: number }[],
  universo: EmpresaRanking[]
): ExposicaoSetor[] {
  const porSetorCarteira: Record<string, number> = {};
  for (const p of pesos) porSetorCarteira[p.setor] = (porSetorCarteira[p.setor] ?? 0) + p.peso;

  const porSetorUniverso: Record<string, number> = {};
  for (const e of universo) {
    const setor = e.setor_b3 ?? "Sem classificação B3";
    porSetorUniverso[setor] = (porSetorUniverso[setor] ?? 0) + 1;
  }
  const totalUniverso = universo.length || 1;

  const setores = new Set([...Object.keys(porSetorCarteira), ...Object.keys(porSetorUniverso)]);
  return [...setores]
    .map((setor) => ({
      setor,
      pctCarteira: porSetorCarteira[setor] ?? 0,
      pctUniverso: (porSetorUniverso[setor] ?? 0) / totalUniverso,
    }))
    .sort((a, b) => b.pctCarteira - a.pctCarteira);
}

function calcularConcentracao(pesos: number[]) {
  const ordenados = [...pesos].sort((a, b) => b - a);
  const maior = ordenados[0] ?? 0;
  const cincoMaiores = ordenados.slice(0, 5).reduce((s, p) => s + p, 0);
  const herfindahl = pesos.reduce((s, p) => s + p * p, 0);
  const numeroEfetivo = herfindahl > 0 ? 1 / herfindahl : 0;
  return { maior, cincoMaiores, numeroEfetivo };
}

export function CarteiraView() {
  const { posicoes, adicionar, remover } = useCarteira();
  const [precos, setPrecos] = useState<Record<string, number | null>>({});
  const [universo, setUniverso] = useState<EmpresaRanking[] | null>(null);
  const [novo, setNovo] = useState({ ticker: "", quantidade: "", precoMedio: "" });

  const [valorAporte, setValorAporte] = useState("");
  const [candidatosSelecionados, setCandidatosSelecionados] = useState<string[]>([]);
  const [indisponivel, setIndisponivel] = useState(false);

  useEffect(() => {
    acoesApi
      .mesAtual()
      .then((d) => setUniverso(d.ranking))
      .catch((err) => {
        if (err instanceof AcoesIndisponivelError) setIndisponivel(true);
        setUniverso([]);
      });
  }, []);

  useEffect(() => {
    if (posicoes.length === 0) {
      setPrecos({});
      return;
    }
    acoesApi.precos(posicoes.map((p) => p.ticker)).then(setPrecos).catch(() => setPrecos({}));
  }, [posicoes]);

  const setorPorTicker = useMemo(() => {
    const mapa: Record<string, string> = {};
    (universo ?? []).forEach((e) => (mapa[e.ticker] = e.setor_b3 ?? "Sem classificação B3"));
    return mapa;
  }, [universo]);

  const linhas = posicoes.map((p) => {
    const precoAtual = precos[p.ticker] ?? null;
    const valorAtual = precoAtual !== null ? precoAtual * p.quantidade : null;
    return { ...p, precoAtual, valorAtual, setor: setorPorTicker[p.ticker] ?? "Sem classificação B3" };
  });

  const valorTotal = linhas.reduce((s, l) => s + (l.valorAtual ?? l.quantidade * l.precoMedio), 0);
  const pesos = linhas.map((l) => ({
    ticker: l.ticker,
    setor: l.setor,
    peso: valorTotal > 0 ? (l.valorAtual ?? l.quantidade * l.precoMedio) / valorTotal : 0,
  }));

  const exposicao = universo ? calcularExposicao(pesos, universo) : [];
  const concentracao = calcularConcentracao(pesos.map((p) => p.peso));

  function handleAdicionar() {
    const quantidade = Number(novo.quantidade);
    const precoMedio = Number(novo.precoMedio);
    if (!novo.ticker || !quantidade || !precoMedio) return;
    adicionar({ ticker: novo.ticker.toUpperCase(), quantidade, precoMedio });
    setNovo({ ticker: "", quantidade: "", precoMedio: "" });
  }

  // simulação de aporte: pesos "depois" assumindo aporte dividido igualmente entre os
  // candidatos marcados, somado à carteira atual — nunca sugere quanto comprar de cada
  // um (isso seria a Seção 8, ainda não validada), só mostra a consequência da escolha
  // que o próprio usuário fez.
  const aporte = Number(valorAporte) || 0;
  const pesosDepois = useMemo(() => {
    if (aporte <= 0 || candidatosSelecionados.length === 0) return null;
    const porCandidato = aporte / candidatosSelecionados.length;
    const valorTotalDepois = valorTotal + aporte;
    const mapa: Record<string, { setor: string; valor: number }> = {};
    for (const l of linhas) {
      mapa[l.ticker] = { setor: l.setor, valor: l.valorAtual ?? l.quantidade * l.precoMedio };
    }
    for (const ticker of candidatosSelecionados) {
      const setor = setorPorTicker[ticker] ?? "Sem classificação B3";
      mapa[ticker] = { setor, valor: (mapa[ticker]?.valor ?? 0) + porCandidato };
    }
    const pesosLista = Object.entries(mapa).map(([ticker, v]) => ({
      ticker,
      setor: v.setor,
      peso: valorTotalDepois > 0 ? v.valor / valorTotalDepois : 0,
    }));
    return {
      exposicao: universo ? calcularExposicao(pesosLista, universo) : [],
      concentracao: calcularConcentracao(pesosLista.map((p) => p.peso)),
    };
  }, [aporte, candidatosSelecionados, linhas, setorPorTicker, universo, valorTotal]);

  if (indisponivel) {
    return (
      <>
        <div className="acoes-page-header">
          <h1>Minha carteira</h1>
        </div>
        <IndisponivelLocal />
      </>
    );
  }

  return (
    <>
      <div className="acoes-page-header">
        <h1>Minha carteira</h1>
      </div>

      <div className="acoes-panel">
        <h3>Composição</h3>
        <table className="acoes-table" style={{ marginBottom: 14 }}>
          <thead>
            <tr>
              <th>Ticker</th>
              <th className="acoes-num">Quantidade</th>
              <th className="acoes-num">Preço médio</th>
              <th className="acoes-num">Valor atual</th>
              <th className="acoes-num">Peso</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {linhas.map((l, i) => (
              <tr key={l.ticker}>
                <td className="acoes-num">{l.ticker}</td>
                <td className="acoes-num">{l.quantidade}</td>
                <td className="acoes-num">{l.precoMedio.toFixed(2).replace(".", ",")}</td>
                <td className="acoes-num">{l.valorAtual !== null ? l.valorAtual.toFixed(2).replace(".", ",") : "s/d"}</td>
                <td className="acoes-num">{formatPct(pesos[i]?.peso ?? 0, 1)}</td>
                <td>
                  <button className="acoes-btn--texto" onClick={() => remover(l.ticker)}>
                    remover
                  </button>
                </td>
              </tr>
            ))}
            {linhas.length === 0 && (
              <tr>
                <td colSpan={6} className="acoes-empty-state">
                  Nenhuma posição cadastrada ainda.
                </td>
              </tr>
            )}
          </tbody>
        </table>

        <div className="acoes-form-row">
          <input
            placeholder="Ticker (ex. PETR4)"
            value={novo.ticker}
            onChange={(e) => setNovo((n) => ({ ...n, ticker: e.target.value }))}
          />
          <input
            type="number"
            placeholder="Quantidade"
            value={novo.quantidade}
            onChange={(e) => setNovo((n) => ({ ...n, quantidade: e.target.value }))}
          />
          <input
            type="number"
            placeholder="Preço médio"
            value={novo.precoMedio}
            onChange={(e) => setNovo((n) => ({ ...n, precoMedio: e.target.value }))}
          />
          <button className="acoes-btn" onClick={handleAdicionar}>
            Adicionar posição
          </button>
        </div>
      </div>

      <div className="acoes-panel">
        <h3>Concentração</h3>
        <div className="acoes-kpi-row">
          <div className="acoes-stat">
            <div className="acoes-stat__label">Maior posição</div>
            <div className="acoes-stat__value">{formatPct(concentracao.maior, 1)}</div>
          </div>
          <div className="acoes-stat">
            <div className="acoes-stat__label">5 maiores posições</div>
            <div className="acoes-stat__value">{formatPct(concentracao.cincoMaiores, 1)}</div>
          </div>
          <div className="acoes-stat">
            <div className="acoes-stat__label">Número efetivo de posições</div>
            <div className="acoes-stat__value">{concentracao.numeroEfetivo.toFixed(1).replace(".", ",")}</div>
          </div>
        </div>
      </div>

      <div className="acoes-panel">
        <h3>Exposição setorial — carteira vs. universo elegível</h3>
        <p style={{ fontSize: 12, color: "var(--acoes-tinta-2)", marginBottom: 10 }}>
          Comparado contra o universo elegível, não contra o Ibovespa — o índice ainda
          não tem fonte verificada (Seção 9.4).
        </p>
        {exposicao.map((e) => (
          <div className="acoes-hbar-row" key={e.setor}>
            <span>{e.setor}</span>
            <div className="acoes-hbar-track">
              <div className="acoes-hbar-fill" style={{ width: `${Math.min(100, e.pctCarteira * 100)}%` }} />
            </div>
            <span className="acoes-num">
              {formatPct(e.pctCarteira, 0)} <span style={{ color: "var(--acoes-tinta-2)" }}>vs {formatPct(e.pctUniverso, 0)}</span>
            </span>
          </div>
        ))}
      </div>

      <div className="acoes-panel">
        <h3>Simulação de aporte</h3>
        <p style={{ fontSize: 12.5, marginBottom: 10 }}>
          Informe um valor e marque candidatos — a tela mostra o antes e o depois da
          exposição e da concentração. Ela não sugere o que comprar.
        </p>
        <div className="acoes-form-row" style={{ marginBottom: 12 }}>
          <input
            type="number"
            placeholder="Valor do aporte"
            value={valorAporte}
            onChange={(e) => setValorAporte(e.target.value)}
          />
        </div>
        <div style={{ maxHeight: 220, overflowY: "auto", marginBottom: 14 }}>
          {(universo ?? []).map((e) => (
            <label className="acoes-checkbox-row" key={e.ticker}>
              <input
                type="checkbox"
                checked={candidatosSelecionados.includes(e.ticker)}
                onChange={(ev) =>
                  setCandidatosSelecionados((atual) =>
                    ev.target.checked ? [...atual, e.ticker] : atual.filter((t) => t !== e.ticker)
                  )
                }
              />
              {e.ticker} — {e.setor_b3 ?? "Sem classificação B3"}
            </label>
          ))}
        </div>

        {pesosDepois && (
          <div className="acoes-grid-2">
            <div>
              <h3 style={{ fontSize: 13 }}>Concentração — depois</h3>
              <div className="acoes-kpi-row">
                <div className="acoes-stat">
                  <div className="acoes-stat__label">Maior posição</div>
                  <div className="acoes-stat__value">{formatPct(pesosDepois.concentracao.maior, 1)}</div>
                </div>
                <div className="acoes-stat">
                  <div className="acoes-stat__label">5 maiores</div>
                  <div className="acoes-stat__value">{formatPct(pesosDepois.concentracao.cincoMaiores, 1)}</div>
                </div>
              </div>
            </div>
            <div>
              <h3 style={{ fontSize: 13 }}>Exposição setorial — depois</h3>
              {pesosDepois.exposicao.slice(0, 5).map((e) => (
                <div className="acoes-hbar-row" key={e.setor}>
                  <span>{e.setor}</span>
                  <div className="acoes-hbar-track">
                    <div className="acoes-hbar-fill" style={{ width: `${Math.min(100, e.pctCarteira * 100)}%` }} />
                  </div>
                  <span className="acoes-num">{formatPct(e.pctCarteira, 0)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
