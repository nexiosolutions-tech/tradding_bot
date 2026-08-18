import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { theme } from "../theme";
import type { Candle, Trade } from "../api/types";

const POSITIVE = theme.positive;
const NEGATIVE = theme.negative;

function toChartTime(tsMs: number): Time {
  return Math.floor(tsMs / 1000) as Time;
}

function buildTradeMarkers(trades: Trade[]): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = [];
  for (const trade of trades) {
    markers.push({
      time: toChartTime(trade.entry_ts),
      position: "belowBar",
      color: theme.accent,
      shape: "arrowUp",
      text: "entrada",
    });
    markers.push({
      time: toChartTime(trade.exit_ts),
      position: "aboveBar",
      color: trade.pnl >= 0 ? POSITIVE : NEGATIVE,
      shape: "arrowDown",
      text: `${trade.pnl >= 0 ? "+" : ""}${trade.pnl.toFixed(2)}`,
    });
  }
  return markers.sort((a, b) => (a.time as number) - (b.time as number));
}

export function PriceChart({ candles, trades }: { candles: Candle[]; trades: Trade[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      height: 420,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: theme.textMuted,
        fontFamily: "JetBrains Mono, monospace",
        attributionLogo: false,
      },
      grid: { horzLines: { color: theme.border }, vertLines: { visible: false } },
      timeScale: { timeVisible: true, borderColor: theme.border },
      rightPriceScale: { borderColor: theme.border },
      crosshair: { mode: 0 },
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: POSITIVE,
      downColor: NEGATIVE,
      borderVisible: false,
      wickUpColor: POSITIVE,
      wickDownColor: NEGATIVE,
    });

    const emaFast = chart.addSeries(LineSeries, {
      color: theme.accent,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      title: "EMA 12",
    });
    const emaSlow = chart.addSeries(LineSeries, {
      color: theme.textSecondary,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      title: "EMA 26",
    });
    const bollUpper = chart.addSeries(LineSeries, {
      color: "rgba(132, 142, 156, 0.5)",
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    const bollLower = chart.addSeries(LineSeries, {
      color: "rgba(132, 142, 156, 0.5)",
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });

    // Secondary pane (index 1) for RSI — its own price scale, stacked below the candles.
    const rsiSeries = chart.addSeries(
      LineSeries,
      {
        color: theme.accent,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: true,
        title: "RSI 14",
      },
      1
    );
    chart.panes()[1]?.setHeight(110);

    const candleData = candles.map((c) => ({
      time: toChartTime(c.ts),
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
    candleSeries.setData(candleData);
    markersRef.current = createSeriesMarkers(candleSeries, buildTradeMarkers(trades));

    const lineData = (key: "ema_fast" | "ema_slow" | "bollinger_upper" | "bollinger_lower" | "rsi") =>
      candles
        .filter((c) => c[key] !== null)
        .map((c) => ({ time: toChartTime(c.ts), value: c[key] as number }));

    emaFast.setData(lineData("ema_fast"));
    emaSlow.setData(lineData("ema_slow"));
    bollUpper.setData(lineData("bollinger_upper"));
    bollLower.setData(lineData("bollinger_lower"));
    rsiSeries.setData(lineData("rsi"));

    chart.timeScale().fitContent();

    const resize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    resize();
    window.addEventListener("resize", resize);

    return () => {
      window.removeEventListener("resize", resize);
      chart.remove();
      chartRef.current = null;
      markersRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles]);

  useEffect(() => {
    markersRef.current?.setMarkers(buildTradeMarkers(trades));
  }, [trades]);

  if (candles.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state__title">Sem histórico de candles ainda</div>
        <p className="muted">O gráfico aparece assim que o engine processar os primeiros candles fechados.</p>
      </div>
    );
  }

  return <div ref={containerRef} className="chart-container" />;
}
