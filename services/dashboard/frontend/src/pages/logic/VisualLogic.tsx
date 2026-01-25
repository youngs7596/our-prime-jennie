import { useEffect, useRef, useState, useMemo } from 'react';
import {
    createChart,
    ISeriesApi,
    Time,
    ColorType,
    LineStyle,
} from 'lightweight-charts';
import { motion, AnimatePresence } from 'framer-motion';

// --- Types ---
type MarketRegime = 'SIDEWAYS' | 'BULL' | 'BEAR';

type TradeEvent = {
    step: number;
    type: 'BUY' | 'SELL' | 'INFO' | 'WARNING';
    title: string;
    desc: string;
};

type ScenarioData = {
    regime: MarketRegime;
    title: string;
    description: string;
    data: MockDatum[];
    events: TradeEvent[];
    stats: {
        totalReturn: string;
        riskReward: string;
        duration: string;
        winRate: string;
    };
};

type MockDatum = {
    time: Time;
    open: number;
    high: number;
    low: number;
    close: number;
    ma5: number;
    ma20: number;
    volume: number;
    rsi: number;

    // Logic Factors
    vwap: number;
    bbUpper: number;
    bbLower: number;

    // Markers
    marker?: {
        text: string;
        color: string;
        position: 'aboveBar' | 'belowBar' | 'inBar';
        shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square';
    };
};

// --- Mock Data Generators ---

const createDate = (daysAgo: number) => {
    const d = new Date();
    d.setDate(d.getDate() - daysAgo);
    return d.toISOString().split('T')[0] as Time;
};

// Scenario A: Sideways Market (Defensive)
function generateSidewaysScenario(): ScenarioData {
    const data: MockDatum[] = [];
    const events: TradeEvent[] = [];

    // 50 days of data
    for (let i = 0; i < 60; i++) {
        const time = createDate(60 - i);
        // Box pattern: oscillating between 9500 and 10500
        const signal = Math.sin(i / 5) * 500;
        const noise = (Math.random() - 0.5) * 100;

        let close = 10000 + signal + noise;
        let open = 10000 + (Math.sin((i - 1) / 5) * 500) + noise;
        let high = Math.max(open, close) + Math.random() * 150;
        let low = Math.min(open, close) - Math.random() * 150;
        let volume = 10000 + Math.random() * 5000;

        // MA Logic
        const ma5 = close + (Math.random() - 0.5) * 50;
        const ma20 = 10000 + (Math.sin(i / 10) * 200);

        // RSI Logic (Oscillating)
        const rsi = 50 + Math.sin(i / 4) * 30;

        // BB Logic
        const bbUpper = ma20 + 800;
        const bbLower = ma20 - 800;
        const vwap = close * 0.99; // roughly close

        const datum: MockDatum = {
            time, open, high, low, close, ma5, ma20, volume, rsi, vwap, bbUpper, bbLower
        };

        // --- Simulated Logic Triggers ---

        // T=15: RSI Rebound Buy
        if (i === 15) {
            datum.open = 9400; datum.close = 9600; datum.low = 9300; datum.high = 9650; // Forced dip & recover
            datum.rsi = 32; // Dropped to 30 then up
            datum.marker = { text: "매수: RSI 반등", color: "#2ECC71", position: "belowBar", shape: "arrowUp" };
            events.push({ step: i, type: "BUY", title: "진입 실행", desc: "RSI 반등(32) + 지지선 확인 진입" });
        }

        // T=18: Check Risk (Pass)
        if (i === 18) {
            events.push({ step: i, type: "INFO", title: "안전 장치", desc: "리스크 점검 통과. 변동성 정상 범위." });
        }

        // T=25: Scale Out L1 (+3%)
        if (i === 25) {
            datum.close = 9900; datum.high = 9950;
            datum.marker = { text: "매도: 1차 익절", color: "#F1C40F", position: "aboveBar", shape: "arrowDown" };
            events.push({ step: i, type: "SELL", title: "1차 분할 매도 (+3%)", desc: "박스권 내 초기 수익 확보." });
        }

        // T=35: Profit Lock Triggered (Price drops back)
        if (i === 35) {
            datum.close = 9650;
            datum.marker = { text: "매도: 수익 보존", color: "#E74C3C", position: "aboveBar", shape: "arrowDown" };
            events.push({ step: i, type: "SELL", title: "Profit Lock 발동", desc: "가격 하락 반전. 손실 방지를 위해 본전 청산." });
        }

        data.push(datum);
    }

    return {
        regime: 'SIDEWAYS',
        title: "디펜시브 스나이퍼 (박스권)",
        description: "횡보/변동성 장세에 최적화. RSI 반등 및 밴드 하단 터치를 노리며, 짧은 호흡으로 수익을 방어합니다.",
        data,
        events,
        stats: { totalReturn: "+2.4%", riskReward: "1 : 2.5", duration: "20일", winRate: "높음 (65%)" }
    };
}

