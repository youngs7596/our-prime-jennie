
import React from 'react';
import { motion } from 'framer-motion';

const SuperPrime: React.FC = () => {
    return (
        <div className="space-y-6">
            <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="rounded-3xl border border-raydium-purple/30 bg-raydium-darker/60 backdrop-blur-xl p-6 shadow-neon-purple"
            >
                <div className="flex items-center gap-4 mb-6">
                    <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-yellow-400 to-orange-500 flex items-center justify-center shadow-lg">
                        <span className="text-2xl">🏆</span>
                    </div>
                    <div>
                        <h2 className="text-2xl font-display font-bold text-white">
                            Super Prime Case: Legendary Pattern
                        </h2>
                        <p className="text-raydium-cyan/70">
                            Verified Historical Data (RSI ≤ 30 & Volume Spike)
                        </p>
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* Key Metrics */}
                    <div className="bg-black/40 rounded-2xl p-6 border border-white/5">
                        <h3 className="text-lg font-bold text-white mb-4">Target: Samsung Pharm (삼성제약)</h3>
                        <div className="space-y-4">
                            <div className="flex justify-between items-center">
                                <span className="text-gray-400">Signal Trigger</span>
                                <span className="text-yellow-400 font-bold">RSI 28.5 + Vol 550%</span>
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-gray-400">Expected Yield</span>
                                <span className="text-green-400 font-bold">+66.9%</span>
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-gray-400">Holding Period</span>
                                <span className="text-white font-bold">55 Days</span>
                            </div>
                        </div>
                    </div>

                    {/* Chart Placeholder */}
                    <div className="bg-black/40 rounded-2xl p-6 border border-white/5 flex items-center justify-center h-64">
                        <p className="text-gray-500">Charts & Analysis Visualization Loading...</p>
                        {/* Future: Integrate Recharts or similar for the specific pattern graph */}
                    </div>
                </div>
            </motion.div>
        </div>
    );
};

export default SuperPrime;
