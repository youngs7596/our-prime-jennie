import { useEffect, useRef, useState, useMemo } from 'react';
import {
    createChart,
    ISeriesApi,
    Time,
    ColorType,
    LineStyle,
} from 'lightweight-charts';
import { motion, AnimatePresence } from 'framer-motion';
import { logicApi, LogicStatusResponse } from '../../api/logic';
import { watchlistApi } from '../../lib/api';

// --- Types ---
type MarketRegime = 'SIDEWAYS' | 'BULL' | 'BEAR' | 'REAL';

type PriceLineDef = {
    price: number;
    color: string;
    title: string;
    lineStyle: LineStyle;
};

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
    priceLines: PriceLineDef[];
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

// --- Helper Functions ---

const calculateSMA = (data: number[], period: number): number[] => {
    const sma = new Array(data.length).fill(NaN);
    for (let i = period - 1; i < data.length; i++) {
        const sum = data.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0);
        sma[i] = sum / period;
    }
    return sma;
};

const calculateBollingerBands = (data: number[], period: number = 20, multiplier: number = 2.0) => {
    const sma = calculateSMA(data, period);
    const bands = new Array(data.length).fill({ upper: NaN, lower: NaN });

    for (let i = period - 1; i < data.length; i++) {
        const slice = data.slice(i - period + 1, i + 1);
        const mean = sma[i];
        const squaredDiffs = slice.map(val => Math.pow(val - mean, 2));
        const variance = squaredDiffs.reduce((a, b) => a + b, 0) / period;
        const stdDev = Math.sqrt(variance);

        bands[i] = {
            upper: mean + multiplier * stdDev,
            lower: mean - multiplier * stdDev
        };
    }
    return bands;
};

const calculateRSI = (data: number[], period: number = 14): number[] => {
    const rsi = new Array(data.length).fill(NaN);
    let gains = 0;
    let losses = 0;

    // First average gain/loss
    for (let i = 1; i <= period; i++) {
        const diff = data[i] - data[i - 1];
        if (diff >= 0) gains += diff;
        else losses -= diff;
    }

    let avgGain = gains / period;
    let avgLoss = losses / period;

    rsi[period] = 100 - (100 / (1 + avgGain / avgLoss));

    // Smoothed RSI
    for (let i = period + 1; i < data.length; i++) {
        const diff = data[i] - data[i - 1];
        const gain = diff >= 0 ? diff : 0;
        const loss = diff < 0 ? -diff : 0;

        avgGain = (avgGain * (period - 1) + gain) / period;
        avgLoss = (avgLoss * (period - 1) + loss) / period;

        if (avgLoss === 0) rsi[i] = 100;
        else rsi[i] = 100 - (100 / (1 + avgGain / avgLoss));
    }

    return rsi;
};

// --- Generators ---

const createDate = (daysAgo: number) => {
    const d = new Date();
    d.setDate(d.getDate() - daysAgo);
    return d.toISOString().split('T')[0] as Time;
};

const generateBaseData = (length: number, startPrice: number) => {
    // Generate empty skeleton
    return Array.from({ length }, (_, i) => ({
        time: createDate(length - i),
        close: startPrice,
        open: startPrice,
        high: startPrice,
        low: startPrice,
        volume: 10000
    }));
};

