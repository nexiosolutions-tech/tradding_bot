import { useEffect, useRef } from "react";
import { AreaSeries, ColorType, createChart } from "lightweight-charts";

export function MiniEquityChart({ points }: { points: [number, number][] }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current || points.length < 2) return;

    const chart = createChart(containerRef.current, {
      height: 96,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "transparent", attributionLogo: false },
      grid: { horzLines: { visible: false }, vertLines: { visible: false } },
      timeScale: { visible: false },
      rightPriceScale: { visible: false },
      crosshair: { horzLine: { visible: false }, vertLine: { visible: false } },
      handleScroll: false,
      handleScale: false,
    });

    const series = chart.addSeries(AreaSeries, {
      lineColor: "#d99a3d",
      topColor: "rgba(217, 154, 61, 0.22)",
      bottomColor: "rgba(217, 154, 61, 0.01)",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    let lastTime = 0;
    const data = points.map(([ts, value]) => {
      let time = Math.floor(ts / 1000);
      if (time <= lastTime) time = lastTime + 1;
      lastTime = time;
      return { time: time as never, value };
    });
    series.setData(data);
    chart.timeScale().fitContent();

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

  if (points.length < 2) {
    return <div className="muted" style={{ fontSize: 12.5, paddingTop: 36 }}>Acumulando histórico de capital da sessão…</div>;
  }

  return <div ref={containerRef} className="chart-container" style={{ height: 96 }} />;
}
