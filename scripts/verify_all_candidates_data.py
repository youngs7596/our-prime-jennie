import os
import sys
import logging

# Set up project root
PROJECT_ROOT = '/app'
SCOUT_JOB_DIR = '/app/services/scout-job'
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if SCOUT_JOB_DIR not in sys.path:
    sys.path.insert(0, SCOUT_JOB_DIR)

from shared.db.connection import session_scope, ensure_engine_initialized
import shared.database as database

# Import from the CURRENT directory (which will be /app/services/scout-job)
import scout_universe 

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_candidates():
    ensure_engine_initialized()
    with session_scope() as session:
        candidate_stocks = {}
        
        # A: 동적 우량주
        for stock in scout_universe.get_dynamic_blue_chips(limit=200):
            candidate_stocks[stock['code']] = {'name': stock['name']}
        
        # E: 섹터
        sector_analysis = scout_universe.analyze_sector_momentum(None, session)
        hot_sector_stocks = scout_universe.get_hot_sector_stocks(sector_analysis, top_n=30)
        for stock in hot_sector_stocks:
            candidate_stocks[stock['code']] = {'name': stock['name']}
            
        # B: 정적
        for stock in scout_universe.BLUE_CHIP_STOCKS:
            candidate_stocks[stock['code']] = {'name': stock['name']}
            
        # D: 모멘텀
        momentum_stocks = scout_universe.get_momentum_stocks(None, session, top_n=30)
        for stock in momentum_stocks:
            candidate_stocks[stock['code']] = {'name': stock['name']}
            
        print(f"Total Unique Candidates: {len(candidate_stocks)}")
        
        missing_data_stocks = []
        for code, info in candidate_stocks.items():
            if code == '0001': continue
            df = database.get_daily_prices(session, code, limit=30)
            if df.empty or len(df) < 30:
                missing_data_stocks.append((code, info['name'], len(df)))
        
        print(f"\nStocks with < 30 days of data: {len(missing_data_stocks)}")
        for code, name, count in missing_data_stocks:
            print(f"- {code} ({name}): {count} days")

if __name__ == "__main__":
    verify_candidates()
