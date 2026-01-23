# Council Consultation: Sector/Theme Momentum Scoring

## Context
The User (Owner) observed that stock movements are often highly correlated within sectors or themes (e.g., recent Hyundai Motor Group rally).
They proposed a new feature for the **Scout (Buy Scanner)**:
> "Identify currently hot sectors/themes and give bonus points (Scoring Boost) to stocks belonging to those sectors."

## Current System
- **Scout**: Scores stocks based on Technicals (MACD, RSI, Bollinger), Fundamental (PER/PBR), and LLM Sentiment (News).
- **Missing**: No explicit "Sector Strength" or "Peer Group Momentum" factor. We judge each stock in isolation.

## Proposal for Review
**"Dynamic Sector Momentum Boosting"**
1. **Pre-calculation**: Before individual stock scoring, calculate "Sector Index" performance for all 20+ sectors (e.g., Auto, Semi, Bio, Defense).
   - Metric: Avg 3-day return of top 5 market-cap stocks in the sector.
2. **Scoring Rule**:
   - If Sector Momentum > Threshold (e.g., +3% in 3 days): Apply `+10` point boost to all candidates in that sector.
   - If Sector Momentum < Negative Threshold: Apply `-10` penalty (avoid catching falling knives in a bad sector).

## Questions for the Council
1. **Minji (Strategy)**: Does this align with our "Conservative/Rebound" philosophy? Is chasing hot sectors risky (buying at the top)? How do we define "Hot" without being late?
2. **Junho (Architect)**: How should we efficiently implement "Sector Grouping"? Do we need a static mapping (e.g., KSIC codes) or dynamic grouping? Redis caching strategy for sector scores?
3. **Jennie (Persona)**: Will this make our trading style too aggressive? How do we balance "Theme Chasing" with "Value Investing"?

## Goal
Decide whether to implement **Sector Momentum Scoring** in `services/buy-scanner` and define the technical approach.
