
import sys
import os
sys.path.append(os.getcwd())
from shared.db.connection import session_scope, ensure_engine_initialized
from shared.db import repository as repo
from sqlalchemy import text

def check_trade_log():
    ensure_engine_initialized()
    with session_scope() as session:
        # Check for any trades today
        sql = text("SELECT * FROM TRADELOG WHERE TRADE_TIMESTAMP > DATE_SUB(NOW(), INTERVAL 24 HOUR) ORDER BY TRADE_TIMESTAMP DESC")
        result = session.execute(sql)
        rows = result.fetchall()
        
        print(f"--- Trades in last 24h: {len(rows)} ---")
        for row in rows:
            print(f"[{row.TRADE_TYPE}] {row.STOCK_CODE} at {row.TRADE_TIMESTAMP}")

if __name__ == "__main__":
    check_trade_log()
