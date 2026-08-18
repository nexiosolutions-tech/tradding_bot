// Structural placeholder for multi-asset support (spec 08). The bot only trades one
// symbol today (state.symbol, currently BTCUSDT) — this component doesn't add any real
// asset-switching logic, it only reserves the visual slot exchanges put a pair list in,
// so wiring a second symbol later is a data change, not a redesign. The "coming soon"
// rows are inert on purpose: no onClick, no state, nothing to accidentally half-wire.

const COMING_SOON = ["ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"];

function baseAsset(symbol: string): string {
  return symbol.replace(/USDT$/, "");
}

export function CoinSelector({
  symbol,
  price,
  changePct,
}: {
  symbol: string;
  price?: number | null;
  changePct?: number | null;
}) {
  const deltaClass =
    changePct == null ? "muted" : `delta ${changePct >= 0 ? "delta--positive" : "delta--negative"}`;

  return (
    <div className="coin-selector">
      <div className="coin-selector__active">
        <div className="coin-selector__pair">
          <span className="coin-selector__base">{baseAsset(symbol)}</span>
          <span className="coin-selector__quote">/USDT</span>
        </div>
        <div className="coin-selector__price-block">
          <span className="coin-selector__price num">{price != null ? price.toFixed(2) : "—"}</span>
          <span className={`coin-selector__change num ${deltaClass}`}>
            {changePct == null ? "carregando…" : `${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%`}
          </span>
        </div>
      </div>

      <ul className="coin-selector__list">
        {COMING_SOON.map((coinSymbol) => (
          <li key={coinSymbol} className="coin-selector__item">
            <span className="coin-selector__item-label">{baseAsset(coinSymbol)}/USDT</span>
            <span className="tag">em breve</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
