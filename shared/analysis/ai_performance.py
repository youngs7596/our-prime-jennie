
import logging
import pandas as pd
from datetime import datetime, timedelta
from shared.db.models import LLMDecisionLedger, StockDailyPrice

logger = logging.getLogger(__name__)

# Rolling window for statistical significance
DEFAULT_LOOKBACK_DAYS = 20  # 20 trading days ~ 1 month

def fetch_ai_decisions(session, lookback_days=DEFAULT_LOOKBACK_DAYS):
    """Fetch BUY/SELL decisions from the ledger within the lookback period."""
    cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)
    
    query = session.query(LLMDecisionLedger).filter(
        LLMDecisionLedger.final_decision.in_(['BUY', 'SELL']),
        LLMDecisionLedger.timestamp >= cutoff_date
    ).order_by(LLMDecisionLedger.timestamp.desc())
    
    decisions = pd.read_sql(query.statement, session.bind)
    # Normalize columns to lowercase to handle DB case discrepancies
    decisions.columns = [c.lower() for c in decisions.columns]
    
    logger.info(f"   Fetched {len(decisions)} decisions from last {lookback_days} days (since {cutoff_date.date()})")
    return decisions

def fetch_price_history(session, stock_code, start_date, days=30):
    """Fetch daily price history for a stock starting from a specific date."""
    query = session.query(StockDailyPrice).filter(
        StockDailyPrice.stock_code == stock_code,
        StockDailyPrice.price_date >= start_date
    ).order_by(StockDailyPrice.price_date.asc())
    
    prices = pd.read_sql(query.statement, session.bind)
    prices.columns = [c.lower() for c in prices.columns]
    return prices

def analyze_performance(session):
    """
    Main analysis logic.
    Returns a DataFrame with performance metrics for each decision.
    """
    logger.info("🔍 Fetching AI Decisions...")
    decisions = fetch_ai_decisions(session)
    
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
            skipped_count += 1
            continue
            
        entry_price = prices.iloc[0]['close_price']
        
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
            'return_20d': None
        }
        
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
        
    if skipped_count > 0:
        logger.warning(f"⚠️ Skipped {skipped_count} decisions due to missing price data (possibly recent decisions).")
        
    return pd.DataFrame(results)