// Scenario B: Bull Market (Aggressive)
function generateBullScenario(): ScenarioData {
    const data: MockDatum[] = [];
    const events: TradeEvent[] = [];

    // 60 days of data
    for (let i = 0; i < 60; i++) {
        const time = createDate(60 - i);

        // Trend pattern: Exponential growth then minor correction
        // Base growth
        let trend = 0;
        if (i > 10) trend = Math.pow(i - 10, 2) * 2; // Parabolic

        const noise = (Math.random() - 0.5) * 150;

        let close = 10000 + trend + noise;
        let open = close - (Math.random() * 100);
        if (i > 10 && i % 3 === 0) open = close - 50; // steady candles

        let high = Math.max(open, close) + Math.random() * 200;
        let low = Math.min(open, close) - Math.random() * 100;

        // Volume spike logic
        let volume = 15000 + Math.random() * 10000;
        if (i === 12) volume = 60000; // Huge volume spike at breakout

        // MA Logic
        const ma5 = close - 100;
        const ma20 = close - 500;

        const rsi = 60 + Math.min(25, i / 2); // High RSI
        const bbUpper = ma20 + 2000; // Wide bands
        const bbLower = ma20 - 2000;
        const vwap = close * 0.98;

        const datum: MockDatum = {
            time, open, high, low, close, ma5, ma20, volume, rsi, vwap, bbUpper, bbLower
        };

        // --- Simulated Logic Triggers ---

        // T=12: Breakout Entry
        if (i === 12) {
            datum.marker = { text: "매수: 돌파", color: "#2ECC71", position: "belowBar", shape: "arrowUp" };
            events.push({ step: i, type: "BUY", title: "공격적 진입", desc: "단기 고점 돌파 + 거래량 3배 + 점수 85점" });
        }

        // T=25: Scale Out L1 (+7%) - Bull regime has higher targets
        if (i === 25) {
            datum.marker = { text: "매도: 1차 익절", color: "#F1C40F", position: "aboveBar", shape: "arrowDown" };
            events.push({ step: i, type: "SELL", title: "1차 분할 매도 (+7%)", desc: "상승장 로직: 목표 수익률 상향 적용." });
        }

        // T=35: Scale Out L2 (+15%)
        if (i === 35) {
            datum.marker = { text: "매도: 2차 익절", color: "#F1C40F", position: "aboveBar", shape: "arrowDown" };
            events.push({ step: i, type: "SELL", title: "2차 분할 매도 (+15%)", desc: "대세 상승 수익 확정. 잔여 물량 홀딩." });
        }

        // T=45: Trailing Stop Activated
        if (i === 45) {
            events.push({ step: i, type: "INFO", title: "트레일링 스톱 활성화", desc: "고점 갱신. 고점 대비 -3.5%로 스톱 라인 상향." });
        }

        // T=55: Trailing Stop Hit (Exit)
        if (i === 55) {
            datum.close = datum.open - 300; // sharp drop
            datum.marker = { text: "매도: 트레일링", color: "#E74C3C", position: "aboveBar", shape: "arrowDown" };
            events.push({ step: i, type: "SELL", title: "트레일링 스톱 체결", desc: "전량 매도. 추세 반전 감지." });
        }

        data.push(datum);
    }

    return {
        regime: 'BULL',
        title: "트렌드 헌터 (상승장)",
        description: "강세장에 최적화. 거래량 동반 돌파 및 모멘텀을 추종합니다. 트레일링 스톱과 넓은 익절 폭(7%/15%)으로 추세 끝까지 수익을 냅니다.",
        data,
        events,
        stats: { totalReturn: "+14.8%", riskReward: "1 : 5.2", duration: "43일", winRate: "중립 (45%)" }
    };
}

