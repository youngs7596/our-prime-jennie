# Prime Council Feedback Log

This document records the feedback provided by the Prime Council (Minji, Jennie, Junho) regarding the Technical Analysis & Chart Phase upgrade.

## 1. Minji (Strategy & Risk)
- **Core Strategy**: "Hybrid Filter" logic.
    - Use **MA Alignment** (20/60/120) for objective phase definition.
    - **Hard Block** Stage 4 (Downtrend) to stop "catching falling knives".
    - **Weight Multiplier** for Stage 2 (Uptrend) to maximize exposure to winners.
- **Exhaustion**: Combine ADX + Bollinger %B + RSI Slope.

## 2. Jennie (Data & Logic)
- **Phase Definitions**:
    - **Phase 2 (Strong Uptrend)**: Price > 20 > 60 > 120. (Score: +10)
    - **Phase 4 (Strong Downtrend)**: Price < 20 < 60 < 120. (Score: -10)
    - **Phase 3 (Distribution)**: 20MA breakdown but Long MA rising.
    - **Phase 1 (Accumulation)**: Long MA inverse but Price > 20MA (Sniper opportunity).
- **Trend Visualization**:
    - **ADX Fatigue**: ADX > 40 and falling.
    - **Parabolic SAR**: Use for clear visual reversal points.
- **Application**:
    - **Buy**: Multiplier (Phase 2 -> 1.5x, Phase 1 -> 1.1x).
    - **Sell**: Adaptive Threshold (Tighten stop in Phase 3/Exhaustion).

## 3. Junho (Implementation & Code)
- **Architecture**:
    - Create a unified `ChartPhaseResult` object.
    - Centralize logic in `shared/chart_phase/phase_engine.py` (or `chart_phase.py`).
- **Features**:
    - **Slope**: Use Normalized Slope (by ATR) for portability across price ranges.
    - **Reversal Detection**: SuperTrend flip or MA Slope sign change.
- **Integration**:
    - `QuantScorer` consumes Phase for scoring.
    - `PriceMonitor` consumes Phase for dynamic risk management.
