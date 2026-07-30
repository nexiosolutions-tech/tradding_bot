import { useEffect, useRef } from "react";
import { AreaSeries, ColorType, createChart, type IChartApi } from "lightweight-charts";

export function EquityCurveChart({ points }: { points: [number, number][] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      height: 280,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#a8b3c5",
        attributionLogo: false,
      },
      grid: { horzLines: { color: "#1f2733" }, vertLines: { visible: false } },
      timeScale: { timeVisible: true, borderColor: "#1f2733" },
      rightPriceScale: { borderColor: "#1f2733" },
    });
    const series = chart.addSeries(AreaSeries, {
      lineColor: "#4ade80",
      topColor: "rgba(74, 222, 128, 0.25)",
      bottomColor: "rgba(74, 222, 128, 0.02)",
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
