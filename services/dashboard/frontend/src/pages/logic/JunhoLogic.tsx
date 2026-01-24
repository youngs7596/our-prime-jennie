// VisualLogic.tsx (Quantum Jump mock)
// Dependency: lightweight-charts
import React, { useEffect, useMemo, useRef } from "react";
import {
    createChart,
    IChartApi,
    ISeriesApi,
    CandlestickData,
    LineData,
    HistogramData,
    Time,
} from "lightweight-charts";

type SignalType = "GOLDEN_CROSS" | "BB_LOWER_TOUCH" | "RSI_FOREIGN_CONFLUENCE";

type Datum = {
    time: Time; // 'YYYY-MM-DD' string works
    open: number;
    high: number;
    low: number;
    close: number;

    ma5: number;
    ma20: number;
    ma120: number;

    bbUpper: number;
    bbMid: number;
    bbLower: number;

    rsi: number;

    volume: number;
    volAvg20: number;

    foreignNet: number; // + buy, - sell
    instNet: number;

    // optional signal markers
    signals?: SignalType[];
};

const THEME = {
    bgTop: "#0D0D0F",
    bgBottom: "#1A1A1F",
    text: "#E5E7EB",
    grid: "rgba(255,255,255,0.06)",

    // Korean market candle style (Up=Red, Down=Blue)
    up: "#EF4444",
    down: "#3B82F6",

    ma5: "#007AFF", // Neon Blue
    ma20: "#FF9500", // Neon Orange
    ma120: "#636366", // Muted Grey
    bb: "#5AC8FA", // Translucent Blue overlay
    rsi: "#A855F7", // Purple

    foreign: "#3B82F6",
    inst: "#F59E0B",

    markerGC: "#22C55E",
    markerBB: "#5AC8FA",
    markerRF: "#F59E0B",
};

function buildMockData(n = 70): Datum[] {
    // Simple deterministic mock (uptrend + some volatility)
    const out: Datum[] = [];
    let price = 100;
    for (let i = 0; i < n; i++) {
        const day = new Date(2026, 0, 1 + i);
        const time = day.toISOString().slice(0, 10) as Time;

        const drift = 0.35 + (i % 12 === 0 ? -0.8 : 0); // occasional pullback
        const noise = (Math.sin(i / 3) + Math.cos(i / 5)) * 0.6;

        const open = price;
        const close = Math.max(1, open + drift + noise);
        const high = Math.max(open, close) + 1.2 + (i % 7) * 0.1;
        const low = Math.min(open, close) - 1.0 - (i % 5) * 0.1;

        price = close;

        const ma5 = close - 1.0;
        const ma20 = close - 2.2;
        const ma120 = close - 6.0;

        const bbMid = ma20;
        const bbUpper = bbMid + 3.5;
        const bbLower = bbMid - 3.5;

        const rsi = Math.min(85, Math.max(18, 50 + Math.sin(i / 4) * 22 + (i % 15 === 0 ? -18 : 0)));

        const volume = 100 + (i % 9) * 25 + (i % 13 === 0 ? 220 : 0);
        const volAvg20 = 160;

        const foreignNet = (i % 10 < 6 ? 1 : -1) * (10 + (i % 7) * 4);
        const instNet = (i % 11 < 5 ? 1 : -1) * (8 + (i % 6) * 3);

        const signals: SignalType[] = [];
        if (i === 22) signals.push("GOLDEN_CROSS");
        if (i === 28) signals.push("BB_LOWER_TOUCH");
        if (i === 31) signals.push("RSI_FOREIGN_CONFLUENCE");

        out.push({
            time,
            open,
            high,
            low,
            close,
            ma5,
            ma20,
            ma120,
            bbUpper,
            bbMid,
            bbLower,
            rsi,
            volume,
            volAvg20,
            foreignNet,
            instNet,
            signals: signals.length ? signals : undefined,
        });
    }
    return out;
}

function useGradientBackgroundStyle(): React.CSSProperties {
    return {
        background: `linear-gradient(180deg, ${THEME.bgTop} 0%, ${THEME.bgBottom} 100%)`,
        borderRadius: 16,
        padding: 12,
        border: "1px solid rgba(255,255,255,0.08)",
        color: THEME.text,
    };
}