// Scenario C: Bear Market (Crash / Deep Value)
function generateBearScenario(): ScenarioData {
    const data: MockDatum[] = [];
    const events: TradeEvent[] = [];

    // 60 days of data
    for (let i = 0; i < 60; i++) {
        const time = createDate(60 - i);

        // Downtrend pattern
        const trend = - (i * 50);
        const noise = (Math.random() - 0.5) * 150;

        let close = 10000 + trend + noise;
        // Panic selling candles (gap downs)
        let open = close + (Math.random() * 80) + 20;
        if (i % 5 === 0) open = close + 150; // Big drop candle

        let high = Math.max(open, close) + Math.random() * 50;
        let low = Math.min(open, close) - Math.random() * 100;

        // MA Logic (Death Cross state)
        const ma5 = close + 50;
        const ma20 = close + 300; // Price far below MA20

        // RSI Logic (Oversold most of the time)
        const rsi = 35 + Math.sin(i / 3) * 15; // Dips below 30 often

        const bbUpper = ma20 + 500;
        const bbLower = ma20 - 500;
        const vwap = close * 1.01;

        const datum: MockDatum = {
            time, open, high, low, close, ma5, ma20, volume: 10000, rsi, vwap, bbUpper, bbLower
        };

        // --- Simulated Logic Triggers ---

        // T=15: Deep Oversold Entry (RSI < 25)
        if (i === 15) {
            datum.rsi = 22; // Deep oversold
            datum.marker = { text: "매수: 과매도", color: "#2ECC71", position: "belowBar", shape: "arrowUp" };
            events.push({ step: i, type: "BUY", title: "역추세 진입", desc: "하락장 로직: RSI 과매도(<25). 기술적 반등(Dead-cat) 예상." });
        }

        // T=18: Quick Scale Out L1 (+2%)
        if (i === 18) {
            // Bounce happened
            datum.close = datum.open + 200;
            datum.marker = { text: "매도: 1차 익절", color: "#F1C40F", position: "aboveBar", shape: "arrowDown" };
            events.push({ step: i, type: "SELL", title: "빠른 익절 (+2%)", desc: "하락장 로직: 반등 시 즉시 현금화." });
        }

        // T=22: Stop Loss (Re-crash)
        if (i === 22) {
            datum.close = datum.open - 400; // Crash resumes
            datum.marker = { text: "매도: 손절", color: "#E74C3C", position: "aboveBar", shape: "square" };
            events.push({ step: i, type: "SELL", title: "방어적 탈출", desc: "재진입 실패. 자본 보존을 위해 즉시 청산." });
        }

        // T=40: No Trade Zone
        if (i === 40) {
            events.push({ step: i, type: "WARNING", title: "거래 차단", desc: "시스템 진입 차단. 하락 모멘텀 과다." });
        }

        data.push(datum);
    }

    return {
        regime: 'BEAR',
        title: "위기 관리자 (하락장)",
        description: "폭락장에 최적화. 극도로 보수적입니다. 침체권(RSI < 25) 기술적 반등만 노리며, 줄 때 먹고(2%) 빠집니다.",
        data,
        events,
        stats: { totalReturn: "-0.5% (vs 시장 -15%)", riskReward: "1 : 1.5", duration: "12일", winRate: "낮음 (30%)" }
    };
}



// --- Component ---

