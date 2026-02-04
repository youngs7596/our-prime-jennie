import logging
import sys
import os
from datetime import datetime, timedelta
from sqlalchemy import text

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'services', 'buy-executor'))

from shared.db.connection import session_scope, init_engine
from shared.db.models import StockMinutePrice
from executor import BuyExecutor
from shared.position_sizing import PositionSizer

class MockConfig:
    def __init__(self, config_dict):
        self.config = config_dict
    
    def get(self, key, default=None):
        return self.config.get(key, default)
    
    def set(self, key, value):
        self.config[key] = value

    def get_int(self, key, default=0):
        val = self.config.get(key, default)
        return int(val)
        
    def get_float(self, key, default=0.0):
        val = self.config.get(key, default)
        return float(val)
        
    def get_bool(self, key, default=False):
        val = self.config.get(key, default)
        if isinstance(val, str):
            return val.lower() in ('true', '1', 'yes')
        return bool(val)

# Logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VERIFY")

def setup_mock_data(session):
    logger.info("--- Setting up Mock Data ---")
    now = datetime.now()
    
    # Clean up test data
    session.execute(text("DELETE FROM STOCK_MINUTE_PRICE WHERE stock_code IN ('TEST01', 'TEST02', 'TEST03', 'TEST04')"))
    
    insert_sql = text("""
        INSERT INTO STOCK_MINUTE_PRICE 
        (stock_code, price_time, open_price, high_price, low_price, close_price, volume, accum_volume, created_at)
        VALUES (:code, :time, :o, :h, :l, :c, :v, 0, NOW())
    """)
    
    # 1. TEST01: Momentum Case
    prices = [1000, 1000, 1000, 1010, 1020, 1030]
    volumes = [100, 100, 100, 200, 200, 200]
    
    for i in range(6):
        t = now - timedelta(minutes=(5 * (5-i)))
        session.execute(insert_sql, {
            "code": 'TEST01', "time": t, "o": prices[i], "h": prices[i]+5, "l": prices[i]-5, "c": prices[i], "v": volumes[i]
        })
        
    # 2. TEST02: Shooting Star
    t_prev = now - timedelta(minutes=5)
    t_curr = now
    
    session.execute(insert_sql, {"code": 'TEST02', "time": t_prev, "o": 990, "h": 1005, "l": 980, "c": 1000, "v": 100})
    session.execute(insert_sql, {"code": 'TEST02', "time": t_curr, "o": 1000, "h": 1050, "l": 1000, "c": 1010, "v": 200})

    # 3. TEST03: Bearish Engulfing
    session.execute(insert_sql, {"code": 'TEST03', "time": t_prev, "o": 1000, "h": 1025, "l": 995, "c": 1020, "v": 100})
    session.execute(insert_sql, {"code": 'TEST03', "time": t_curr, "o": 1025, "h": 1030, "l": 985, "c": 990, "v": 200})

    # 4. TEST04: Intraday ATR
    for i in range(21):
        t = now - timedelta(minutes=(5 * (20-i)))
        p = 1000 + (i % 2) * 10 
        session.execute(insert_sql, {
            "code": 'TEST04', "time": t, "o": p, "h": p+5, "l": p-5, "c": p, "v": 100
        })
    
    session.commit()
    logger.info("Mock Data Setup Complete")

def verify_momentum(session):
    logger.info("\n--- Verifying Intraday Momentum (TEST01) ---")
    # Simulate Scout Logic
    target_codes = ['TEST01']
    check_start_time = datetime.now() - timedelta(minutes=40)
    
    query = text(f"""
        SELECT stock_code, price_time, open_price, close_price, volume
        FROM STOCK_MINUTE_PRICE
        WHERE stock_code IN ('TEST01')
        AND price_time >= :start_time
        ORDER BY stock_code, price_time ASC
    """)
    rows = session.execute(query, {"start_time": check_start_time}).fetchall()
    
    bars = [{'time': r[1], 'open': r[2], 'close': r[3], 'volume': r[4]} for r in rows]
    
    if len(bars) < 6:
        logger.error(f"Failed: Not enough bars ({len(bars)})")
        return
        
    recent_bars = bars[-3:]
    prev_bars = bars[-6:-3]
    
    recent_vol = sum(b['volume'] for b in recent_bars) / len(recent_bars)
    prev_vol = sum(b['volume'] for b in prev_bars) / len(prev_bars)
    
    logger.info(f"Recent Vol Avg: {recent_vol}, Prev Vol Avg: {prev_vol}")
    
    if prev_vol > 0 and recent_vol >= prev_vol * 1.8:
        logger.info("✅ Volume Spike Detected")
    else:
        logger.error("❌ Volume Spike check failed")
        
    price_up = recent_bars[-1]['close'] > prev_bars[-1]['close']
    if price_up:
        logger.info("✅ Price Trend Detected")
    else:
        logger.error("❌ Price Trend check failed")

def verify_executor(session):
    logger.info("\n--- Verifying Executor Micro-Timing (TEST02, TEST03) ---")
    config = MockConfig({})
    config.set('ENABLE_MICRO_TIMING', 'true')
    
    executor = BuyExecutor(kis=None, config=config)
    
    # Test Shooting Star
    logger.info("Checking TEST02 (Shooting Star)...")
    candidates = [{'code': 'TEST02', 'name': 'TestStock2', 'llm_score': 90}]
    result = executor._validate_entry_timing(session, candidates)
    if not result['allowed'] and "Shooting Star" in result['reason']:
        logger.info(f"✅ Shooting Star correctly rejected: {result['reason']}")
    else:
        logger.error(f"❌ Shooting Star check failed: {result}")

    # Test Bearish Engulfing
    logger.info("Checking TEST03 (Bearish Engulfing)...")
    candidates = [{'code': 'TEST03', 'name': 'TestStock3', 'llm_score': 90}]
    result = executor._validate_entry_timing(session, candidates)
    if not result['allowed'] and "Bearish Engulfing" in result['reason']:
        logger.info(f"✅ Bearish Engulfing correctly rejected: {result['reason']}")
    else:
        logger.error(f"❌ Bearish Engulfing check failed: {result}")

def verify_atr(session):
    logger.info("\n--- Verifying Intraday ATR (TEST04) ---")
    ps = PositionSizer(MockConfig({}))
    atr = ps.calculate_intraday_atr(session, 'TEST04', window=20)
    
    if atr:
        logger.info(f"✅ Intraday ATR Calculated: {atr}")
        # TR calculation: 
        # range 1000-1010. High-Low=10. PrevClose diff=10.
        # Average TR should be around 10.
        if 9 <= atr <= 11:
            logger.info("✅ ATR Accuracy Confirmed")
        else:
            logger.warning(f"⚠️ ATR value {atr} is deviating from expected 10")
    else:
        logger.error("❌ Intraday ATR Returned None")

if __name__ == "__main__":
    init_engine()
    with session_scope() as session:
        setup_mock_data(session)
        verify_momentum(session)
        verify_executor(session)
        verify_atr(session)