function generateSidewaysScenario(): ScenarioData {
    const length = 60;
    const basePrices = generateBaseData(length, 10000);
    const events: TradeEvent[] = [];
    const priceLines: PriceLineDef[] = [];

    // 1. Create Price Action (Sine wave for box pattern)
    // Intention: Perfect box range 9500 ~ 10500
    for (let i = 0; i < length; i++) {
        const phase = i / 10;
        // Base sine wave
        let price = 10000 + Math.sin(phase) * 500;

        // T=15: Force Dip for Buy Signal (RSI Divergence / Support Touch)
        // Intention: Drop close to 9400 to trigger RSI < 30 or BB Lower touch
        if (i >= 13 && i <= 15) {
            price = 9400 + (15 - i) * 100; // 13: 9600, 14: 9500, 15: 9400
        }
        // T=16~18: Rebound
        if (i >= 16 && i <= 18) {
            price = 9400 + (i - 15) * 200;
        }

        // T=35: False break down
        if (i === 35) {
            price = 9600;
        }

        const volatility = 100;

        basePrices[i].close = price;
        basePrices[i].open = i > 0 ? basePrices[i - 1].close : price;
        basePrices[i].high = Math.max(basePrices[i].open, basePrices[i].close) + Math.random() * volatility;
        basePrices[i].low = Math.min(basePrices[i].open, basePrices[i].close) - Math.random() * volatility;
        basePrices[i].volume = 10000 + Math.abs(Math.sin(i)) * 5000;
    }

    // 2. Calculate Indicators
    const closes = basePrices.map(d => d.close);
    const ma5 = calculateSMA(closes, 5);
    const ma20 = calculateSMA(closes, 20);
    const bb = calculateBollingerBands(closes, 20);
    const rsi = calculateRSI(closes, 14);

    // 3. Merge Data
    const data: MockDatum[] = basePrices.map((d, i) => ({
        ...d,
        ma5: ma5[i] || d.close, // fallback for initial
        ma20: ma20[i] || d.close,
        bbUpper: bb[i].upper || d.close * 1.05,
        bbLower: bb[i].lower || d.close * 0.95,
        rsi: rsi[i] || 50,
        vwap: d.close, // simplified
    }));

    // 4. Attach Events based on verified logic
    // T=15
    const idxEntry = 15;
    data[idxEntry].marker = { text: "매수: 저점 포착", color: "#2ECC71", position: "belowBar", shape: "arrowUp" };
    events.push({ step: idxEntry, type: "BUY", title: "박스권 하단 진입", desc: `RSI ${data[idxEntry].rsi.toFixed(0)} + BB하단 터치. 기술적 반등 위치.` });

    // T=25 (Peak of wave)
    const idxSell1 = 25;
    data[idxSell1].marker = { text: "익절: 박스상단", color: "#F1C40F", position: "aboveBar", shape: "arrowDown" };
    events.push({ step: idxSell1, type: "SELL", title: "1차 익절 완료", desc: "박스권 상단 도달. 저항선에서 안전마진 확보 (+5%)." });

    // T=35 (Dip again)
    const idxCut = 35;
    data[idxCut].marker = { text: "청산: 지지이탈", color: "#E74C3C", position: "aboveBar", shape: "arrowDown" };
    events.push({ step: idxCut, type: "SELL", title: "Profit Lock 발동", desc: "예상 경로 이탈(하락 반전). 잔여 물량 본전 청산으로 수익 보존." });

    return {
        regime: 'SIDEWAYS',
        title: "디펜시브 스나이퍼 (박스권)",
        description: "횡보장에서는 '쌀 때 사서 비쌀 때 파는' 정석적인 박스권 매매를 수행합니다. 볼린저 밴드 하단과 RSI 과매도를 정확히 타격합니다.",
        data,
        events,
        priceLines,
        stats: { totalReturn: "+3.2%", riskReward: "1 : 3.5", duration: "20일", winRate: "높음 (75%)" }
    };
}

