
import os
import sys
from sqlalchemy import text

# Add project root to path
sys.path.append(os.getcwd())

from shared.db.connection import init_engine, session_scope, dispose_engine
import logging

logging.basicConfig(level=logging.INFO)

def verify_mock_tradelog():
    os.environ['TRADING_MODE'] = 'MOCK'
    os.environ['MARIADB_PORT'] = '3307' 
    
    dispose_engine()
    init_engine()
    
    with session_scope() as session:
        print("--- Checking TRADELOG_MOCK ---")
        # Check recent sell log for 005930
        result = session.execute(text("""
            SELECT LOG_ID, STOCK_CODE, QUANTITY, TRADE_TYPE, PRICE, TRADE_TIMESTAMP 
            FROM TRADELOG_MOCK 
            WHERE STOCK_CODE = '005930' AND TRADE_TYPE = 'SELL'
            ORDER BY LOG_ID DESC LIMIT 5
        """)).fetchall()
        
        if not result:
            print("No SELL logs found for 005930 in TRADELOG_MOCK.")
        else:
            print(f"Found {len(result)} SELL logs:")
            for row in result:
                print(f" - ID={row[0]}, Code={row[1]}, Qty={row[2]}, Type={row[3]}, Price={row[4]}, Time={row[5]}")

if __name__ == "__main__":
    verify_mock_tradelog()
