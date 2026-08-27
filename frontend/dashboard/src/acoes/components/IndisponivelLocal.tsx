// Estado vazio honesto para o módulo inteiro (Seção 11.3/11.12) — banco de Ações vazio
// ou não encontrado (produção sem volume/Postgres) é ambiente, não bug de dado. Mostra
// isso explicitamente em vez de "não foi possível carregar este mês", que levaria
// quem visse a tela a caçar bug de dado por engano.
export function IndisponivelLocal() {
  return (
    <div className="acoes-panel">
      <div className="acoes-empty-state">
        <strong>Módulo de Ações disponível apenas localmente.</strong>
        <br />
        Este ambiente não tem o banco de dados do módulo configurado — é esperado em
        produção sem volume persistente ou Postgres (decisão registrada, spec 14,
        Seção 11.12). Rode o backend e o dashboard na sua máquina para usar esta tela.
      </div>
    </div>
  );
}