export default function JunhoLogic() {
    const wrapStyle = useGradientBackgroundStyle();

    const priceRef = useRef<HTMLDivElement | null>(null);
    const rsiRef = useRef<HTMLDivElement | null>(null);
    const flowRef = useRef<HTMLDivElement | null>(null);

    // Keep data stable to prevent infinite re-renders
    const data = useMemo(() => buildMockData(80), []);

    useEffect(() => {
        // Only initialize if refs are ready
        if (!priceRef.current || !rsiRef.current || !flowRef.current) return;

        // Check if charts are already initialized to avoid duplication 
        // (React StricMode might run effect twice, so clean up is important)
        // However, lightweight-charts doesn't attach to the DOM node in a way we can check easily without keeping chart instance ref.
        // For simplicity in this mock, we rely on the cleanup function.

        // ---------- Price Chart (Candles + MA + BB + Volume) ----------
        const priceChart = createChart(priceRef.current, {
            height: 360,
            layout: { background: { color: "transparent" }, textColor: THEME.text },
            grid: { vertLines: { color: THEME.grid }, horzLines: { color: THEME.grid } },
            rightPriceScale: { borderColor: "rgba(255,255,255,0.10)" },
            timeScale: { borderColor: "rgba(255,255,255,0.10)" },
            crosshair: { vertLine: { color: "rgba(255,255,255,0.2)" }, horzLine: { color: "rgba(255,255,255,0.2)" } },
        });

        const candleSeries = priceChart.addCandlestickSeries({
            upColor: THEME.up,
            downColor: THEME.down,
            borderUpColor: THEME.up,
            borderDownColor: THEME.down,
            wickUpColor: THEME.up,
            wickDownColor: THEME.down,
        });

        const ma5Series = priceChart.addLineSeries({ color: THEME.ma5, lineWidth: 2 });
        const ma20Series = priceChart.addLineSeries({ color: THEME.ma20, lineWidth: 2 });
        const ma120Series = priceChart.addLineSeries({ color: THEME.ma120, lineWidth: 1, lineStyle: 2 }); // dotted

        const bbUpperSeries = priceChart.addLineSeries({ color: "rgba(90,200,250,0.35)", lineWidth: 1 });
        const bbLowerSeries = priceChart.addLineSeries({ color: "rgba(90,200,250,0.35)", lineWidth: 1 });
        const bbMidSeries = priceChart.addLineSeries({ color: "rgba(90,200,250,0.18)", lineWidth: 1 });

        const volSeries = priceChart.addHistogramSeries({
            priceFormat: { type: "volume" },
            priceScaleId: "", // separate scale
            scaleMargins: { top: 0.80, bottom: 0 },
        });

        // Map data
        const candles: CandlestickData[] = data.map(d => ({
            time: d.time,
            open: d.open,
            high: d.high,
            low: d.low,
            close: d.close,
        }));

        const ma5: LineData[] = data.map(d => ({ time: d.time, value: d.ma5 }));
        const ma20: LineData[] = data.map(d => ({ time: d.time, value: d.ma20 }));
        const ma120: LineData[] = data.map(d => ({ time: d.time, value: d.ma120 }));

        const bbU: LineData[] = data.map(d => ({ time: d.time, value: d.bbUpper }));
        const bbM: LineData[] = data.map(d => ({ time: d.time, value: d.bbMid }));
        const bbL: LineData[] = data.map(d => ({ time: d.time, value: d.bbLower }));

        const vols: HistogramData[] = data.map(d => ({
            time: d.time,
            value: d.volume,
            color: d.close >= d.open ? "rgba(239,68,68,0.55)" : "rgba(59,130,246,0.55)",
        }));

        candleSeries.setData(candles);
        ma5Series.setData(ma5);
        ma20Series.setData(ma20);
        ma120Series.setData(ma120);
        bbUpperSeries.setData(bbU);
        bbMidSeries.setData(bbM);
        bbLowerSeries.setData(bbL);
        volSeries.setData(vols);

        // Signal Markers (▲ ● ◆)
        // lightweight-charts markers are attached to a series:
        const markers = data.flatMap(d => {
            if (!d.signals?.length) return [];
            return d.signals.map(sig => {
                if (sig === "GOLDEN_CROSS") {
                    return {
                        time: d.time,
                        position: "belowBar" as const,
                        color: THEME.markerGC,
                        shape: "arrowUp" as const,
                        text: "GC ▲",
                    };
                }
                if (sig === "BB_LOWER_TOUCH") {
                    return {
                        time: d.time,
                        position: "belowBar" as const,
                        color: THEME.markerBB,
                        shape: "circle" as const,
                        text: "BB ●",
                    };
                }
                return {
                    time: d.time,
                    position: "belowBar" as const,
                    color: THEME.markerRF,
                    shape: "diamond" as const,
                    text: "RSI+F ◆",
                };
            });
        });
        // @ts-ignore
        candleSeries.setMarkers(markers);

        priceChart.timeScale().fitContent();

        // ---------- RSI Chart ----------
        const rsiChart = createChart(rsiRef.current, {
            height: 140,
            layout: { background: { color: "transparent" }, textColor: THEME.text },
            grid: { vertLines: { color: THEME.grid }, horzLines: { color: THEME.grid } },
            rightPriceScale: { borderColor: "rgba(255,255,255,0.10)" },
            timeScale: { borderColor: "rgba(255,255,255,0.10)" },
            crosshair: { vertLine: { color: "rgba(255,255,255,0.2)" }, horzLine: { color: "rgba(255,255,255,0.2)" } },
        });

        const rsiSeries = rsiChart.addLineSeries({ color: THEME.rsi, lineWidth: 2 });
        rsiSeries.setData(data.map(d => ({ time: d.time, value: d.rsi })));

        // Oversold zone hint (<30): two reference lines (30/70)
        const line30 = rsiChart.addLineSeries({ color: "rgba(34,197,94,0.35)", lineWidth: 1, lineStyle: 2 });
        const line70 = rsiChart.addLineSeries({ color: "rgba(255,255,255,0.18)", lineWidth: 1, lineStyle: 2 });
        line30.setData(data.map(d => ({ time: d.time, value: 30 })));
        line70.setData(data.map(d => ({ time: d.time, value: 70 })));
        rsiChart.timeScale().fitContent();

        // ---------- Flow (Supply/Demand) Chart: Foreign/Institution net buy ----------
        const flowChart = createChart(flowRef.current, {
            height: 160,
            layout: { background: { color: "transparent" }, textColor: THEME.text },
            grid: { vertLines: { color: THEME.grid }, horzLines: { color: THEME.grid } },
            rightPriceScale: { borderColor: "rgba(255,255,255,0.10)" },
            timeScale: { borderColor: "rgba(255,255,255,0.10)" },
            crosshair: { vertLine: { color: "rgba(255,255,255,0.2)" }, horzLine: { color: "rgba(255,255,255,0.2)" } },
        });

        const foreignSeries = flowChart.addHistogramSeries({
            priceFormat: { type: "volume" },
            color: THEME.foreign,
            // base: 0, // Not explicitly supported in all versions, but default is 0
        });
        const instSeries = flowChart.addHistogramSeries({
            priceFormat: { type: "volume" },
            color: THEME.inst,
            // base: 0,
        });

        foreignSeries.setData(
            data.map(d => ({
                time: d.time,
                value: d.foreignNet,
                color: d.foreignNet >= 0 ? "rgba(59,130,246,0.75)" : "rgba(59,130,246,0.25)",
            }))
        );
        instSeries.setData(
            data.map(d => ({
                time: d.time,
                value: d.instNet,
                color: d.instNet >= 0 ? "rgba(245,158,11,0.75)" : "rgba(245,158,11,0.25)",
            }))
        );

        flowChart.timeScale().fitContent();

        // Sync time scales (optional but good for UX)
        const syncCharts = (source: IChartApi) => {
            // Simplistic sync logic can be added here if needed
            // lightweight-charts version 4+ has specific sync methods or you use logical range
        };

        // Cleanup
        const charts: IChartApi[] = [priceChart, rsiChart, flowChart];

        // Resize observer to handle window resize
        const handleResize = () => {
            if (priceRef.current) priceChart.applyOptions({ width: priceRef.current.clientWidth });
            if (rsiRef.current) rsiChart.applyOptions({ width: rsiRef.current.clientWidth });
            if (flowRef.current) flowChart.applyOptions({ width: flowRef.current.clientWidth });
        };
        window.addEventListener('resize', handleResize);

        return () => {
            charts.forEach(c => c.remove());
            window.removeEventListener('resize', handleResize);
        };
    }, [data]);

    return (
        <div style={wrapStyle} className="h-full">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
                <div style={{ fontSize: 16, fontWeight: 700 }}>Junho's Quantum Logic — Visual Logic</div>
                <div style={{ fontSize: 12, opacity: 0.8 }}>
                    Layers: Candles · MA5/20/120 · Bollinger · Signals · RSI · Foreign/Institution · Volume
                </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                <section className="bg-black/20 p-4 rounded-lg">
                    <div style={{ fontSize: 12, opacity: 0.9, marginBottom: 6 }} className="flex items-center gap-2">
                        <span className="font-bold text-white">Price Action</span>
                        <span className="text-gray-400">Signals: GC ▲ / BB ● / RSI+Foreign ◆</span>
                    </div>
                    <div ref={priceRef} className="w-full" />
                </section>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <section className="bg-black/20 p-4 rounded-lg">
                        <div style={{ fontSize: 12, opacity: 0.9, marginBottom: 6 }}>
                            <span className="font-bold text-profit-positive">RSI (Purple)</span> — Oversold Zone & reference lines (30/70)
                        </div>
                        <div ref={rsiRef} className="w-full" />
                    </section>

                    <section className="bg-black/20 p-4 rounded-lg">
                        <div style={{ fontSize: 12, opacity: 0.9, marginBottom: 6 }}>
                            <span className="font-bold text-profit-positive">Supply/Demand</span> — Foreign (Blue) / Institution (Orange) Net Buy
                        </div>
                        <div ref={flowRef} className="w-full" />
                    </section>
                </div>
            </div>
        </div>
    );
}
