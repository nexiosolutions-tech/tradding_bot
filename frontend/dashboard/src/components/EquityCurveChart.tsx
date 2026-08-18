import { useEffect, useRef } from "react";
import { AreaSeries, ColorType, createChart, type IChartApi } from "lightweight-charts";
import { theme } from "../theme";

export function EquityCurveChart({ points }: { points: [number, number][] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      height: 280,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: theme.textMuted,
        fontFamily: "JetBrains Mono, monospace",
        attributionLogo: false,
      },
      grid: { horzLines: { color: theme.border }, vertLines: { visible: false } },
      timeScale: { timeVisible: true, borderColor: theme.border },
      rightPriceScale: { borderColor: theme.border },
    });
    const series = chart.addSeries(AreaSeries, {
      lineColor: theme.accent,
      topColor: "rgba(240, 185, 11, 0.20)",
      bottomColor: "rgba(240, 185, 11, 0.01)",
      lineWidth: 2,
    });

    series.setData(
      points.map(([ts, equity]) => ({ time: Math.floor(ts / 1000) as never, value: equity }))
    );
    chart.timeScale().fitContent();
    chartRef.current = chart;

    const resize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    resize();
    window.addEventListener("resize", resize);

    return () => {
      window.removeEventListener("resize", resize);
      chart.remove();
    };
  }, [points]);

  return <div ref={containerRef} className="chart-container" />;
}