function generateBullScenario(): ScenarioData {
    const length = 60;
    const basePrices = generateBaseData(length, 10000);
    const events: TradeEvent[] = [];
    const priceLines: PriceLineDef[] = [];

    // Intention: Breakout + Trend Following
    for (let i = 0; i < length; i++) {
        // Base: 10000 -> 14000
        let price = 10000;

        if (i < 12) {
            // Consolidation before breakout
            price = 10000 + Math.sin(i) * 100;
        } else {
            // Trend
            price = 10000 + Math.pow(i - 10, 1.8) * 3;
        }

        // T=12: Breakout Candle
        if (i === 12) {
            price = 10500; // Jump
            basePrices[i].volume = 50000; // Volume Spike
        }

        // T=45: Correction
        if (i === 45) basePrices[i].volume = 30000; // Sell volume

        const volatility = i > 12 ? 150 : 50;

        basePrices[i].close = price;
        basePrices[i].open = i > 0 ? basePrices[i - 1].close : price;
        basePrices[i].high = Math.max(basePrices[i].open, basePrices[i].close) + Math.random() * volatility;
        basePrices[i].low = Math.min(basePrices[i].open, basePrices[i].close) - Math.random() * volatility;

        if (i !== 12 && i !== 45) basePrices[i].volume = 10000 + Math.random() * 5000;
    }

    const closes = basePrices.map(d => d.close);
    const ma5 = calculateSMA(closes, 5);
    const ma20 = calculateSMA(closes, 20);
    const bb = calculateBollingerBands(closes, 20);
    const rsi = calculateRSI(closes, 14);

    const data: MockDatum[] = basePrices.map((d, i) => ({
        ...d,
        ma5: ma5[i] || d.close,
        ma20: ma20[i] || d.close,
        bbUpper: bb[i].upper || d.close,
        bbLower: bb[i].lower || d.close,
        rsi: rsi[i] || 60,
        vwap: d.close,
    }));

    // T=12: Breakout
    const idxEntry = 12;
    data[idxEntry].marker = { text: "매수: 돌파", color: "#2ECC71", position: "belowBar", shape: "arrowUp" };
    events.push({ step: idxEntry, type: "BUY", title: "강력한 돌파 매수", desc: "저항선 돌파 + 거래량 500% 급증. 골든크로스 확정." });

    // T=25
    const idxSell1 = 25;
    data[idxSell1].marker = { text: "1차 익절", color: "#F1C40F", position: "aboveBar", shape: "arrowDown" };
    events.push({ step: idxSell1, type: "SELL", title: "추세 추종 (1차)", desc: "상승 추세 강화. 목표 수익률(+10%) 도달로 일부 차익 실현." });

    // T=40
    const idxSell2 = 40;
    data[idxSell2].marker = { text: "2차 익절", color: "#F1C40F", position: "aboveBar", shape: "arrowDown" };
    events.push({ step: idxSell2, type: "SELL", title: "추세 추종 (2차)", desc: "가속화 구간. +25% 수익 구간에서 추가 익절. 트레일링 스톱 가동." });

    // T=55 (End of trend)
    const idxExit = 55;
    data[idxExit].marker = { text: "전량매도", color: "#E74C3C", position: "aboveBar", shape: "arrowDown" };
    events.push({ step: idxExit, type: "SELL", title: "트레일링 스톱 청산", desc: "MA5 이탈 및 추세 꺾임 확인. 전량 매도로 추세 매매 종료." });


    return {
        regime: 'BULL',
        title: "트렌드 헌터 (상승장)",
        description: "상승 추세에서는 거래량이 실린 돌파 시점에 진입하여, MA20을 깨지 않는 한 끝까지 보유합니다 (Let profits run).",
        data,
        events,
        priceLines,
        stats: { totalReturn: "+28.4%", riskReward: "1 : 7.2", duration: "43일", winRate: "중립 (50%)" }
    };
}

