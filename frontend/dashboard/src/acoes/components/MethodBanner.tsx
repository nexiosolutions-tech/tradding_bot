// Faixa de contexto do método (Seção 11.3) — fixa no topo da tela principal, nunca
// descartável, nunca modal. O texto é exigido pela Seção 9: o backtest voltou nulo
// (p=0,52), a ordenação não foi validada como preditiva.
export function MethodBanner() {
  return (
    <div className="acoes-method-banner" role="note">
      <span>
        A ordenação abaixo organiza dados públicos por critérios explícitos.{" "}
        <strong>Ela não foi validada como preditiva</strong> — no teste de 2015-2026 não se
        distinguiu do acaso. Use como ponto de partida de análise, não como recomendação.
      </span>
    </div>
  );
}
