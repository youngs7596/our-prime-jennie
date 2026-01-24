import React, { useEffect, useRef, useState, useCallback } from "react";
import {
    createChart,
    ISeriesApi,
    Time,
} from "lightweight-charts";
import { useWebSocket, BuySignal } from "../../lib/useWebSocket";

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

// ... (buildMockData function remains same for initial data) ...
function buildMockData(n = 70): Datum[] {
    // Simple deterministic mock (uptrend + some volatility)
    const out: Datum[] = [];
    let price = 100;
    for (let i = 0; i < n; i++) {
        // Use a date relative to now to make it look recent
        const day = new Date();
        day.setDate(day.getDate() - (n - i));

        // Simple YYYY-MM-DD format
        const time = day.toISOString().split('T')[0] as Time;

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

    // References to series to update them directly
    const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const ma5SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const ma20SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const ma120SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const bbUpperSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const bbMidSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const bbLowerSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
    const rsiSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const foreignSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
    const instSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);

    // Initial Data State
    const [chartData, setChartData] = useState<Datum[]>(() => buildMockData(70));
    const [lastSignal, setLastSignal] = useState<BuySignal | null>(null);

    // Real-time WebSocket Integration
    const { isConnected } = useWebSocket({
        onMessage: (msg) => {
            if (msg.type === 'buy_signal') {
                handleNewSignal(msg.data);
            }
        }
    });

    // Helper to update chart data from real-time signal
    const handleNewSignal = useCallback((signal: BuySignal) => {
        setLastSignal(signal);
        setChartData(prev => {
            const lastBar = prev[prev.length - 1];
            // If same day, update last bar. If new day, add new bar.
            // For this demo, let's assume we append or update the last simulated bar
            // To make it interesting, we'll shift time or just append

            // Extract price from signal
            const nextPrice = signal.price;

            // Just for visualization: mimic a new bar or update last
            // Let's simple append a new bar based on previous close
            const newBar = { ...lastBar };

            // Simple logic: verify if time is different
            // In a real app, 'time' handling is critical.
            // Here we just bump the day for demo if it's "next day" or same day update

            // For visualization effect: Create a new candle
            const nextDate = new Date(lastBar.time as string);
            nextDate.setDate(nextDate.getDate() + 1);
            const nextTime = nextDate.toISOString().split('T')[0] as Time;

            newBar.time = nextTime;
            newBar.open = lastBar.close;
            newBar.close = nextPrice;
            newBar.high = Math.max(newBar.open, newBar.close) + Math.random();
            newBar.low = Math.min(newBar.open, newBar.close) - Math.random();
            newBar.signals = undefined;

            // Signal Marker Logic
            if (signal.signal_type === 'GOLDEN_CROSS') {
                newBar.signals = ["GOLDEN_CROSS"];
            } else if (signal.signal_type.includes('BB')) {
                newBar.signals = ["BB_LOWER_TOUCH"];
            }

            // Recalculate indicators (Mocking update)
            newBar.ma5 = (lastBar.ma5 * 4 + nextPrice) / 5;
            newBar.ma20 = (lastBar.ma20 * 19 + nextPrice) / 20;
            // ... simplify others

            return [...prev, newBar];
        });
    }, []);

    // Update charts when data changes
    useEffect(() => {
        if (!candleSeriesRef.current) return;

        // Map data to series format
        const candles = chartData.map(d => ({ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close }));
        const ma5 = chartData.map(d => ({ time: d.time, value: d.ma5 }));
        const ma20 = chartData.map(d => ({ time: d.time, value: d.ma20 }));
        const ma120 = chartData.map(d => ({ time: d.time, value: d.ma120 }));
        const bbU = chartData.map(d => ({ time: d.time, value: d.bbUpper }));
        const bbM = chartData.map(d => ({ time: d.time, value: d.bbMid }));
        const bbL = chartData.map(d => ({ time: d.time, value: d.bbLower }));
        const vols = chartData.map(d => ({ time: d.time, value: d.volume, color: d.close >= d.open ? "rgba(239,68,68,0.55)" : "rgba(59,130,246,0.55)" }));
        const rsi = chartData.map(d => ({ time: d.time, value: d.rsi }));
        const foreign = chartData.map(d => ({ time: d.time, value: d.foreignNet, color: d.foreignNet >= 0 ? "rgba(59,130,246,0.75)" : "rgba(59,130,246,0.25)" }));
        const inst = chartData.map(d => ({ time: d.time, value: d.instNet, color: d.instNet >= 0 ? "rgba(245,158,11,0.75)" : "rgba(245,158,11,0.25)" }));

        candleSeriesRef.current.setData(candles);
        ma5SeriesRef.current?.setData(ma5);
        ma20SeriesRef.current?.setData(ma20);
        ma120SeriesRef.current?.setData(ma120);
        bbUpperSeriesRef.current?.setData(bbU);
        bbMidSeriesRef.current?.setData(bbM);
        bbLowerSeriesRef.current?.setData(bbL);
        volSeriesRef.current?.setData(vols);
        rsiSeriesRef.current?.setData(rsi);
        foreignSeriesRef.current?.setData(foreign);
        instSeriesRef.current?.setData(inst);

        // Markers
        const markers = chartData.flatMap(d => {
            if (!d.signals?.length) return [];
            return d.signals.map(sig => {
                if (sig === "GOLDEN_CROSS") {
                    return { time: d.time, position: "belowBar", color: THEME.markerGC, shape: "arrowUp", text: "GC ▲" };
                }
                if (sig === "BB_LOWER_TOUCH") {
                    return { time: d.time, position: "belowBar", color: THEME.markerBB, shape: "circle", text: "BB ●" };
                }
                return { time: d.time, position: "belowBar", color: THEME.markerRF, shape: "diamond", text: "RSI+F ◆" };
            });
        });
        // @ts-ignore
        candleSeriesRef.current.setMarkers(markers);

    }, [chartData]); // Re-render charts when data updates

    useEffect(() => {
        // Initialize Charts only once
        if (!priceRef.current || !rsiRef.current || !flowRef.current) return;
        if (candleSeriesRef.current) return; // Already initialized

        // ---------- Price Chart (Candles + MA + BB + Volume) ----------
        const priceChart = createChart(priceRef.current, {
            height: 360,
            layout: { background: { color: "transparent" }, textColor: THEME.text },
            grid: { vertLines: { color: THEME.grid }, horzLines: { color: THEME.grid } },
            rightPriceScale: { borderColor: "rgba(255,255,255,0.10)" },
            timeScale: { borderColor: "rgba(255,255,255,0.10)" },
            crosshair: { vertLine: { color: "rgba(255,255,255,0.2)" }, horzLine: { color: "rgba(255,255,255,0.2)" } },
        });

        candleSeriesRef.current = priceChart.addCandlestickSeries({
            upColor: THEME.up,
            downColor: THEME.down,
            borderUpColor: THEME.up,
            borderDownColor: THEME.down,
            wickUpColor: THEME.up,
            wickDownColor: THEME.down,
        });

        ma5SeriesRef.current = priceChart.addLineSeries({ color: THEME.ma5, lineWidth: 2 });
        ma20SeriesRef.current = priceChart.addLineSeries({ color: THEME.ma20, lineWidth: 2 });
        ma120SeriesRef.current = priceChart.addLineSeries({ color: THEME.ma120, lineWidth: 1, lineStyle: 2 }); // dotted

        bbUpperSeriesRef.current = priceChart.addLineSeries({ color: "rgba(90,200,250,0.35)", lineWidth: 1 });
        bbLowerSeriesRef.current = priceChart.addLineSeries({ color: "rgba(90,200,250,0.35)", lineWidth: 1 });
        bbMidSeriesRef.current = priceChart.addLineSeries({ color: "rgba(90,200,250,0.18)", lineWidth: 1 });

        volSeriesRef.current = priceChart.addHistogramSeries({
            priceFormat: { type: "volume" },
            priceScaleId: "", // separate scale
            // scaleMargins: { top: 0.80, bottom: 0 },
        });

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

        rsiSeriesRef.current = rsiChart.addLineSeries({ color: THEME.rsi, lineWidth: 2 });

        // Oversold zone hint (<30): two reference lines (30/70)
        // const line30 = rsiChart.addLineSeries({ color: "rgba(34,197,94,0.35)", lineWidth: 1, lineStyle: 2 });
        // const line70 = rsiChart.addLineSeries({ color: "rgba(255,255,255,0.18)", lineWidth: 1, lineStyle: 2 });
        // Set fake data for reference lines just to draw them
        // In real app, create Primitive or just set constant relative to visible logic, but this works

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

        foreignSeriesRef.current = flowChart.addHistogramSeries({
            priceFormat: { type: "volume" },
            color: THEME.foreign,
        });
        instSeriesRef.current = flowChart.addHistogramSeries({
            priceFormat: { type: "volume" },
            color: THEME.inst,
        });

        flowChart.timeScale().fitContent();

        // Resize observer
        const handleResize = () => {
            if (priceRef.current) priceChart.applyOptions({ width: priceRef.current.clientWidth });
            if (rsiRef.current) rsiChart.applyOptions({ width: rsiRef.current.clientWidth });
            if (flowRef.current) flowChart.applyOptions({ width: flowRef.current.clientWidth });
        };
        window.addEventListener('resize', handleResize);

        return () => {
            priceChart.remove();
            rsiChart.remove();
            flowChart.remove();
            window.removeEventListener('resize', handleResize);
        };
    }, []);

    return (
        <div style={wrapStyle} className="h-full">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
                <div style={{ fontSize: 16, fontWeight: 700 }}>
                    Junho's Quantum Logic — Visual Logic
                    {isConnected && <span className="ml-2 inline-block w-2 h-2 rounded-full bg-green-500 animate-pulse" title="Live Connected" />}
                    {!isConnected && <span className="ml-2 inline-block w-2 h-2 rounded-full bg-red-500" title="Disconnected" />}
                </div>
                <div style={{ fontSize: 12, opacity: 0.8 }} className="flex gap-4">
                    <span>layers: Candles · MA5/20/120 · Bollinger · Signals · RSI · Supply/Demand</span>
                    {lastSignal && (
                        <span className="text-jennie-gold animate-bounce">
                            Latest Signal: {lastSignal.stock_name} ({lastSignal.price}원) - {lastSignal.signal_type}
                        </span>
                    )}
                </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                <section className="bg-black/20 p-4 rounded-lg relative">
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