function generateBearScenario(): ScenarioData {
    const length = 60;
    const basePrices = generateBaseData(length, 10000);
    const events: TradeEvent[] = [];
    const priceLines: PriceLineDef[] = [];

    // Intention: Crash -> Oversold bounce -> Crash again
    for (let i = 0; i < length; i++) {
        let price = 10000 - (i * 80); // Downtrend

        // T=15: Deep dip (Panic sell)
        if (i === 15) price = price - 500;

        // T=16~18: Dead cat bounce
        if (i >= 16 && i <= 18) price = price + 300;

        // T=22: Crash deeper
        if (i >= 22) price = price - 600;

        const volatility = 100;
        basePrices[i].close = price;
        basePrices[i].open = i > 0 ? basePrices[i - 1].close : price + 50;
        basePrices[i].high = Math.max(basePrices[i].open, basePrices[i].close) + Math.random() * volatility;
        basePrices[i].low = Math.min(basePrices[i].open, basePrices[i].close) - Math.random() * volatility;
        basePrices[i].volume = 10000;

        if (i === 15) basePrices[i].volume = 30000; // Panic volume
    }

    const closes = basePrices.map(d => d.close);
    const ma5 = calculateSMA(closes, 5);
    const ma20 = calculateSMA(closes, 20);
    const bb = calculateBollingerBands(closes, 20);
    const rsi = calculateRSI(closes, 14);

    const data: MockDatum[] = basePrices.map((d, i) => ({
        ...d,
        ma5: ma5[i] || d.close,
        ma20: ma20[i] || d.close,
        bbUpper: bb[i].upper || d.close,
        bbLower: bb[i].lower || d.close,
        rsi: rsi[i] || 30,
        vwap: d.close,
    }));

    // T=15: Oversold
    const idxEntry = 15;
    data[idxEntry].marker = { text: "매수: 과매도", color: "#2ECC71", position: "belowBar", shape: "arrowUp" };
    events.push({ step: idxEntry, type: "BUY", title: "낙주 매매 (Scalping)", desc: `RSI ${data[idxEntry].rsi.toFixed(0)}(<25) 극단적 과매도. 단기 반등을 노린 스캘핑 진입.` });

    // T=18: Quick Profit
    const idxSell = 18;
    data[idxSell].marker = { text: "익절: 전량", color: "#F1C40F", position: "aboveBar", shape: "arrowDown" };
    events.push({ step: idxSell, type: "SELL", title: "빠른 청산 (+3%)", desc: "데드캣 바운스 확인 즉시 전량 현금화. 하락장에서는 욕심내지 않습니다." });

    // T=22: Warning
    const idxWarn = 22;
    events.push({ step: idxWarn, type: "WARNING", title: "재진입 금지", desc: "2차 하락 파동 시작. 모든 매수 시그널 필터링." });

    return {
        regime: 'BEAR',
        title: "위기 관리자 (하락장)",
        description: "하락장에서는 현금을 지키는 것이 1순위입니다. RSI 20 이하의 투매(Panic Sell) 구간에서만 짧게 진입하여 반등만 취합니다.",
        data,
        events,
        priceLines,
        stats: { totalReturn: "+3.0%", riskReward: "1 : 2.0", duration: "3일", winRate: "낮음 (30%)" }
    };
}

