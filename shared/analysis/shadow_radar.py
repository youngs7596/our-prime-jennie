
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func

from shared.db.models import ShadowRadarLog, StockDailyPrice

logger = logging.getLogger(__name__)

def analyze_shadow_performance(session: Session, lookback_days: int = 5, regret_threshold: float = 0.05) -> Dict:
    """
    Analyzes the performance of rejected stocks (Shadow Radar) to identify missed opportunities.
    
    Note: Shadow Radar uses a shorter lookback (5 days) than the main Performance Analysis (20 days)
    because we want to catch "fresh" regrets while the market context is still similar.
    Too long of a lookback would mix different market regimes.
    
    Args:
        session: DB Session
        lookback_days: How far back to look for rejections (default: 5 days)
        regret_threshold: Return threshold to consider a rejection as a "missed opportunity" (default: 5%)
        
    Returns:
        Dict containing:
        - regret_count: Number of missed opportunities
        - good_rejection_count: Number of correct rejections
        - regrets: List of details for missed stocks
        - validations: List of details for correct rejections
    """
    logger.info(f"📡 [Shadow Radar] Analyzing rejections from last {lookback_days} days...")
    
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    
    # 1. Fetch recent rejections
    rejections = session.query(ShadowRadarLog).filter(
        ShadowRadarLog.timestamp >= cutoff_date
    ).order_by(ShadowRadarLog.timestamp.desc()).all()
    
    if not rejections:
        logger.info("   No rejections found in the lookback period.")
        return {"regret_count": 0, "good_rejection_count": 0, "regrets": [], "validations": []}
        
    regrets = []
    validations = []
    
    # Group by stock to avoid duplicate processing (take the earliest rejection in period if multiple)
    # Actually, we might want to check each rejection instance. Let's keep it simple.
    
    processed_codes = set()
    
    for log in rejections:
        code = log.stock_code
        if code in processed_codes:
            continue
            
        processed_codes.add(code)
        
        # 2. Get price at rejection time (approximate to nearest day)
        rejection_date = log.timestamp.date()
        
        # Fetch prices from rejection date onwards
        prices = session.query(StockDailyPrice).filter(
            StockDailyPrice.stock_code == code,
            StockDailyPrice.price_date >= rejection_date
        ).order_by(StockDailyPrice.price_date.asc()).all()
        
        if not prices:
            continue
            
        initial_price = prices[0].close_price
        max_price = max(p.high_price for p in prices)
        current_price = prices[-1].close_price
        
        max_return = (max_price - initial_price) / initial_price
        current_return = (current_price - initial_price) / initial_price
        
        # 3. Classify
        item = {
            'code': code,
            'name': log.stock_name,
            'rejected_at': log.timestamp.strftime('%Y-%m-%d'),
            'reason': log.rejection_reason,
            'initial_price': initial_price,
            'max_return': max_return * 100,
            'current_return': current_return * 100
        }
        
        # Regret criteria: rose significantly after rejection
        if max_return >= regret_threshold:
            regrets.append(item)
        # Validation criteria: fell or stayed flat
        elif current_return <= 0:
            validations.append(item)
            
    logger.info(f"   Done. Found {len(regrets)} regrets and {len(validations)} correct rejections.")
    
    return {
        "regret_count": len(regrets),
        "good_rejection_count": len(validations),
        "regrets": sorted(regrets, key=lambda x: x['max_return'], reverse=True),
        "validations": sorted(validations, key=lambda x: x['current_return'])
    }
