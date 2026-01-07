#!/usr/bin/env python3
# scripts/apply_optimized_params.py
"""
Optimized Parameters Applier
----------------------------
Applies the parameters found via auto_optimize_backtest_gpt_v2.py (Test Set Verified)
to the live database configuration.
"""
import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.db.connection import session_scope, ensure_engine_initialized, get_engine
from shared.config import ConfigManager
from dotenv import load_dotenv

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(APP_ROOT, ".env"))

# secrets.json 경로 설정
secrets_path = os.path.join(APP_ROOT, "secrets.json")
if os.path.exists(secrets_path):
    os.environ.setdefault("SECRETS_FILE", secrets_path)

# 로그 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ParamApplier")

# 최적화된 파라미터 (2026-01-07 Test Set Verified)
# Return: +8.35% / Month: +3.35% / MDD: -4.29%
OPTIMIZED_PARAMS = {
    # 진입 (Entry)
    "BUY_RSI_OVERSOLD_THRESHOLD": 35,         # Aggressive Entry
    "BUY_BB_BUFFER_PCT": 1.5,                 # BB Lower + 1.5%
    "BUY_BREAKOUT_BUFFER_PCT": 0.8,           # Resistance + 0.8%
    "MIN_LLM_SCORE": 70,                      # Optimization Goal
    
    # 자금 관리 (Capital)
    "MAX_POSITION_VALUE_PCT": 15.0,           # Max allocation per stock
    "MAX_SECTOR_PCT": 35.0,                   # Max allocation per sector
    "CASH_KEEP_PCT": 3.0,                     # Cash buffer
    "MAX_BUY_COUNT_PER_DAY": 3,               # Daily buy limit
    
    # 청산 (Exit)
    "PROFIT_TARGET_FULL": 6.0,                # +6% Target Profit
    "SELL_STOP_LOSS_PCT": 5.0,                # -5% Stop Loss (Monitor handles sign)
    "ATR_MULTIPLIER_INITIAL_STOP": 1.6,       # ATR Trailing multiplier
    "TRAILING_TAKE_PROFIT_ATR_MULT": 1.6,     # Align with ATR Multiplier
    "MAX_HOLDING_DAYS": 35,                   # Time Exit
    
    # RSI 분할 매도
    "RSI_THRESHOLD_1": 68.0,
    "RSI_THRESHOLD_2": 75.0,
    "RSI_THRESHOLD_3": 80.0,
}

def apply_params():
    logger.info("🔪 Applying optimized parameters to LIVE database...")
    
    # DB 초기화 및 연결
    try:
        ensure_engine_initialized()
        engine = get_engine()
        logger.info("✅ DB Engine initialized.")
    except Exception as e:
        logger.error(f"❌ DB initialization failed: {e}")
        return

    config = ConfigManager(db_conn=engine)
    
    updated_count = 0
    for key, value in OPTIMIZED_PARAMS.items():
        try:
            # 기존 값 조회 (로그용)
            old_val = config.get(key)
            
            # DB에 저장 (persist_to_db=True triggers DB upsert)
            config.set(key, value, persist_to_db=True)
            
            logger.info(f"✅ Set {key}: {old_val} -> {value}")
            updated_count += 1
        except Exception as e:
            logger.error(f"❌ Failed to set {key}: {e}")

    logger.info(f"✨ Finished. Updated {updated_count} parameters.")
    logger.info("⚠️ Please restart services (buy-scanner, buy-executor, price-monitor) to take effect.")

if __name__ == "__main__":
    apply_params()
