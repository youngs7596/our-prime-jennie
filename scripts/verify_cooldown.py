
import sys
import os
import logging
from datetime import datetime, timedelta, timezone

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.db.connection import session_scope, ensure_engine_initialized
from shared.db import repository as repo
from shared.db.models import TradeLog

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_cooldown_logic():
    ensure_engine_initialized()
    logger.info("=== Verifying Cooldown Logic ===")
    
    stock_code = "TEST999"
    stock_name = "CooldownTest"
    
    with session_scope() as session:
        # Cleanup
        session.query(TradeLog).filter(TradeLog.stock_code == stock_code).delete()
        
        # Case 1: Sell 23 hours ago
        logger.info("Test Case 1: Sell 23 hours ago")
        sell_time_23h = datetime.now(timezone.utc) - timedelta(hours=23)
        trade_log_23h = TradeLog(
            stock_code=stock_code,
            trade_type="SELL",
            quantity=10,
            price=10000,
            trade_timestamp=sell_time_23h,
            reason="MANUAL_SELL_TEST"
        )
        session.add(trade_log_23h)
        session.flush() # Ensure it's visible? session_scope commits at end, but for same transaction it should be visible.
        
        # Check 24h cooldown -> Should be TRUE
        is_active_24h = repo.was_traded_recently(session, stock_code, hours=24.0, trade_type='SELL')
        logger.info(f"Checking 24h cooldown: {is_active_24h} (Expected: True)")
        
        if not is_active_24h:
            logger.error("❌ FAILED: 23 hours ago should trigger 24h cooldown")
        
        # Check 1h cooldown -> Should be FALSE
        is_active_1h = repo.was_traded_recently(session, stock_code, hours=1.0, trade_type='SELL')
        logger.info(f"Checking 1h cooldown: {is_active_1h} (Expected: False)")
        
        if is_active_1h:
            logger.error("❌ FAILED: 23 hours ago should NOT trigger 1h cooldown")

        # Cleanup
        session.query(TradeLog).filter(TradeLog.stock_code == stock_code).delete()
        
        # Case 2: Sell 25 hours ago
        logger.info("Test Case 2: Sell 25 hours ago")
        sell_time_25h = datetime.now(timezone.utc) - timedelta(hours=25)
        trade_log_25h = TradeLog(
            stock_code=stock_code,
            trade_type="SELL",
            quantity=10,
            price=10000,
            trade_timestamp=sell_time_25h,
            reason="MANUAL_SELL_TEST"
        )
        session.add(trade_log_25h)
        session.flush()
        
        # Check 24h cooldown -> Should be FALSE
        is_active_25h = repo.was_traded_recently(session, stock_code, hours=24.0, trade_type='SELL')
        logger.info(f"Checking 24h cooldown: {is_active_25h} (Expected: False)")
        
        if is_active_25h:
             logger.error("❌ FAILED: 25 hours ago should NOT trigger 24h cooldown")
             
        # Cleanup
        session.query(TradeLog).filter(TradeLog.stock_code == stock_code).delete()
        
        if is_active_24h and not is_active_1h and not is_active_25h:
            logger.info("✅ ALL TESTS PASSED")
        else:
            logger.error("❌ SOME TESTS FAILED")

if __name__ == "__main__":
    verify_cooldown_logic()