export default function VisualLogic() {
    const [scenario, setScenario] = useState<MarketRegime>('SIDEWAYS');

    const activeData = useMemo(() => {
        if (scenario === 'SIDEWAYS') return generateSidewaysScenario();
        else if (scenario === 'BULL') return generateBullScenario();
        else return generateBearScenario();
    }, [scenario]);

    // Element Refs
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
    const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const ma5SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const ma20SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const bbUSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const bbLSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

    // Chart Initialization
    useEffect(() => {
        if (!chartContainerRef.current) return;

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: 'transparent' },
                textColor: '#9CA3AF'
            },
            grid: {
                vertLines: { color: 'rgba(255, 255, 255, 0.05)' },
                horzLines: { color: 'rgba(255, 255, 255, 0.05)' },
            },
            width: chartContainerRef.current.clientWidth,
            height: 350,
            timeScale: {
                borderColor: 'rgba(255, 255, 255, 0.1)',
            },
            rightPriceScale: {
                borderColor: 'rgba(255, 255, 255, 0.1)',
            },
        });

        // Series
        const candleSeries = chart.addCandlestickSeries({
            upColor: '#2ECC71',
            downColor: '#EF4444',
            borderVisible: false,
            wickUpColor: '#2ECC71',
            wickDownColor: '#EF4444',
        });

        const ma5Series = chart.addLineSeries({ color: '#3B82F6', lineWidth: 1, title: 'MA5' });
        const ma20Series = chart.addLineSeries({ color: '#F59E0B', lineWidth: 1, title: 'MA20' });
        const bbUSeries = chart.addLineSeries({ color: 'rgba(147, 197, 253, 0.3)', lineWidth: 1, lineStyle: LineStyle.Dotted, title: 'BB Upper' });
        const bbLSeries = chart.addLineSeries({ color: 'rgba(147, 197, 253, 0.3)', lineWidth: 1, lineStyle: LineStyle.Dotted, title: 'BB Lower' });

        candleSeriesRef.current = candleSeries;
        ma5SeriesRef.current = ma5Series;
        ma20SeriesRef.current = ma20Series;
        bbUSeriesRef.current = bbUSeries;
        bbLSeriesRef.current = bbLSeries;
        chartRef.current = chart;

        const handleResize = () => {
            if (chartContainerRef.current) {
                chart.applyOptions({ width: chartContainerRef.current.clientWidth });
            }
        };
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, [scenario]);

    // Data Update
    useEffect(() => {
        if (!chartRef.current || !candleSeriesRef.current) return;

        const { data } = activeData;
        const candles = data.map(d => ({ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close }));
        const ma5 = data.map(d => ({ time: d.time, value: d.ma5 }));
        const ma20 = data.map(d => ({ time: d.time, value: d.ma20 }));
        const bbU = data.map(d => ({ time: d.time, value: d.bbUpper }));
        const bbL = data.map(d => ({ time: d.time, value: d.bbLower }));

        candleSeriesRef.current.setData(candles);
        ma5SeriesRef.current?.setData(ma5);
        ma20SeriesRef.current?.setData(ma20);
        bbUSeriesRef.current?.setData(bbU);
        bbLSeriesRef.current?.setData(bbL);

        // Map markers
        const markers = data
            .filter(d => d.marker)
            .map(d => ({
                time: d.time,
                position: d.marker!.position,
                color: d.marker!.color,
                shape: d.marker!.shape,
                text: d.marker!.text,
            }));
        // @ts-ignore
        candleSeriesRef.current.setMarkers(markers);

        chartRef.current.timeScale().fitContent();

    }, [activeData]);

    return (
        <div className="p-6 bg-[#0D0D0F] min-h-screen text-gray-200 font-sans">
            <header className="mb-8">
                <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-500">
                    프라임 제니 적응형 트레이딩 로직
                </h1>
                <p className="text-gray-500 mt-2 text-sm">
                    현재 시장 국면(Market Regime)에 따라 진입, 청산, 리스크 관리 전략을 동적으로 최적화합니다.
                </p>
            </header>

            {/* Scenario Selector */}
            <div className="flex gap-4 mb-6">
                <button
                    onClick={() => setScenario('SIDEWAYS')}
                    className={`flex-1 p-4 rounded-xl border transition-all duration-300 ${scenario === 'SIDEWAYS'
                        ? 'bg-blue-500/10 border-blue-500 text-blue-400'
                        : 'bg-[#1A1A1F] border-white/5 hover:bg-[#242429]'
                        }`}
                >
                    <div className="flex justify-between items-center mb-2">
                        <span className="font-bold text-lg">시나리오 A: 횡보장 (박스권)</span>
                        <span className="text-xs bg-blue-500/20 text-blue-300 px-2 py-1 rounded">방어형</span>
                    </div>
                    <p className="text-xs text-left opacity-70">
                        "방어가 최선의 공격입니다." RSI 반등과 볼린저 밴드 하단을 공략해 짧은 수익을 반복하며, 조기 수익 확정(Profit Lock)으로 손실을 차단합니다.
                    </p>
                </button>

                <button
                    onClick={() => setScenario('BULL')}
                    className={`flex-1 p-4 rounded-xl border transition-all duration-300 ${scenario === 'BULL'
                        ? 'bg-green-500/10 border-green-500 text-green-400'
                        : 'bg-[#1A1A1F] border-white/5 hover:bg-[#242429]'
                        }`}
                >
                    <div className="flex justify-between items-center mb-2">
                        <span className="font-bold text-lg">시나리오 B: 상승장 (추세)</span>
                        <span className="text-xs bg-green-500/20 text-green-300 px-2 py-1 rounded">공격형</span>
                    </div>
                    <p className="text-xs text-left opacity-70">
                        "수익을 끝까지 추구합니다." 돌파 매매와 거래량 급증을 포착하며, 목표가를 상향하고 트레일링 스톱을 넓게 설정해 추세를 극대화합니다.
                    </p>
                </button>

                <button
                    onClick={() => setScenario('BEAR')}
                    className={`flex-1 p-4 rounded-xl border transition-all duration-300 ${scenario === 'BEAR'
                        ? 'bg-red-500/10 border-red-500 text-red-400'
                        : 'bg-[#1A1A1F] border-white/5 hover:bg-[#242429]'
                        }`}
                >
                    <div className="flex justify-between items-center mb-2">
                        <span className="font-bold text-lg">시나리오 C: 하락장 (폭락)</span>
                        <span className="text-xs bg-red-500/20 text-red-300 px-2 py-1 rounded">생존형</span>
                    </div>
                    <p className="text-xs text-left opacity-70">
                        "현금이 왕입니다." 과매도(RSI &lt; 25) 구간에서만 제한적으로 진입하며, 짧은 반등에 즉시 매도하여 리스크를 최소화합니다.
                    </p>
                </button>
            </div>

            {/* Main Content Area */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Left: Chart & Stats */}
                <div className="lg:col-span-2 space-y-6">
                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        key={scenario}
                        className="bg-[#1A1A1F] rounded-xl border border-white/10 p-4"
                    >
                        <div className="flex justify-between items-center mb-4">
                            <div>
                                <h3 className="text-xl font-bold text-white">{activeData.title}</h3>
                                <p className="text-xs text-gray-500">{activeData.description}</p>
                            </div>
                            <div className="flex gap-4 text-xs font-mono">
                                <div className="text-center">
                                    <div className="text-gray-500">누적 수익률</div>
                                    <div className={`font-bold ${activeData.regime === 'BULL' ? 'text-green-400' :
                                        activeData.regime === 'SIDEWAYS' ? 'text-blue-400' : 'text-red-400'
                                        }`}>
                                        {activeData.stats.totalReturn}
                                    </div>
                                </div>
                                <div className="text-center">
                                    <div className="text-gray-500">손익비</div>
                                    <div className="text-white">{activeData.stats.riskReward}</div>
                                </div>
                            </div>
                        </div>

                        {/* Chart Area */}
                        <div ref={chartContainerRef} className="w-full h-[350px] bg-black/20 rounded-lg overflow-hidden relative" />

                        <div className="flex gap-4 mt-4 text-xs text-gray-500 justify-center">
                            <div className="flex items-center gap-1"><span className="w-3 h-3 bg-green-500 rounded-sm"></span> 매수 신호</div>
                            <div className="flex items-center gap-1"><span className="w-3 h-3 bg-yellow-500 rounded-sm"></span> 분할 매도</div>
                            <div className="flex items-center gap-1"><span className="w-3 h-3 bg-red-500 rounded-sm"></span> 전량 매도</div>
                            <div className="flex items-center gap-1"><span className="w-3 h-0.5 bg-blue-500"></span> MA5</div>
                            <div className="flex items-center gap-1"><span className="w-3 h-0.5 bg-yellow-600"></span> MA20</div>
                        </div>
                    </motion.div>
                </div>

                {/* Right: Narrative Log */}
                <div className="bg-[#1A1A1F] rounded-xl border border-white/10 p-4 flex flex-col h-full">
                    <h3 className="font-bold text-white mb-4 flex items-center gap-2">
                        <span className="text-lg">📜</span> 매매 실행 로그
                    </h3>
                    <div className="flex-1 overflow-y-auto space-y-4 pr-2 custom-scrollbar">
                        <AnimatePresence mode='popLayout'>
                            {activeData.events.map((event, idx) => (
                                <motion.div
                                    key={`${scenario}-${idx}`}
                                    initial={{ opacity: 0, x: 20 }}
                                    animate={{ opacity: 1, x: 0 }}
                                    transition={{ delay: idx * 0.1 }}
                                    className="relative pl-6 pb-2"
                                >
                                    {/* Timeline Line */}
                                    <div className="absolute left-0 top-2 bottom-0 w-0.5 bg-gray-800"></div>
                                    <div className={`absolute left-[-4px] top-2 w-2.5 h-2.5 rounded-full border-2 border-[#1A1A1F] ${event.type === 'BUY' ? 'bg-green-500' :
                                        event.type === 'SELL' ? 'bg-red-500' :
                                            event.type === 'WARNING' ? 'bg-yellow-500' : 'bg-blue-500'
                                        }`}></div>

                                    <div className={`p-3 rounded-lg border ${event.type === 'BUY' ? 'bg-green-500/10 border-green-500/30' :
                                        event.type === 'SELL' ? 'bg-red-500/10 border-red-500/30' :
                                            event.type === 'WARNING' ? 'bg-yellow-500/10 border-yellow-500/30' :
                                                'bg-gray-800/50 border-gray-700'
                                        }`}>
                                        <div className="flex justify-between items-center mb-1">
                                            <span className={`text-xs font-bold ${event.type === 'BUY' ? 'text-green-400' :
                                                event.type === 'SELL' ? 'text-red-400' :
                                                    'text-gray-300'
                                                }`}>{event.title}</span>
                                            <span className="text-[10px] opacity-50 font-mono">T={event.step}</span>
                                        </div>
                                        <p className="text-xs text-gray-400 leading-relaxed">
                                            {event.desc}
                                        </p>
                                    </div>
                                </motion.div>
                            ))}
                        </AnimatePresence>
                    </div>
                </div>
            </div>

            <div className="mt-8 text-center text-xs text-gray-600">
                * 이 시각화 도구는 프라임 제니의 결정론적 시나리오를 시뮬레이션한 것입니다.<br />
                실제 시장 성과는 유동성 및 슬리피지에 따라 달라질 수 있습니다.
            </div>
        </div>
    );
}

// Add custom scrollbar styles to global CSS or inline
const style = document.createElement('style');
style.textContent = `
    .custom-scrollbar::-webkit-scrollbar {
        width: 4px;
    }
    .custom-scrollbar::-webkit-scrollbar-track {
        background: rgba(255, 255, 255, 0.02);
    }
    .custom-scrollbar::-webkit-scrollbar-thumb {
        background: rgba(255, 255, 255, 0.1);
        border-radius: 2px;
    }
`;
document.head.appendChild(style);