function convertRealDataToScenario(response: LogicStatusResponse): ScenarioData {
    const { chart_data, snapshot, stock_code } = response;

    // Map Chart Data
    // Map Chart Data and Ensure Validity
    const validData = chart_data
        .filter(d => d && d.time && typeof d.close === 'number' && !isNaN(d.close))
        .sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime());

    // Remove duplicates
    const uniqueData = validData.filter((item, index, self) =>
        index === self.findIndex((t) => t.time === item.time)
    );

    const data: MockDatum[] = uniqueData.map(d => ({
        time: d.time as Time,
        open: d.open || 0,
        high: d.high || 0,
        low: d.low || 0,
        close: d.close || 0,
        volume: d.volume || 0,
        ma5: d.close, // TODO: calculate real MA
        ma20: d.close,
        bbUpper: d.close * 1.05,
        bbLower: d.close * 0.95,
        rsi: (snapshot?.rsi !== null && snapshot?.rsi !== undefined) ? snapshot.rsi : 50,
        vwap: d.close,
    }));

    const events: TradeEvent[] = [];
    const priceLines: PriceLineDef[] = [];

    if (snapshot) {
        // Stop Loss Line
        if (snapshot.stop_loss_price) {
            priceLines.push({
                price: snapshot.stop_loss_price,
                color: '#EF4444',
                title: 'Stop Loss',
                lineStyle: LineStyle.Solid
            });
        }
        // Profit Floor
        if (snapshot.profit_floor_price) {
            priceLines.push({
                price: snapshot.profit_floor_price,
                color: '#3B82F6',
                title: 'Profit Floor',
                lineStyle: LineStyle.Dotted
            });
        }
        // Buy Price
        if (snapshot.buy_price) {
            priceLines.push({
                price: snapshot.buy_price,
                color: '#10B981',
                title: 'Buy Price',
                lineStyle: LineStyle.Dashed
            });
        }

        // Add Logic Reason
        if (snapshot.active_signal) {
            events.push({
                step: data.length - 1,
                type: 'SELL',
                title: '매도 신호 발생',
                desc: snapshot.active_signal.reason
            });
        } else {
            events.push({
                step: data.length - 1,
                type: 'INFO',
                title: '현재 상태: 홀딩',
                desc: `수익률: ${(snapshot.profit_pct ?? 0).toFixed(2)}%, RSI: ${snapshot.rsi?.toFixed(1) || 'N/A'}`
            });
        }
    }

    return {
        regime: 'REAL',
        title: `${snapshot?.stock_name || stock_code} (Real-Time)`,
        description: "실시간 감시 데이터를 기반으로 한 로직 시각화입니다.",
        data,
        events,
        priceLines,
        stats: {
            totalReturn: snapshot ? `${(snapshot.profit_pct ?? 0).toFixed(1)}%` : '-',
            riskReward: "-",
            duration: "-",
            winRate: "-"
        }
    };
}



// --- Component ---

