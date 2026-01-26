
import os
import sys
import logging
from sqlalchemy import select, and_

# Add project root to path
sys.path.append(os.getcwd())

from shared.db.connection import init_engine, session_scope
from shared.db import models

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def cleanup_mock_data():
    # Force Env Vars for Connection (Override defaults)
    # Based on env-vars-wsl.yaml
    if "MARIADB_PORT" not in os.environ:
        os.environ["MARIADB_PORT"] = "3307" # Default to 3307 for WSL/Local
    
    # TRADING_MODE is handled by models.py import. 
    # To check both, we might need to subprocess or just check REAL (Request priority).
    # Checking REAL table.
    os.environ["TRADING_MODE"] = "REAL"
    
    print(f"Connecting to MariaDB at {os.environ.get('MARIADB_HOST', 'localhost')}:{os.environ['MARIADB_PORT']} (Mode: {os.environ['TRADING_MODE']})")

    # Initialize DB (Dispose first to ensure new config is used)
    from shared.db.connection import dispose_engine
    dispose_engine()
    init_engine()
    
    with session_scope() as session:
        # 1. Check ActivePortfolio
        print("--- Checking ActivePortfolio (REAL) ---")
        # List ALL Active Portfolio Items
        stmt = select(models.ActivePortfolio)
        portfolios = session.execute(stmt).scalars().all()
        
        print(f"Total Active Portfolio Items: {len(portfolios)}")
        target_found = False
        
        for p in portfolios:
            print(f" - [{p.stock_code}] {p.stock_name}: Qty={p.quantity}, AvgPrice={p.average_buy_price}")
            if p.stock_code == '005930' or 'Samsung' in (p.stock_name or "") or '삼성전자' in (p.stock_name or ""):
                print("   !!! FOUND TARGET !!!")
                target_found = True
                if p.quantity == 10:
                    print(f"   -> MATCHES MOCK PROFILE (Qty=10). Deleting...")
                    session.delete(p)
                    deleted_portfolio_count += 1
                else:
                    print(f"   -> Quantity mismatch (Expected 10, got {p.quantity}). User input needed?")

        # 2. Check TradeLog
        print("\n--- Checking TradeLog ---")
        # Look for recent logs for 005930
        stmt = select(models.TradeLog).where(
            models.TradeLog.stock_code == '005930'
        ).order_by(models.TradeLog.trade_timestamp.desc()).limit(10)
        
        logs = session.execute(stmt).scalars().all()
        
        deleted_log_count = 0
        if not logs:
            print("No TradeLogs found for 005930.")
        else:
            for log in logs:
                print(f"Found TradeLog: ID={log.log_id}, Type={log.trade_type}, Qty={log.quantity}, Price={log.price}, Time={log.trade_timestamp}")
                # Assuming the mock trade happened recently and has quantity 10
                # We can also check specific timestamp or just delete if it looks like the mock one.
                # User asked to remove it if found.
                if log.quantity == 10:
                     print("-> Deleting this log (Matches Mock Quantity 10)")
                     session.delete(log)
                     deleted_log_count += 1
                else:
                     print("-> SKIPPING (Does not match quantity 10)")

        # End of Real Check
        print("\n--- Finished Checking REAL ---")

    # Check MOCK Table using Raw SQL (Bypassing ORM mapping issues)
    print("\n\n=== Checking ACTIVE_PORTFOLIO_MOCK (Raw SQL) ===")
    from sqlalchemy import text
    
    with session_scope() as session:
        try:
            # Check if table exists and has data
            result = session.execute(text("SELECT STOCK_CODE, STOCK_NAME, QUANTITY FROM ACTIVE_PORTFOLIO_MOCK"))
            # Use mappings() for dict-like access or fetchall for tuples
            # We'll use fetchall and index access as it's robust
            rows = result.fetchall()
            
            print(f"Total MOCK Portfolio Items: {len(rows)}")
            for row in rows:
                code = row[0]
                name = row[1]
                qty = row[2]
                print(f" - [{code}] {name}: Qty={qty}")
                
                if code == '005930':
                    print("   !!! FOUND SAMSUNG IN MOCK TABLE !!!")
                    print("   -> Deleting from ACTIVE_PORTFOLIO_MOCK...")
                    session.execute(text("DELETE FROM ACTIVE_PORTFOLIO_MOCK WHERE STOCK_CODE = '005930'"))
                    print("   -> Deleted.")

            # Check TRADELOG_MOCK
            print("\n=== Checking TRADELOG_MOCK (Raw SQL) ===")
            result = session.execute(text("SELECT LOG_ID, STOCK_CODE, QUANTITY, TRADE_TYPE FROM TRADELOG_MOCK ORDER BY LOG_ID DESC LIMIT 10"))
            rows = result.fetchall()
            print(f"Recent MOCK Trade Logs: {len(rows)}")
            
            for row in rows:
                log_id = row[0]
                code = row[1]
                qty = row[2]
                trade_type = row[3]
                print(f" - ID={log_id}, Code={code}, Qty={qty}, Type={trade_type}")
                
                if code == '005930' and qty == 10:
                    print(f"   !!! FOUND MOCK TRADE LOG MATCH (ID={log_id}) !!!")
                    print("   -> Deleting from TRADELOG_MOCK...")
                    session.execute(text(f"DELETE FROM TRADELOG_MOCK WHERE LOG_ID = {log_id}")) # Simple delete
                    print("   -> Deleted.")

        except Exception as e:
             print(f"Error checking MOCK tables: {e}")
    
if __name__ == "__main__":
    cleanup_mock_data()
