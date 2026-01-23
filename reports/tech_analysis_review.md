# Prime Council Consultation Request: Technical Analysis & Chart Phase

**Instructions**:
Copy the text below the separator and paste it directly into your chat with **Web Version Jennie (Gemini Advanced)**, **Minji (Claude Opus)**, or **Junho (GPT-4/5)**.

---
**Subject**: Enhancing "Chart Phase" and "Trend Visualization" Logic

**Context**:
We are currently operating an automated trading system (`Scout` & `PriceMonitor`) that uses various technical indicators.
The User has requested an upgrade: **"Beyond simple conditions (e.g., A > B), can we identify 'where we are on the chart' (e.g., Knee vs. Shoulder, Rising vs. Falling Trend)?"**

Currently, our logic is partially implemented but fragmented. We need your advice on how to unify this into a robust "Chart Phase Score" or "Trend Status".

**Current Implementation**:

1.  **Sell Logic (`PriceMonitor`)**:
    *   **Death Cross**: 5-day MA crossing below 20-day MA.
    *   **MACD Divergence**: Detects when price makes a new high but MACD does not (Bearish Divergence).
    *   **Trailing Stop**: High-watermark based exit.
    *   *Verdict*: Good at catching "falling" knives, but reactive.

2.  **Buy Logic (`QuantScorer`)**:
    *   **Momentum Score**: Calculates 6-month and 1-month returns. If positive, it adds points.
    *   **Golden Cross**: Analyzed in reports but treated as a simple binary or simple score in the scorer.
    *   **RSI**: Checks for oversold (<30) for "Sniper" strategy.
    *   *Verdict*: We buy "strong" stocks (high score), but we don't explicitly distinguish "Rising early stage" from "Rising late stage (overextended)".

**Key Code Snippets (Current)**:

```python
# shared/hybrid_scoring/quant_scorer.py (Simplified)
def calculate_momentum_score(self, df):
    # Simple Return Calculation
    stock_return = (current_price / price_6m_ago - 1) * 100
    if stock_return > 0:
        score += proportional_score(stock_return)
    # Checks consistency (months with >0 return)
```

```python
# services/price-monitor/monitor.py
def _check_sell_signal(self):
    # MACD Divergence Check
    if macd_bearish:
        tighten_stops()
    
    # Death Cross Check
    if check_death_cross(df):
        return Signal("Death Cross")
```

**My Questions to You (The Council)**:

1.  **Phase Identification**:
    *   How can we programmably detect **"Chart Phases"** (e.g., Accumulation, Uptrend, Distribution, Downtrend) using our existing 1-year daily OHLCV data?
    *   Should we implement **"Stan Weinstein's Stage Analysis"** or a simpler **"Moving Average Alignment (e.g., 20 > 60 > 120)"** score?

2.  **Trend Visualization for Bot**:
    *   The user asked: *"Are we passing a peak? Is the curve bending?"*
    *   Besides MACD Divergence, what is the best low-lag indicator to detect **"Trend Exhaustion"** (Top) vs **"Trend Reversal"** (Bottom) for a Python bot? (e.g., ADX? Parabolic SAR? Bollinger Band Width?)

3.  **Action Plan**:
    *   If we add a `ChartPhase` module, should this be a "hard filter" (Don't buy in Stage 4) or a "Weight Multiplier" (Stage 2 = 1.2x score)?

**Goal**:
Transform our logic from "Point-in-Time Conditions" to "Context-Aware Trend Analysis".