export default function VisualLogic() {
    const [scenario, setScenario] = useState<MarketRegime>('SIDEWAYS');
    const [realStock, setRealStock] = useState<string>('');
    const [watchlist, setWatchlist] = useState<{ stock_code: string, stock_name: string }[]>([]);
    const [realData, setRealData] = useState<ScenarioData | null>(null);

    // Fetch Watchlist
    useEffect(() => {
        watchlistApi.getAll(100).then(items => {
            // @ts-ignore
            setWatchlist(items);
            if (items.length > 0) setRealStock(items[0].stock_code);
        }).catch(err => console.error(err));
    }, []);

    // Fetch Real Data when mode is REAL and stock changes
    useEffect(() => {
        if (scenario === 'REAL' && realStock) {
            logicApi.getStatus(realStock).then(res => {
                setRealData(convertRealDataToScenario(res));
            }).catch(err => console.error(err));
            // Poll every 5 seconds for real-time updates
            const interval = setInterval(() => {
                logicApi.getStatus(realStock).then(res => {
                    setRealData(convertRealDataToScenario(res));
                }).catch(err => console.error(err));
            }, 5000);
            return () => clearInterval(interval);
        }
    }, [scenario, realStock]);


    const activeData = useMemo(() => {
        if (scenario === 'SIDEWAYS') return generateSidewaysScenario();
        else if (scenario === 'BULL') return generateBullScenario();
        else if (scenario === 'BEAR') return generateBearScenario();
        else return realData || generateSidewaysScenario(); // Fallback
    }, [scenario, realData]);

    // Element Refs
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
    const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const ma5SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const ma20SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const bbUSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    const bbLSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
    // const priceLinesRef = useRef<IPriceLine[]>([]);

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

        // Strict validation with LOGGING
        console.log('[VisualLogic] Processing', data.length, 'candles');
        const validCandles = data
            .filter(d => {
                const isValid = d && d.time &&
                    typeof d.open === 'number' && !isNaN(d.open) &&
                    typeof d.high === 'number' && !isNaN(d.high) &&
                    typeof d.low === 'number' && !isNaN(d.low) &&
                    typeof d.close === 'number' && !isNaN(d.close);
                if (!isValid) console.warn('[VisualLogic] Invalid Candle Dropped:', d);
                return isValid;
            })
            .map(d => ({
                time: d.time as string,
                open: d.open,
                high: d.high,
                low: d.low,
                close: d.close,
                ma5: d.ma5,
                ma20: d.ma20,
                bbUpper: d.bbUpper,
                bbLower: d.bbLower,
                volume: d.volume,
                rsi: d.rsi,
                vwap: d.vwap,
            }));

        // Deduplicate and Sort
        const uniqueCandlesMap = new Map();
        validCandles.forEach(c => uniqueCandlesMap.set(c.time, c));
        const sortedCandles = Array.from(uniqueCandlesMap.values()).sort((a, b) => (a.time > b.time ? 1 : -1));

        const finalCandles = sortedCandles.map(c => ({
            ...c,
            time: c.time as Time
        }));

        console.log(`[VisualLogic] setData | Original: ${data.length} | Final: ${finalCandles.length}`);

        if (finalCandles.length > 0) {
            try {
                candleSeriesRef.current.setData(finalCandles);

                // Set Indicators
                const ma5Data = finalCandles.map(c => ({ time: c.time, value: c.ma5 }));
                const ma20Data = finalCandles.map(c => ({ time: c.time, value: c.ma20 }));
                const bbUData = finalCandles.map(c => ({ time: c.time, value: c.bbUpper }));
                const bbLData = finalCandles.map(c => ({ time: c.time, value: c.bbLower }));

                if (ma5SeriesRef.current) ma5SeriesRef.current.setData(ma5Data);
                if (ma20SeriesRef.current) ma20SeriesRef.current.setData(ma20Data);
                if (bbUSeriesRef.current) bbUSeriesRef.current.setData(bbUData);
                if (bbLSeriesRef.current) bbLSeriesRef.current.setData(bbLData);

            } catch (err) {
                console.error('[VisualLogic] CRITICAL: setData failed with SORTED data!', err);
            }
        }
        // ma5SeriesRef.current?.setData(ma5);
        // ma20SeriesRef.current?.setData(ma20);
        // bbUSeriesRef.current?.setData(bbU);
        // bbLSeriesRef.current?.setData(bbL);



        // Map markers
        /*
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
        */
        // candleSeriesRef.current.setMarkers([]);

        // Price Lines
        // priceLinesRef.current.forEach(line => candleSeriesRef.current?.removePriceLine(line));
        // priceLinesRef.current = [];

        /*
        if (activeData.priceLines) {
            activeData.priceLines.forEach(line => {
                const pl = candleSeriesRef.current?.createPriceLine({
                    price: line.price,
                    color: line.color,
                    title: line.title,
                    lineStyle: line.lineStyle,
                    axisLabelVisible: true,
                });
                if (pl) priceLinesRef.current.push(pl);
            });
        }
        */

        chartRef.current.timeScale().fitContent();

    }, [activeData, scenario]);

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

            {/* Read Logic Selector */}
            <div className="mb-6">
                <div className="flex items-center gap-4">
                    <button
                        onClick={() => setScenario('REAL')}
                        className={`px-6 py-2 rounded-lg font-bold border transition-all ${scenario === 'REAL'
                            ? 'bg-purple-500 text-white border-purple-500'
                            : 'bg-[#1A1A1F] text-gray-400 border-white/10 hover:bg-[#242429]'
                            }`}
                    >
                        🔮 Real-Time Observability
                    </button>

                    {scenario === 'REAL' && (
                        <select
                            value={realStock}
                            onChange={(e) => setRealStock(e.target.value)}
                            className="bg-[#1A1A1F] border border-white/20 text-white rounded px-4 py-2"
                        >
                            {watchlist.map(item => (
                                <option key={item.stock_code} value={item.stock_code}>
                                    {item.stock_name} ({item.stock_code})
                                </option>
                            ))}
                        </select>
                    )}
                </div>
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

                        {/* 
                        <div className="w-full h-[350px] bg-red-900/20 rounded-lg flex items-center justify-center border border-red-500">
                             <h2 className="text-2xl font-bold text-red-500">CHART DISABLED FOR DEBUGGING</h2>
                        </div>
                        */}

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
