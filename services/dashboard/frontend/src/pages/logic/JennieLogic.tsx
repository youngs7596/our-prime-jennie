import React, { useState } from 'react';
import { useWebSocket, BuySignal } from '../../lib/useWebSocket';
import {
    LineChart,
    Line,
    BarChart,
    Bar,

    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
    ReferenceLine
} from 'recharts';

// Mock Data Generation
const generateData = () => {
    return Array.from({ length: 20 }, (_, i) => ({
        index: i,
        ma5: [10, 12, 11, 14, 16, 18, 17, 21, 24, 26, 25, 29, 32, 35, 34, 38, 42, 45, 48, 52][i],
        ma20: [8, 9, 10, 11, 13, 14, 15, 17, 19, 20, 22, 24, 26, 28, 30, 32, 34, 37, 40, 43][i],
        rsi: [40, 45, 35, 28, 32, 45, 55, 60, 50, 65, 75, 70, 65, 60, 55, 50, 45, 50, 55, 60][i],
        volume: [5, 4, 6, 8, 12, 7, 5, 9, 15, 22, 18, 14, 10, 12, 8, 11, 19, 25, 30, 28][i]
    }));
};

const initialData = generateData();

const JennieLogic: React.FC = () => {
    // Real-time Data Integration
    const [chartData, setChartData] = useState(initialData);
    const [lastSignal, setLastSignal] = useState<BuySignal | null>(null);

    const { isConnected } = useWebSocket({
        onMessage: (msg) => {
            if (msg.type === 'buy_signal') {
                const signal = msg.data;
                setLastSignal(signal);

                // Update chart mock data with new price point
                setChartData(prev => {
                    const last = prev[prev.length - 1];
                    const nextIndex = last.index + 1;
                    // Mock logical next values based on price change
                    return [...prev.slice(1), {
                        index: nextIndex,
                        ma5: (last.ma5 * 4 + signal.price) / 5, // Simple mock
                        ma20: last.ma20, // Static for short term
                        rsi: 50 + Math.random() * 20,
                        volume: 10 + Math.random() * 20,
                    }];
                });
            }
        }
    });

    const displayInfo = lastSignal ? {
        name: lastSignal.stock_name,
        code: lastSignal.stock_code,
        price: lastSignal.price,
        status: lastSignal.signal_type
    } : {
        name: "SK Hynix Mock",
        code: "000660.KS",
        price: 72500, // Mock
        status: "WAITING"
    };
    return (
        <div className="p-6 bg-[#0D0D0F] text-[#E5E5E7] font-sans min-h-screen">
            {/* Header */}
            <div className="flex justify-between items-center mb-6">
                <div>
                    <h1 className="text-3xl font-bold text-[#007AFF] drop-shadow-[0_0_10px_rgba(0,122,255,0.5)]">
                        Prime Jennie <span className="text-white text-lg font-light">| Quantum Jump v2.0</span>
                        {isConnected && <span className="ml-3 inline-block w-3 h-3 rounded-full bg-green-500 animate-pulse align-middle" title="Connected" />}
                    </h1>
                    <p className="text-gray-500 mt-1">Target Asset: 2.1억 KRW | Strategy: Aggressive Hunter</p>
                </div>
                <div className="flex gap-4">
                    <div className="bg-[#1A1A1F]/80 border border-white/10 rounded-xl px-4 py-2 text-center">
                        <p className="text-xs text-gray-400">Total Heat</p>
                        <p className="text-xl font-bold text-green-400">3.2% / 5.0%</p>
                    </div>
                    <div className="bg-[#1A1A1F]/80 border border-white/10 rounded-xl px-4 py-2 text-center">
                        <p className="text-xs text-gray-400">Hunter Score</p>
                        <p className="text-xl font-bold text-blue-400">85 (Super Prime)</p>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Left Column: Charts */}
                <div className="lg:col-span-2 bg-[#1A1A1F]/80 border border-white/10 rounded-xl p-4">
                    <div className="flex justify-between items-center mb-4">
                        <div className="flex justify-between items-center mb-4">
                            <h3 className="font-semibold text-gray-300">Real-time Analysis ({displayInfo.name})</h3>
                            <div className="flex gap-2 text-xs">
                                <span className="flex items-center"><span className="w-3 h-3 bg-[#007AFF] mr-1 rounded-full"></span> MA5</span>
                                <span className="flex items-center"><span className="w-3 h-3 bg-[#FF9500] mr-1 rounded-full"></span> MA20</span>
                            </div>
                        </div>

                        {/* Main Trading Chart */}
                        <div className="h-[200px] w-full mb-4">
                            <ResponsiveContainer width="100%" height="100%">
                                <LineChart data={chartData}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                                    {/* <XAxis dataKey="index" hide /> */}
                                    <YAxis hide domain={['auto', 'auto']} />
                                    <Tooltip
                                        contentStyle={{ backgroundColor: '#1A1A1F', borderColor: 'rgba(255,255,255,0.1)', color: '#fff' }}
                                        itemStyle={{ color: '#fff' }}
                                    />
                                    <Line type="monotone" dataKey="ma5" stroke="#007AFF" strokeWidth={2} dot={false} />
                                    <Line type="monotone" dataKey="ma20" stroke="#FF9500" strokeWidth={2} dot={false} />
                                </LineChart>
                            </ResponsiveContainer>
                        </div>

                        <div className="grid grid-cols-2 gap-4 mt-4">
                            {/* RSI Chart */}
                            <div className="h-32">
                                <ResponsiveContainer width="100%" height="100%">
                                    <LineChart data={chartData}>
                                        <YAxis hide domain={[0, 100]} />
                                        <Tooltip contentStyle={{ backgroundColor: '#1A1A1F', borderColor: 'rgba(255,255,255,0.1)' }} />
                                        <ReferenceLine y={30} stroke="#2ECC71" strokeDasharray="3 3" />
                                        <ReferenceLine y={70} stroke="#E74C3C" strokeDasharray="3 3" />
                                        <Line type="monotone" dataKey="rsi" stroke="#AF52DE" strokeWidth={2} dot={false} />
                                    </LineChart>
                                </ResponsiveContainer>
                            </div>
                            {/* Volume Chart */}
                            <div className="h-32">
                                <ResponsiveContainer width="100%" height="100%">
                                    <BarChart data={chartData}>
                                        <YAxis hide />
                                        <Tooltip contentStyle={{ backgroundColor: '#1A1A1F', borderColor: 'rgba(255,255,255,0.1)' }} />
                                        <Bar dataKey="volume" fill="#34C759" />
                                    </BarChart>
                                </ResponsiveContainer>
                            </div>
                        </div>
                    </div>

                    {/* Right Column: Info & Logic */}
                    <div className="space-y-6">
                        {/* Junho Safety Guards */}
                        <div className="bg-[#1A1A1F]/80 border border-white/10 rounded-xl p-4 border-l-4 border-l-[#007AFF]">
                            <h3 className="text-sm font-bold text-blue-400 mb-2 uppercase">Junho Safety Guards</h3>
                            <ul className="text-sm space-y-2">
                                <li className="flex justify-between border-b border-white/5 pb-1">
                                    <span className="text-gray-400">Base Risk</span>
                                    <span className="text-white font-mono">1.0%</span>
                                </li>
                                <li className="flex justify-between border-b border-white/5 pb-1">
                                    <span className="text-gray-400">Sector Discount</span>
                                    <span className="text-yellow-500 font-bold">Active (x0.7)</span>
                                </li>
                                <li className="flex justify-between border-b border-white/5 pb-1">
                                    <span className="text-gray-400">Max Weight</span>
                                    <span className="text-white">18% (Score 80+)</span>
                                </li>
                                <li className="flex justify-between">
                                    <span className="text-gray-400">ATR Stop</span>
                                    <span className="text-red-400 font-mono">Entry - (ATR * 2)</span>
                                </li>
                            </ul>
                        </div>

                        {/* Active Buy Logic */}
                        <div className="bg-[#1A1A1F]/80 border border-white/10 rounded-xl p-4">
                            <h3 className="text-sm font-bold text-green-400 mb-2 uppercase">Active Buy Logic</h3>
                            <div className="space-y-2">
                                <div className="bg-black/40 p-3 rounded border border-green-900/50 flex flex-col gap-1">
                                    <div className="flex justify-between items-center">
                                        <p className="text-xs font-bold text-green-500">VCP_BREAKOUT</p>
                                        <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
                                    </div>
                                    <p className="text-[10px] text-gray-400">Volatility Contraction + Vol 3x</p>
                                </div>
                                <div className="bg-black/40 p-3 rounded border border-gray-800 flex flex-col gap-1 opacity-60">
                                    <p className="text-xs font-bold text-gray-500">LATEST SIGNAL</p>
                                    <p className="text-[10px] text-gray-600 italic">
                                        {lastSignal ? `${lastSignal.stock_name}: ${lastSignal.signal_type} @ ${lastSignal.price}` : "Waiting for Signal..."}
                                    </p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default JennieLogic;
