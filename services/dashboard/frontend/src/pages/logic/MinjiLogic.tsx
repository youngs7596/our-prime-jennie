import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';

const MinjiLogic: React.FC = () => {
    // Styles from the HTML file, adapted for Styled-Components or inline styles
    // Since we are in a React environment with Tailwind available, we can mix approaches.
    // However, to preserve the exact look of Minji's HTML, we'll use a style block or scoped styles.

    // For simplicity and fidelity, we will inject the CSS and use the HTML structure.

    return (
        <div className="minji-visualization-container" style={{
            fontFamily: "'JetBrains Mono', 'Noto Sans KR', monospace",
            background: "linear-gradient(135deg, #0D0D0F 0%, #0a0a0c 50%, #1A1A1F 100%)",
            color: "#FFFFFF",
            minHeight: "100%",
            borderRadius: "16px",
            padding: "20px",
            overflow: "hidden"
        }}>
            <style dangerouslySetInnerHTML={{
                __html: `
                :root {
                    --bg-deep: #0D0D0F;
                    --bg-surface: #1A1A1F;
                    --bg-elevated: #242429;
                    --neon-blue: #007AFF;
                    --neon-orange: #FF9500;
                    --neon-green: #2ECC71;
                    --neon-red: #E74C3C;
                    --neon-purple: #9B59B6;
                    --neon-cyan: #5AC8FA;
                    --neon-yellow: #F1C40F;
                    --text-primary: #FFFFFF;
                    --text-secondary: #8E8E93;
                    --text-muted: #636366;
                }

                .minji-header {
                    text-align: center;
                    margin-bottom: 40px;
                }

                .minji-title {
                    font-size: 2.5rem;
                    font-weight: 900;
                    margin-bottom: 10px;
                    background: linear-gradient(135deg, var(--neon-cyan), var(--neon-blue), var(--neon-purple));
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    text-shadow: 0 0 30px rgba(90, 200, 250, 0.3);
                }

                .flow-container {
                    background: linear-gradient(180deg, rgba(26, 26, 31, 0.8), rgba(13, 13, 15, 0.9));
                    border: 1px solid rgba(90, 200, 250, 0.1);
                    border-radius: 20px;
                    padding: 30px;
                    margin-bottom: 40px;
                    position: relative;
                }

                .flow-stages {
                    display: flex;
                    justify-content: space-between;
                    gap: 20px;
                    flex-wrap: wrap;
                }

                .flow-stage {
                    flex: 1;
                    min-width: 250px;
                    background: rgba(36, 36, 41, 0.4);
                    border-radius: 12px;
                    padding: 15px;
                    border: 1px solid rgba(255,255,255,0.05);
                }

                .stage-title {
                    font-size: 1rem;
                    font-weight: 600;
                    margin-bottom: 15px;
                    display: flex;
                    align-items: center;
                    gap: 10px;
                }
                
                .stage-title.scout { color: var(--neon-cyan); }
                .stage-title.buy { color: var(--neon-green); }
                .stage-title.guard { color: var(--neon-yellow); }
                .stage-title.sell { color: var(--neon-red); }

                .flow-item {
                    background: rgba(0,0,0,0.3);
                    padding: 10px;
                    border-radius: 8px;
                    margin-bottom: 8px;
                    border-left: 2px solid;
                    font-size: 0.8rem;
                    color: var(--text-secondary);
                }

                .flow-item.scout { border-color: var(--neon-cyan); }
                .flow-item.buy { border-color: var(--neon-green); }
                .flow-item.guard { border-color: var(--neon-yellow); }
                .flow-item.sell { border-color: var(--neon-red); }

                .guard-wall {
                    border: 1px solid var(--neon-yellow);
                    padding: 15px;
                    border-radius: 12px;
                    margin-top: 15px;
                    background: rgba(241, 196, 15, 0.05);
                    position: relative;
                }
                
                .guard-wall::before {
                    content: '🛡️ JUNHO SAFETY GUARDS';
                    position: absolute;
                    top: -10px;
                    left: 20px;
                    background: #1A1A1F;
                    padding: 0 8px;
                    font-size: 0.7rem;
                    color: var(--neon-yellow);
                }

                /* Dashboard Section */
                .dashboard-container {
                    background: linear-gradient(180deg, rgba(26, 26, 31, 0.95), rgba(13, 13, 15, 0.98));
                    border: 1px solid rgba(90, 200, 250, 0.15);
                    border-radius: 20px;
                    overflow: hidden;
                }

                .dashboard-header {
                    padding: 20px;
                    border-bottom: 1px solid rgba(255,255,255,0.05);
                    display: flex;
                    justify-content: space-between;
                }

                .stock-price {
                    font-size: 1.5rem;
                    color: var(--neon-green);
                    font-weight: 700;
                    font-family: 'Orbitron', monospace;
                }

                /* SVG Charts */
                .chart-area {
                    padding: 20px;
                    background: rgba(0,0,0,0.2);
                    height: 300px;
                    position: relative;
                }
                
                /* Animations */
                @keyframes pulse {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.5; }
                }
            `}} />

            <div className="minji-header">
                <h1 className="minji-title">Quantum Jump</h1>
                <div style={{ color: "var(--neon-green)", letterSpacing: "0.2em" }}>PRIME JENNIE TRADING SYSTEM</div>
                <div style={{ marginTop: "10px", fontSize: "0.8rem", color: "var(--text-muted)" }}>Visualized by Minji</div>
            </div>

            {/* Part 1: Logic Flow */}
            <div className="flow-container">
                <h2 style={{ color: "var(--text-primary)", marginBottom: "20px", fontFamily: "'Orbitron'", fontSize: "1.2rem" }}>
                    Workflow Pipeline
                </h2>
                <div className="flow-stages">
                    {/* Scout */}
                    <motion.div className="flow-stage" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
                        <div className="stage-title scout"><span>🔍</span> SCOUT</div>
                        <div className="flow-item scout">
                            <strong>Hunter AI</strong><br />News/Sentiment Scoring
                        </div>
                        <div className="flow-item scout">
                            <strong>Judge AI</strong><br />Final Trade Approval
                        </div>
                        <div className="flow-item scout" style={{ background: "rgba(90,200,250,0.1)" }}>
                            Target: Score &ge; 70
                        </div>
                    </motion.div>

                    {/* Buy */}
                    <motion.div className="flow-stage" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
                        <div className="stage-title buy"><span>📡</span> BUY SCANNER</div>
                        <div className="flow-item buy">
                            <strong>Pre-Entry Gates</strong><br />
                            No-Trade Window (09:00-09:30)<br />
                            VWAP Disparity &lt; 2%
                        </div>
                        <div className="flow-item buy">
                            <strong>Triggers</strong><br />
                            <span style={{ color: "var(--neon-green)" }}>Golden Cross</span><br />
                            <span style={{ color: "var(--neon-cyan)" }}>BB Lower Touch</span><br />
                            <span style={{ color: "var(--neon-purple)" }}>RSI Rebound</span>
                        </div>
                    </motion.div>

                    {/* Guard & Size */}
                    <motion.div className="flow-stage" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
                        <div className="stage-title guard"><span>🛡️</span> SIZING & RISK</div>
                        <div className="guard-wall">
                            <div className="flow-item guard">
                                <strong>Risk Per Trade</strong>: 1.0% Equity
                            </div>
                            <div className="flow-item guard">
                                <strong>Sector Discount</strong>: 0.7x
                            </div>
                            <div className="flow-item guard">
                                <strong>Portfolio Heat</strong>: Max 5%
                            </div>
                            <div className="flow-item guard" style={{ border: "none", background: "var(--neon-yellow)", color: "black", fontWeight: "bold", textAlign: "center" }}>
                                CAP: 12% ~ 18%
                            </div>
                        </div>
                    </motion.div>

                    {/* Sell */}
                    <motion.div className="flow-stage" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 }}>
                        <div className="stage-title sell"><span>💰</span> SELL LOGIC</div>
                        <div className="flow-item sell">
                            <strong>Profit Lock</strong><br />
                            L1: 1.5~3% &rarr; BE<br />
                            L2: 3~5% &rarr; +1%
                        </div>
                        <div className="flow-item sell">
                            <strong>Trailing Stop</strong><br />
                            -3.5% from High
                        </div>
                        <div className="flow-item sell">
                            <strong>Stop Loss</strong><br />
                            ATR (2.0) or -6% Hard
                        </div>
                    </motion.div>
                </div>
            </div>

            {/* Part 2: Dashboard Mock */}
            <div className="dashboard-container">
                <div className="dashboard-header">
                    <div>
                        <div style={{ fontFamily: "'Orbitron'", fontSize: "1.2rem" }}>TECH PRIME</div>
                        <div style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>005930.KS</div>
                    </div>
                    <div>
                        <div className="stock-price">72,500</div>
                        <div style={{ color: "var(--neon-green)", textAlign: "right" }}>+2.3%</div>
                    </div>
                </div>

                <div className="chart-area">
                    {/* Using SVG for a lightweight static chart mock as per Minji's HTML design */}
                    <svg width="100%" height="100%" viewBox="0 0 800 300" preserveAspectRatio="none">
                        {/* Grid */}
                        <line x1="0" y1="50" x2="800" y2="50" stroke="rgba(255,255,255,0.05)" />
                        <line x1="0" y1="150" x2="800" y2="150" stroke="rgba(255,255,255,0.05)" />
                        <line x1="0" y1="250" x2="800" y2="250" stroke="rgba(255,255,255,0.05)" />

                        {/* MA Lines */}
                        <path d="M0,200 Q200,220 400,150 T800,50" fill="none" stroke="var(--neon-blue)" strokeWidth="2" />
                        <path d="M0,220 Q200,240 400,180 T800,100" fill="none" stroke="var(--neon-orange)" strokeWidth="2" />

                        {/* Candles (Simplified) */}
                        {[...Array(20)].map((_, i) => {
                            const x = i * 40 + 20;
                            const h = Math.random() * 60 + 20;
                            const y = 150 + Math.sin(i / 3) * 50 - h / 2;
                            const color = Math.random() > 0.4 ? "var(--neon-red)" : "var(--neon-blue)";
                            return (
                                <g key={i}>
                                    <line x1={x} y1={y - 10} x2={x} y2={y + h + 10} stroke={color} strokeWidth="1" />
                                    <rect x={x - 5} y={y} width={10} height={h} fill={color} />
                                </g>
                            )
                        })}

                        {/* Signal Markers */}
                        <g transform="translate(350, 200)">
                            <circle cx="0" cy="0" r="8" fill="var(--neon-green)" style={{ filter: "drop-shadow(0 0 10px var(--neon-green))" }} />
                            <text x="0" y="20" fill="var(--neon-green)" textAnchor="middle" fontSize="10">GC</text>
                        </g>

                        <g transform="translate(580, 160)">
                            <rect x="-6" y="-6" width="12" height="12" fill="var(--neon-cyan)" transform="rotate(45)" style={{ filter: "drop-shadow(0 0 10px var(--neon-cyan))" }} />
                            <text x="0" y="25" fill="var(--neon-cyan)" textAnchor="middle" fontSize="10">RSI</text>
                        </g>
                    </svg>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "10px", padding: "20px" }}>
                    <div className="sub-panel" style={{ background: "rgba(0,0,0,0.3)", padding: "10px", borderRadius: "8px" }}>
                        <div style={{ fontSize: "0.7rem", color: "var(--neon-purple)", marginBottom: "5px" }}>RSI (14)</div>
                        <div style={{ height: "50px", background: "rgba(155, 89, 182, 0.1)", position: "relative" }}>
                            <div style={{ position: "absolute", top: "70%", left: 0, right: 0, borderTop: "1px dashed var(--neon-purple)" }}></div>
                        </div>
                    </div>
                    <div className="sub-panel" style={{ background: "rgba(0,0,0,0.3)", padding: "10px", borderRadius: "8px" }}>
                        <div style={{ fontSize: "0.7rem", color: "var(--neon-blue)", marginBottom: "5px" }}>NET FLOW</div>
                        <div style={{ height: "50px", display: "flex", alignItems: "flex-end", gap: "2px" }}>
                            {[...Array(10)].map((_, i) => (
                                <div key={i} style={{ flex: 1, height: `${Math.random() * 100}%`, background: i % 2 === 0 ? "var(--neon-blue)" : "var(--neon-orange)" }}></div>
                            ))}
                        </div>
                    </div>
                    <div className="sub-panel" style={{ background: "rgba(0,0,0,0.3)", padding: "10px", borderRadius: "8px" }}>
                        <div style={{ fontSize: "0.7rem", color: "var(--neon-green)", marginBottom: "5px" }}>STATUS</div>
                        <div style={{ fontSize: "0.8rem", color: "var(--text-primary)" }}>Active Monitoring</div>
                        <div style={{ fontSize: "0.7rem", color: "var(--neon-yellow)" }}>Heat: 3.2% / 5.0%</div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default MinjiLogic;
