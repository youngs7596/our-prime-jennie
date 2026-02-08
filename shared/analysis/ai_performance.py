
import logging
import pandas as pd
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from shared.db.models import LLMDecisionLedger, StockDailyPrice

logger = logging.getLogger(__name__)

# Rolling window for statistical significance
DEFAULT_LOOKBACK_DAYS = 20  # 20 trading days ~ 1 month

def fetch_ai_decisions(session, lookback_days=DEFAULT_LOOKBACK_DAYS):
    """Fetch BUY/SELL decisions from the ledger within the lookback period."""
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    stmt = select(LLMDecisionLedger).where(
        LLMDecisionLedger.final_decision.in_(['BUY', 'SELL']),
        LLMDecisionLedger.timestamp >= cutoff_date
    ).order_by(LLMDecisionLedger.timestamp.desc())

    decisions = pd.read_sql(stmt, session.connection())
    # Normalize columns to lowercase to handle DB case discrepancies
    decisions.columns = [c.lower() for c in decisions.columns]
    
    logger.info(f"   Fetched {len(decisions)} decisions from last {lookback_days} days (since {cutoff_date.date()})")
    return decisions

def fetch_price_history(session, stock_code, start_date, days=30):
    """Fetch daily price history for a stock starting from a specific date."""
    stmt = select(StockDailyPrice).where(
        StockDailyPrice.stock_code == stock_code,
        StockDailyPrice.price_date >= start_date
    ).order_by(StockDailyPrice.price_date.asc())

    prices = pd.read_sql(stmt, session.connection())
    prices.columns = [c.lower() for c in prices.columns]
    return prices

def extract_reasoning_tags(reason_text):
    """Extract key tags from LLM reasoning text."""
    if not reason_text or not isinstance(reason_text, str):
        return []
    
    tags = []
    keywords = {
        '저평가': 'Undervalued',
        '실적': 'Earnings',
        '모멘텀': 'Momentum',
        '수급': 'Market Flow',
        '기술적': 'Technical',
        '반등': 'Rebound',
        '성장': 'Growth',
        '배당': 'Dividend',
        '리스크': 'Risk',
        '고평가': 'Overvalued'
    }
    
    for kw, tag in keywords.items():
        if kw in reason_text:
            tags.append(tag)
            
    return list(set(tags))[:3]  # Limit to 3 unique tags

def fetch_score_history(session, stock_code, limit=5):
    """Fetch recent Hunter scores for a stock."""
    stmt = select(LLMDecisionLedger.hunter_score).where(
        LLMDecisionLedger.stock_code == stock_code,
        LLMDecisionLedger.final_decision.in_(['BUY', 'SELL'])
    ).order_by(LLMDecisionLedger.timestamp.desc()).limit(limit)

    # Return list of scores (oldest to newest for sparkline)
    result = [r[0] for r in session.execute(stmt).all()]
    return result[::-1] if result else []

def analyze_performance(session, lookback_days=DEFAULT_LOOKBACK_DAYS):
    """
    Main analysis logic.
    Returns a DataFrame with performance metrics for each decision.
    """
    logger.info(f"🔍 Fetching AI Decisions (lookback: {lookback_days} days)...")
    decisions = fetch_ai_decisions(session, lookback_days=lookback_days)
    
    if decisions.empty:
        logger.warning("⚠️ No AI decisions found in LLM_DECISION_LEDGER.")
        return pd.DataFrame()

    logger.info(f"📊 Analyzing {len(decisions)} decisions...")
    
    results = []
    skipped_count = 0
    
    for _, row in decisions.iterrows():
        stock_code = row['stock_code']
        decision_date = row['timestamp']
        decision_type = row['final_decision']
        
        prices = fetch_price_history(session, stock_code, decision_date.date())
        
        if prices.empty:
            # If no price data found (e.g., decision today, data not collected), 
            # still include the decision but with None returns.
            logger.debug(f"⚠️ No price data for {stock_code} on {decision_date.date()}. Returns will be None.")
            entry_price = None
        else:
            entry_price = prices.iloc[0]['close_price']
        
        # Extract tags
        llm_reason = row.get('llm_reason') or row.get('reason')
        tags = extract_reasoning_tags(llm_reason)

        # distinct score history
        score_history = fetch_score_history(session, stock_code)

        # Calculate returns for T+1, T+5, T+10, T+20
        performance = {
            'timestamp': decision_date,
            'stock_code': stock_code,
            'stock_name': row['stock_name'],
            'decision': decision_type,
            'hunter_score': row['hunter_score'],
            'market_regime': row['market_regime'],
            'entry_price': entry_price,
            'return_1d': None,
            'return_5d': None,
            'return_20d': None,
            'tags': tags,
            'score_history': score_history
        }
        
        if entry_price and entry_price > 0:
            if len(prices) > 1:
                price_1d = prices.iloc[1]['close_price']
                ret_1d = (price_1d - entry_price) / entry_price
                performance['return_1d'] = ret_1d if decision_type == 'BUY' else -ret_1d
                
            if len(prices) > 5:
                price_5d = prices.iloc[5]['close_price']
                ret_5d = (price_5d - entry_price) / entry_price
                performance['return_5d'] = ret_5d if decision_type == 'BUY' else -ret_5d

            if len(prices) > 20:
                price_20d = prices.iloc[20]['close_price']
                ret_20d = (price_20d - entry_price) / entry_price
                performance['return_20d'] = ret_20d if decision_type == 'BUY' else -ret_20d
            
        results.append(performance)
        
    return pd.DataFrame(results)
